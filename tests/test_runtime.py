"""Модульные тесты согласованной семантики runtime."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from ciao import (
    ActionExecutionError,
    AmbiguousTransitionError,
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Connection,
    Emit,
    ModelValidationError,
    NoTransitionError,
    Program,
    Query,
    RunStatus,
    Runtime,
    State,
    StepLimitExceeded,
    StepStatus,
    action,
    guard,
    provided_command,
    provided_query,
    required_command,
    required_query,
    transition,
)
from examples.array_sum.headless_run import (
    calculate_sum,
    format_operation_trace,
    run_calculation,
)
from examples.array_sum.automatos import (
    SumContext,
    SumController,
    SumView,
    ViewContext,
)
from examples.array_sum.contracts import CalculationMode, StartInput
from examples.array_sum.program import build_sample


@dataclass
class ProviderContext(AutomatonContext):
    value: int = 42


class Provider(Automaton[ProviderContext]):
    ready = State(initial=True)

    @provided_query
    def read_value(self, ctx: ProviderContext) -> int:
        return ctx.value


@dataclass
class ConsumerContext(AutomatonContext):
    received: int | None = None


class Consumer(Automaton[ConsumerContext]):
    ready = State(initial=True)

    @provided_command
    def load(self) -> None:
        ...

    @required_query
    def source_value(self) -> int:
        ...

    @action(query=source_value)
    def load_value(self, ctx: ConsumerContext, query: Query) -> None:
        ctx.received = query()

    on_load = transition(
        source=ready,
        event=load,
        actions=(load_value,),
        target=ready,
    )


@dataclass
class AmbiguousContext(AutomatonContext):
    count: int = 0


class AmbiguousAutomaton(Automaton[AmbiguousContext]):
    ready = State(initial=True)

    @provided_command
    def fire(self) -> None:
        ...

    @action
    def increment(self, ctx: AmbiguousContext) -> None:
        ctx.count += 1

    @guard
    def first_enabled(self, ctx: AmbiguousContext) -> bool:
        return True

    @guard
    def second_enabled(self, ctx: AmbiguousContext) -> bool:
        return True

    first = transition(
        source=ready,
        event=fire,
        guard=first_enabled,
        actions=(increment,),
        target=ready,
    )
    second = transition(
        source=ready,
        event=fire,
        guard=second_enabled,
        actions=(increment,),
        target=ready,
    )
    fallback = transition(
        source=ready,
        event=fire,
        otherwise=True,
        target=ready,
    )


@dataclass
class ReceiverContext(AutomatonContext):
    received: int = 0


class Receiver(Automaton[ReceiverContext]):
    ready = State(initial=True)

    @provided_command
    def accept(self, value: int) -> None:
        ...

    @action
    def store(self, ctx: ReceiverContext, value: int) -> None:
        ctx.received = value

    on_accept = transition(
        source=ready,
        event=accept,
        actions=(store,),
        target=ready,
    )


@dataclass
class FailingContext(AutomatonContext):
    changed: int = 0


class FailingSender(Automaton[FailingContext]):
    ready = State(initial=True)
    finished = State()

    @provided_command
    def start(self) -> None:
        ...

    @required_command
    def notify(self, value: int) -> None:
        ...

    @action(emit=notify)
    def emit_then_fail(self, ctx: FailingContext, emit: Emit) -> None:
        ctx.changed += 1
        emit(value=ctx.changed)
        raise ValueError("ожидаемая ошибка")

    on_start = transition(
        source=ready,
        event=start,
        actions=(emit_then_fail,),
        target=finished,
    )


@dataclass
class RenamedSenderContext(AutomatonContext):
    sent: bool = False


class RenamedSender(Automaton[RenamedSenderContext]):
    ready = State(initial=True)

    @provided_command
    def start(self) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @action(emit=output)
    def publish(self, ctx: RenamedSenderContext, emit: Emit) -> None:
        emit(value=91)
        ctx.sent = True

    on_start = transition(
        source=ready,
        event=start,
        actions=(publish,),
        target=ready,
    )


@dataclass
class RenamedReceiverContext(AutomatonContext):
    received: int = 0


class RenamedReceiver(Automaton[RenamedReceiverContext]):
    ready = State(initial=True)

    @provided_command
    def accept(self, number: int) -> None:
        ...

    @action
    def store(self, ctx: RenamedReceiverContext, number: int) -> None:
        ctx.received = number

    on_accept = transition(
        source=ready,
        event=accept,
        actions=(store,),
        target=ready,
    )


@dataclass
class GuardEmitterContext(AutomatonContext):
    checked: bool = False


class GuardEmitter(Automaton[GuardEmitterContext]):
    ready = State(initial=True)

    @provided_command
    def start(self) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @guard
    def invalid_guard(self, ctx: GuardEmitterContext, emit: Emit) -> bool:
        ctx.checked = True
        emit(value=1)
        return True

    on_start = transition(
        source=ready,
        event=start,
        guard=invalid_guard,
        target=ready,
    )


class RuntimeTests(unittest.TestCase):
    def test_array_sum_boundary_cases(self) -> None:
        for values, expected in (([], 0), ([7], 7), ([2, 4, 6], 12)):
            with self.subTest(values=values):
                total, view = calculate_sum(values)
                self.assertEqual(expected, total)
                self.assertEqual(expected, view.total)
                self.assertEqual(len(values), view.tick_count)

    def test_array_sum_exposes_readable_operation_trace(self) -> None:
        result = run_calculation([2])

        self.assertEqual(
            [
                "init_clicked",
                "start",
                "render_data",
                "render_controls",
                "render_status",
                "tick",
                "draw",
                "render_data",
                "render_controls",
                "render_status",
                "draw_completed",
            ],
            [event.operation for event in result.trace],
        )
        rendered = format_operation_trace(result.trace)
        self.assertIn("view.init_clicked(request=StartInput", rendered)
        self.assertIn(
            "running_all --on_last_automatic_tick--> publishing",
            rendered,
        )
        self.assertIn("emit -> view.draw(", rendered)
        self.assertIn("controller.draw_completed()", rendered)

    def test_contexts_are_independent_between_runtimes(self) -> None:
        sample = build_sample()
        first = Runtime(sample.program)
        second = Runtime(sample.program)

        first.send(
            sample.view,
            SumView.init_clicked,
            StartInput((5,), CalculationMode.STEP_BY_STEP),
        )
        first.run()
        first.send(sample.view, SumView.next_clicked)
        first.run()

        self.assertEqual(5, first.snapshot(sample.controller).total)
        self.assertEqual(0, second.snapshot(sample.controller).total)
        self.assertIs(SumController.idle, second.snapshot(sample.controller).state)

    def test_emitted_command_is_processed_after_current_transition(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((3,), CalculationMode.STEP_BY_STEP),
        )
        runtime.run()
        runtime.send(sample.view, SumView.next_clicked)

        request_step = runtime.step()
        self.assertEqual("next_clicked", request_step.operation)

        controller_step = runtime.step()
        self.assertEqual(StepStatus.PROCESSED, controller_step.status)
        self.assertEqual(1, len(controller_step.emitted))
        self.assertEqual(0, runtime.snapshot(sample.view).total)
        self.assertIs(
            SumController.publishing,
            runtime.snapshot(sample.controller).state,
        )

        # controls/status команды Next уже находились перед draw в общей FIFO.
        runtime.step()
        runtime.step()
        view_step = runtime.step()
        self.assertEqual("draw", view_step.operation)
        self.assertEqual(4, len(view_step.emitted))
        self.assertEqual(3, runtime.snapshot(sample.view).total)
        self.assertIs(
            SumController.publishing,
            runtime.snapshot(sample.controller).state,
        )

        runtime.step()
        runtime.step()
        runtime.step()
        acknowledgement_step = runtime.step()
        self.assertEqual("draw_completed", acknowledgement_step.operation)
        self.assertIs(
            SumController.completed,
            runtime.snapshot(sample.controller).state,
        )

    def test_snapshot_is_detached_from_runtime_context(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        snapshot = runtime.snapshot(sample.controller)
        snapshot.context.total = 100
        self.assertEqual(0, runtime.snapshot(sample.controller).total)

    def test_required_query_is_synchronous(self) -> None:
        provider = AutomatonObject("provider", Provider, ProviderContext(value=73))
        consumer = AutomatonObject("consumer", Consumer, ConsumerContext())
        program = Program(
            objects=(provider, consumer),
            connections=(
                Connection(
                    required=(consumer, Consumer.source_value),
                    provided=(provider, Provider.read_value),
                ),
            ),
        )
        runtime = Runtime(program)
        runtime.send(consumer, Consumer.load)
        result = runtime.step()

        self.assertEqual(StepStatus.PROCESSED, result.status)
        self.assertEqual(73, runtime.snapshot(consumer).received)
        self.assertEqual(0, runtime.pending_messages)

    def test_ambiguous_transitions_are_rejected_at_runtime(self) -> None:
        object_ref = AutomatonObject(
            "ambiguous",
            AmbiguousAutomaton,
            AmbiguousContext(),
        )
        runtime = Runtime(Program(objects=(object_ref,)))
        runtime.send(object_ref, AmbiguousAutomaton.fire)
        with self.assertRaises(AmbiguousTransitionError):
            runtime.step()

    def test_strict_and_non_strict_missing_transition(self) -> None:
        sample = build_sample()
        strict = Runtime(sample.program)
        strict.send(sample.controller, SumController.reset)
        with self.assertRaises(NoTransitionError):
            strict.step()

        non_strict = Runtime(sample.program, strict=False)
        non_strict.send(sample.controller, SumController.reset)
        result = non_strict.step()
        self.assertEqual(StepStatus.IGNORED, result.status)
        self.assertEqual(StepStatus.IGNORED, non_strict.trace[-1].status)

    def test_run_reports_limit_in_non_strict_mode(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program, strict=False)
        request = StartInput((), CalculationMode.STEP_BY_STEP)
        runtime.send(sample.view, SumView.init_clicked, request)
        runtime.send(sample.view, SumView.init_clicked, request)

        result = runtime.run(max_steps=1)
        self.assertEqual(RunStatus.LIMIT_REACHED, result.status)
        self.assertEqual(5, runtime.pending_messages)

    def test_action_failure_keeps_state_and_discards_buffer(self) -> None:
        sender = AutomatonObject("sender", FailingSender, FailingContext())
        receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
        program = Program(
            objects=(sender, receiver),
            connections=(
                Connection(
                    required=(sender, FailingSender.notify),
                    provided=(receiver, Receiver.accept),
                ),
            ),
        )
        runtime = Runtime(program)
        runtime.send(sender, FailingSender.start)

        with self.assertRaises(ActionExecutionError) as captured:
            runtime.step()

        self.assertIsInstance(captured.exception.__cause__, ValueError)
        self.assertIs(FailingSender.ready, runtime.snapshot(sender).state)
        self.assertEqual(1, runtime.snapshot(sender).changed)
        self.assertEqual(0, runtime.pending_messages)
        self.assertEqual(0, runtime.snapshot(receiver).received)

    def test_trace_listener_receives_immutable_event(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        events = []
        runtime.subscribe(events.append)
        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((), CalculationMode.STEP_BY_STEP),
        )
        runtime.step()

        self.assertEqual(1, len(events))
        with self.assertRaises(TypeError):
            events[0].parameters["request"] = StartInput(
                (1,),
                CalculationMode.STEP_BY_STEP,
            )
        self.assertEqual((), events[0].parameters["request"].values)

    def test_connection_translates_different_parameter_names(self) -> None:
        sender = AutomatonObject("sender", RenamedSender, RenamedSenderContext())
        receiver = AutomatonObject(
            "receiver",
            RenamedReceiver,
            RenamedReceiverContext(),
        )
        program = Program(
            objects=(sender, receiver),
            connections=(
                Connection(
                    required=(sender, RenamedSender.output),
                    provided=(receiver, RenamedReceiver.accept),
                ),
            ),
        )
        runtime = Runtime(program)
        runtime.send(sender, RenamedSender.start)
        runtime.run()

        self.assertTrue(runtime.snapshot(sender).sent)
        self.assertEqual(91, runtime.snapshot(receiver).received)

    def test_emit_capability_is_forbidden_inside_guard(self) -> None:
        sender = AutomatonObject("sender", GuardEmitter, GuardEmitterContext())
        receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
        program = Program(
            objects=(sender, receiver),
            connections=(
                Connection(
                    required=(sender, GuardEmitter.output),
                    provided=(receiver, Receiver.accept),
                ),
            ),
        )
        with self.assertRaises(ModelValidationError):
            Runtime(program)

    def test_run_raises_on_limit_in_strict_mode(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((), CalculationMode.STEP_BY_STEP),
        )
        with self.assertRaises(StepLimitExceeded):
            runtime.run(max_steps=0)


class ValidationTests(unittest.TestCase):
    def test_wrong_context_annotation_is_rejected(self) -> None:
        @dataclass
        class WrongContext(AutomatonContext):
            value: int = 0

        class InvalidAutomaton(Automaton[SumContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @action
            def invalid(self, ctx: WrongContext) -> None:
                ctx.value += 1

            on_start = transition(
                source=ready,
                event=start,
                actions=(invalid,),
                target=ready,
            )

        object_ref = AutomatonObject("invalid", InvalidAutomaton, SumContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))

    def test_operation_context_must_match_generic_context(self) -> None:
        @dataclass
        class WrongContext(AutomatonContext):
            value: int = 0

        class InvalidQuery(Automaton[SumContext]):
            ready = State(initial=True)

            @provided_query
            def value(self, ctx: WrongContext) -> int:
                return ctx.value

        object_ref = AutomatonObject("invalid", InvalidQuery, SumContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))


if __name__ == "__main__":
    unittest.main()
