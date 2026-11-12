"""Тесты резервной ветви ``otherwise`` и диагностики условных групп."""

from __future__ import annotations

import unittest
import warnings
from dataclasses import dataclass, field

from ciao import (
    ActionExecutionError,
    AmbiguousTransitionError,
    Automaton,
    AutomatonContext,
    AutomatonObject,
    GuardExecutionError,
    MissingOtherwiseWarning,
    ModelValidationError,
    NoTransitionError,
    Program,
    Runtime,
    State,
    StepStatus,
    action,
    compile_program,
    guard,
    provided_command,
    transition,
)
from examples.array_sum import CalculationMode, StartInput, SumController, SumView
from examples.array_sum.program import build_sample


@dataclass
class DecisionContext(AutomatonContext):
    first_enabled: bool = False
    second_enabled: bool = False
    guard_calls: list[str] = field(default_factory=list)
    branch: str | None = None


class DecisionAutomaton(Automaton[DecisionContext]):
    ready = State(initial=True)
    first_done = State()
    second_done = State()
    fallback_done = State()

    @provided_command
    def decide(self) -> None:
        ...

    @guard
    def first_guard(self, ctx: DecisionContext) -> bool:
        ctx.guard_calls.append("first")
        return ctx.first_enabled

    @guard
    def second_guard(self, ctx: DecisionContext) -> bool:
        ctx.guard_calls.append("second")
        return ctx.second_enabled

    @action
    def mark_first(self, ctx: DecisionContext) -> None:
        ctx.branch = "first"

    @action
    def mark_second(self, ctx: DecisionContext) -> None:
        ctx.branch = "second"

    @action
    def mark_fallback(self, ctx: DecisionContext) -> None:
        ctx.branch = "fallback"

    first = transition(
        source=ready,
        event=decide,
        guard=first_guard,
        actions=(mark_first,),
        target=first_done,
    )
    second = transition(
        source=ready,
        event=decide,
        guard=second_guard,
        actions=(mark_second,),
        target=second_done,
    )
    fallback = transition(
        source=ready,
        event=decide,
        otherwise=True,
        actions=(mark_fallback,),
        target=fallback_done,
    )


@dataclass
class IncompleteContext(AutomatonContext):
    calls: int = 0


class IncompleteAutomaton(Automaton[IncompleteContext]):
    ready = State(initial=True)

    @provided_command
    def decide(self) -> None:
        ...

    @guard
    def never(self, ctx: IncompleteContext) -> bool:
        ctx.calls += 1
        return False

    branch = transition(
        source=ready,
        event=decide,
        guard=never,
        target=ready,
    )


class NoGroupAutomaton(Automaton[IncompleteContext]):
    ready = State(initial=True)

    @provided_command
    def decide(self) -> None:
        ...


class UnconditionalAutomaton(Automaton[IncompleteContext]):
    ready = State(initial=True)

    @provided_command
    def decide(self) -> None:
        ...

    branch = transition(
        source=ready,
        event=decide,
        target=ready,
    )


class OtherwiseRuntimeTests(unittest.TestCase):
    def _decision_runtime(
        self,
        *,
        first: bool,
        second: bool,
    ) -> tuple[Runtime, AutomatonObject]:
        object_ref = AutomatonObject(
            "decision",
            DecisionAutomaton,
            DecisionContext(first_enabled=first, second_enabled=second),
        )
        return Runtime(Program(objects=(object_ref,))), object_ref

    def test_single_true_guard_wins_and_all_guards_run_once(self) -> None:
        runtime, object_ref = self._decision_runtime(first=True, second=False)
        runtime.send(object_ref, DecisionAutomaton.decide)

        result = runtime.step()

        snapshot = runtime.snapshot(object_ref)
        self.assertEqual("first", snapshot.branch)
        self.assertEqual(("first", "second"), tuple(snapshot.guard_calls))
        self.assertIs(DecisionAutomaton.first_done, snapshot.state)
        self.assertEqual("first", result.transition)
        self.assertEqual("first", runtime.trace[-1].transition)

    def test_all_false_guards_select_otherwise_and_run_its_action(self) -> None:
        runtime, object_ref = self._decision_runtime(first=False, second=False)
        runtime.send(object_ref, DecisionAutomaton.decide)

        result = runtime.step()

        snapshot = runtime.snapshot(object_ref)
        self.assertEqual("fallback", snapshot.branch)
        self.assertEqual(("first", "second"), tuple(snapshot.guard_calls))
        self.assertIs(DecisionAutomaton.fallback_done, snapshot.state)
        self.assertEqual("fallback", result.transition)

    def test_second_true_guard_is_selected_without_priority(self) -> None:
        runtime, object_ref = self._decision_runtime(first=False, second=True)
        runtime.send(object_ref, DecisionAutomaton.decide)

        result = runtime.step()

        self.assertEqual("second", result.transition)
        self.assertEqual("second", runtime.snapshot(object_ref).branch)

    def test_two_true_guards_are_ambiguous_even_with_otherwise(self) -> None:
        runtime, object_ref = self._decision_runtime(first=True, second=True)
        runtime.send(object_ref, DecisionAutomaton.decide)

        with self.assertRaises(AmbiguousTransitionError):
            runtime.step()

        snapshot = runtime.snapshot(object_ref)
        self.assertEqual(("first", "second"), tuple(snapshot.guard_calls))
        self.assertIsNone(snapshot.branch)
        self.assertIs(DecisionAutomaton.ready, snapshot.state)
        self.assertIsNone(runtime.trace[-1].transition)

    def test_empty_queue_does_not_evaluate_guards_or_otherwise(self) -> None:
        runtime, object_ref = self._decision_runtime(first=False, second=False)

        result = runtime.step()

        self.assertEqual(StepStatus.EMPTY, result.status)
        self.assertEqual((), tuple(runtime.snapshot(object_ref).guard_calls))
        self.assertIs(DecisionAutomaton.ready, runtime.snapshot(object_ref).state)

    def test_guard_exception_does_not_select_otherwise(self) -> None:
        class Exploding(Automaton[IncompleteContext]):
            ready = State(initial=True)
            done = State()

            @provided_command
            def decide(self) -> None:
                ...

            @guard
            def accepted(self, ctx: IncompleteContext) -> bool:
                ctx.calls += 1
                return True

            @guard
            def explode(self, ctx: IncompleteContext) -> bool:
                ctx.calls += 1
                raise ValueError("boom")

            accepted_branch = transition(
                source=ready,
                event=decide,
                guard=accepted,
                target=done,
            )
            exploding_branch = transition(
                source=ready,
                event=decide,
                guard=explode,
                target=done,
            )
            fallback = transition(
                source=ready,
                event=decide,
                otherwise=True,
                target=done,
            )

        object_ref = AutomatonObject("exploding", Exploding, IncompleteContext())
        runtime = Runtime(Program(objects=(object_ref,)))
        runtime.send(object_ref, Exploding.decide)

        with self.assertRaisesRegex(GuardExecutionError, "Ошибка Guard"):
            runtime.step()

        self.assertIs(Exploding.ready, runtime.snapshot(object_ref).state)
        self.assertEqual(2, runtime.snapshot(object_ref).calls)
        self.assertIsNone(runtime.trace[-1].transition)

    def test_action_error_trace_keeps_selected_transition_name(self) -> None:
        class FailingAction(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            @action
            def fail(self, ctx: IncompleteContext) -> None:
                raise ValueError("boom")

            selected = transition(
                source=ready,
                event=decide,
                actions=(fail,),
                target=ready,
            )

        object_ref = AutomatonObject(
            "failing_action",
            FailingAction,
            IncompleteContext(),
        )
        runtime = Runtime(Program(objects=(object_ref,)))
        runtime.send(object_ref, FailingAction.decide)

        with self.assertRaises(ActionExecutionError):
            runtime.step()

        self.assertEqual("selected", runtime.trace[-1].transition)

    def test_strict_and_non_strict_incomplete_group(self) -> None:
        strict_object = AutomatonObject(
            "strict_incomplete",
            IncompleteAutomaton,
            IncompleteContext(),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MissingOtherwiseWarning)
            strict = Runtime(Program(objects=(strict_object,)))
        strict.send(strict_object, IncompleteAutomaton.decide)
        with self.assertRaises(NoTransitionError):
            strict.step()
        self.assertIn("Все Guard ложны", strict.trace[-1].error or "")
        self.assertIsNone(strict.trace[-1].transition)

        non_strict_object = AutomatonObject(
            "non_strict_incomplete",
            IncompleteAutomaton,
            IncompleteContext(),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MissingOtherwiseWarning)
            non_strict = Runtime(
                Program(objects=(non_strict_object,)),
                strict=False,
            )
        non_strict.send(non_strict_object, IncompleteAutomaton.decide)
        result = non_strict.step()
        self.assertEqual(StepStatus.IGNORED, result.status)
        self.assertIn("Все Guard ложны", result.error or "")
        self.assertIsNone(result.transition)

    def test_ignored_reason_distinguishes_missing_group(self) -> None:
        object_ref = AutomatonObject(
            "no_group",
            NoGroupAutomaton,
            IncompleteContext(),
        )
        runtime = Runtime(Program(objects=(object_ref,)), strict=False)
        runtime.send(object_ref, NoGroupAutomaton.decide)

        result = runtime.step()

        self.assertEqual(StepStatus.IGNORED, result.status)
        self.assertIn("переходы не объявлены", result.error or "")
        self.assertNotIn("Все Guard ложны", result.error or "")

    def test_sample_uses_otherwise_for_last_step(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((7,), CalculationMode.STEP_BY_STEP),
        )
        runtime.run()

        runtime.send(sample.view, SumView.next_clicked)
        runtime.step()
        result = runtime.step()

        self.assertEqual("on_last_step_tick", result.transition)
        self.assertIs(
            SumController.publishing,
            runtime.snapshot(sample.controller).state,
        )
        self.assertGreater(runtime.pending_messages, 0)


class OtherwiseCompilerTests(unittest.TestCase):
    def test_warning_is_emitted_once_per_class_group(self) -> None:
        first = AutomatonObject("first", IncompleteAutomaton, IncompleteContext())
        second = AutomatonObject("second", IncompleteAutomaton, IncompleteContext())

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            compile_program(Program(objects=(first, second)))

        matching = [
            item
            for item in captured
            if issubclass(item.category, MissingOtherwiseWarning)
        ]
        self.assertEqual(1, len(matching))
        message = str(matching[0].message)
        self.assertIn("IncompleteAutomaton", message)
        self.assertIn("ready", message)
        self.assertIn("decide", message)

    def test_complete_and_unconditional_groups_do_not_warn(self) -> None:
        decision = AutomatonObject(
            "decision",
            DecisionAutomaton,
            DecisionContext(),
        )
        unconditional = AutomatonObject(
            "unconditional",
            UnconditionalAutomaton,
            IncompleteContext(),
        )
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            compile_program(Program(objects=(decision, unconditional)))

        self.assertFalse(
            any(issubclass(item.category, MissingOtherwiseWarning) for item in captured)
        )

    def test_invalid_otherwise_declarations_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            transition(
                source=DecisionAutomaton.ready,
                event=DecisionAutomaton.decide,
                target=DecisionAutomaton.ready,
                otherwise=1,  # type: ignore[arg-type]
            )

        class GuardAndOtherwise(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            @guard
            def condition(self, ctx: IncompleteContext) -> bool:
                return True

            invalid = transition(
                source=ready,
                event=decide,
                guard=condition,
                otherwise=True,
                target=ready,
            )

        class TwoOtherwise(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            @guard
            def condition(self, ctx: IncompleteContext) -> bool:
                return False

            guarded = transition(
                source=ready,
                event=decide,
                guard=condition,
                target=ready,
            )
            first = transition(
                source=ready,
                event=decide,
                otherwise=True,
                target=ready,
            )
            second = transition(
                source=ready,
                event=decide,
                otherwise=True,
                target=ready,
            )

        class MixedUnconditional(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            @guard
            def condition(self, ctx: IncompleteContext) -> bool:
                return True

            unconditional = transition(
                source=ready,
                event=decide,
                target=ready,
            )
            guarded = transition(
                source=ready,
                event=decide,
                guard=condition,
                target=ready,
            )

        class LoneOtherwise(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            fallback = transition(
                source=ready,
                event=decide,
                otherwise=True,
                target=ready,
            )

        for automaton_type in (
            GuardAndOtherwise,
            TwoOtherwise,
            MixedUnconditional,
            LoneOtherwise,
        ):
            with self.subTest(automaton=automaton_type.__name__):
                object_ref = AutomatonObject(
                    "invalid",
                    automaton_type,
                    IncompleteContext(),
                )
                with self.assertRaises(ModelValidationError):
                    compile_program(Program(objects=(object_ref,)))

    def test_inherited_guard_group_can_receive_otherwise_in_child(self) -> None:
        class Base(Automaton[IncompleteContext]):
            ready = State(initial=True)

            @provided_command
            def decide(self) -> None:
                ...

            @guard
            def condition(self, ctx: IncompleteContext) -> bool:
                return False

            guarded = transition(
                source=ready,
                event=decide,
                guard=condition,
                target=ready,
            )

        class Child(Base):
            fallback = transition(
                source=Base.ready,
                event=Base.decide,
                otherwise=True,
                target=Base.ready,
            )

        object_ref = AutomatonObject("child", Child, IncompleteContext())
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            runtime = Runtime(Program(objects=(object_ref,)))
        self.assertFalse(
            any(issubclass(item.category, MissingOtherwiseWarning) for item in captured)
        )

        runtime.send(object_ref, Child.decide)
        result = runtime.step()
        self.assertEqual("fallback", result.transition)


if __name__ == "__main__":
    unittest.main()
