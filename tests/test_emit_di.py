"""Проверки DI-контракта ``Emit`` / ``Emits``."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Annotated, Optional

from ciao import (
    ActionExecutionError,
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Connection,
    Emit,
    Emits,
    InvalidRuntimeCallError,
    ModelValidationError,
    Program,
    Runtime,
    State,
    action,
    compile_program,
    guard,
    provided_command,
    required_command,
    required_query,
    transition,
)


@dataclass
class ReceiverContext(AutomatonContext):
    events: list[tuple[str, object]] = field(default_factory=list)


class Receiver(Automaton[ReceiverContext]):
    ready = State(initial=True)

    @provided_command
    def accept(self, value: int) -> None:
        ...

    @provided_command
    def write_log(self, message: str) -> None:
        ...

    @action
    def store(self, ctx: ReceiverContext, value: int) -> None:
        ctx.events.append(("accept", value))

    @action
    def store_log(self, ctx: ReceiverContext, message: str) -> None:
        ctx.events.append(("log", message))

    on_accept = transition(
        source=ready,
        event=accept,
        actions=(store,),
        target=ready,
    )
    on_log = transition(
        source=ready,
        event=write_log,
        actions=(store_log,),
        target=ready,
    )


@dataclass
class SenderContext(AutomatonContext):
    action_calls: int = 0


def _send_value(capability: Emit, value: int) -> None:
    """Проверяет допустимую передачу Emit синхронному helper."""

    capability(value=value)


class SingleSender(Automaton[SenderContext]):
    ready = State(initial=True)

    @provided_command
    def start(self, value: int) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @action(emit=output)
    def publish(
        self,
        ctx: SenderContext,
        value: int,
        *,
        capability: Emit,
    ) -> None:
        ctx.action_calls += 1
        _send_value(capability, value)

    on_start = transition(
        source=ready,
        event=start,
        actions=(publish,),
        target=ready,
    )


class MultiSender(Automaton[SenderContext]):
    ready = State(initial=True)

    @provided_command
    def start(self, include_log: bool) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @required_command
    def log(self, message: str) -> None:
        ...

    @action(emits=(output, log))
    def publish(
        self,
        ctx: SenderContext,
        capabilities: Emits,
        include_log: bool,
    ) -> None:
        ctx.action_calls += 1
        capabilities[self.output](value=1)
        capabilities[self.output](value=2)
        if include_log:
            capabilities[self.log](message="done")

    on_start = transition(
        source=ready,
        event=start,
        actions=(publish,),
        target=ready,
    )


class OneCollectionSender(Automaton[SenderContext]):
    ready = State(initial=True)

    @provided_command
    def start(self) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @action(emits=(output,))
    def publish(self, ctx: SenderContext, capabilities: Emits) -> None:
        ctx.action_calls += 1
        capabilities[self.output](value=7)

    on_start = transition(
        source=ready,
        event=start,
        actions=(publish,),
        target=ready,
    )


_captured: list[Emit] = []


class CapturingSender(Automaton[SenderContext]):
    ready = State(initial=True)

    @provided_command
    def start(self) -> None:
        ...

    @required_command
    def output(self, value: int) -> None:
        ...

    @action(emit=output)
    def capture(self, ctx: SenderContext, capability: Emit) -> None:
        ctx.action_calls += 1
        _captured.append(capability)

    on_start = transition(
        source=ready,
        event=start,
        actions=(capture,),
        target=ready,
    )


def _single_program(
    sender_type: type[Automaton[SenderContext]],
) -> tuple[Program, AutomatonObject, AutomatonObject]:
    sender = AutomatonObject("sender", sender_type, SenderContext())
    receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
    program = Program(
        objects=(sender, receiver),
        connections=(
            Connection(
                required=(sender, sender_type.output),
                provided=(receiver, Receiver.accept),
            ),
        ),
    )
    return program, sender, receiver


class EmitRuntimeTests(unittest.TestCase):
    def test_emit_delivers_one_command_and_supports_keyword_only_di(self) -> None:
        program, sender, receiver = _single_program(SingleSender)
        runtime = Runtime(program)

        runtime.send(sender, SingleSender.start, value=41)
        sender_step = runtime.step()

        self.assertEqual(("accept",), tuple(item.operation for item in sender_step.emitted))
        self.assertEqual([], runtime.snapshot(receiver).events)
        runtime.step()
        self.assertEqual([("accept", 41)], runtime.snapshot(receiver).events)

    def test_emits_preserves_call_order_and_allows_repeated_or_skipped_calls(self) -> None:
        sender = AutomatonObject("sender", MultiSender, SenderContext())
        receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
        runtime = Runtime(
            Program(
                objects=(sender, receiver),
                connections=(
                    Connection(
                        required=(sender, MultiSender.output),
                        provided=(receiver, Receiver.accept),
                    ),
                    Connection(
                        required=(sender, MultiSender.log),
                        provided=(receiver, Receiver.write_log),
                    ),
                ),
            )
        )

        runtime.send(sender, MultiSender.start, include_log=True)
        step = runtime.step()
        self.assertEqual(("accept", "accept", "write_log"), tuple(
            item.operation for item in step.emitted
        ))
        self.assertEqual([], runtime.snapshot(receiver).events)
        runtime.run()
        self.assertEqual(
            [("accept", 1), ("accept", 2), ("log", "done")],
            runtime.snapshot(receiver).events,
        )

        runtime.send(sender, MultiSender.start, include_log=False)
        skipped_step = runtime.step()
        self.assertEqual(2, len(skipped_step.emitted))

    def test_emits_with_one_command_still_injects_emits(self) -> None:
        program, sender, receiver = _single_program(OneCollectionSender)
        runtime = Runtime(program)
        runtime.send(sender, OneCollectionSender.start)
        runtime.run()
        self.assertEqual([("accept", 7)], runtime.snapshot(receiver).events)

    def test_capability_is_invalid_after_action_and_between_runtimes(self) -> None:
        _captured.clear()
        program, sender, _ = _single_program(CapturingSender)
        first = Runtime(program)
        second = Runtime(program)

        first.send(sender, CapturingSender.start)
        second.send(sender, CapturingSender.start)
        first.step()
        second.step()

        self.assertEqual(2, len(_captured))
        self.assertIsNot(_captured[0], _captured[1])
        for capability in _captured:
            with self.assertRaises(InvalidRuntimeCallError):
                capability(value=10)

    def test_two_instances_route_capabilities_to_their_own_connections(self) -> None:
        first_sender = AutomatonObject("first_sender", SingleSender, SenderContext())
        second_sender = AutomatonObject("second_sender", SingleSender, SenderContext())
        first_receiver = AutomatonObject("first_receiver", Receiver, ReceiverContext())
        second_receiver = AutomatonObject("second_receiver", Receiver, ReceiverContext())
        runtime = Runtime(
            Program(
                objects=(
                    first_sender,
                    second_sender,
                    first_receiver,
                    second_receiver,
                ),
                connections=(
                    Connection(
                        required=(first_sender, SingleSender.output),
                        provided=(first_receiver, Receiver.accept),
                    ),
                    Connection(
                        required=(second_sender, SingleSender.output),
                        provided=(second_receiver, Receiver.accept),
                    ),
                ),
            )
        )
        runtime.send(first_sender, SingleSender.start, value=10)
        runtime.send(second_sender, SingleSender.start, value=20)
        runtime.run()

        self.assertEqual([("accept", 10)], runtime.snapshot(first_receiver).events)
        self.assertEqual([("accept", 20)], runtime.snapshot(second_receiver).events)

    def test_emits_rejects_undeclared_command_during_action(self) -> None:
        class InvalidSender(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def first(self, value: int) -> None:
                ...

            @required_command
            def second(self, value: int) -> None:
                ...

            @action(emits=(first,))
            def publish(self, ctx: SenderContext, capabilities: Emits) -> None:
                capabilities[self.second](value=1)

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        sender = AutomatonObject("sender", InvalidSender, SenderContext())
        receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
        runtime = Runtime(
            Program(
                objects=(sender, receiver),
                connections=(
                    Connection(
                        required=(sender, InvalidSender.first),
                        provided=(receiver, Receiver.accept),
                    ),
                    Connection(
                        required=(sender, InvalidSender.second),
                        provided=(receiver, Receiver.accept),
                    ),
                ),
            )
        )
        runtime.send(sender, InvalidSender.start)

        with self.assertRaises(ActionExecutionError) as captured:
            runtime.step()
        self.assertIsInstance(captured.exception.__cause__, InvalidRuntimeCallError)
        self.assertIn("InvalidSender.publish", str(captured.exception.__cause__))
        self.assertIn("InvalidSender.first", str(captured.exception.__cause__))
        self.assertEqual(0, runtime.pending_messages)


class EmitMetadataAndValidationTests(unittest.TestCase):
    def test_action_metadata_preserves_selected_form(self) -> None:
        self.assertIs(SingleSender.output, SingleSender.publish.emit)
        self.assertIsNone(SingleSender.publish.emits)
        self.assertEqual((SingleSender.output,), SingleSender.publish.outgoing_commands)

        self.assertIsNone(OneCollectionSender.publish.emit)
        self.assertEqual(
            (OneCollectionSender.output,),
            OneCollectionSender.publish.emits,
        )
        self.assertEqual(
            (OneCollectionSender.output,),
            OneCollectionSender.publish.outgoing_commands,
        )
        with self.assertRaises(AttributeError):
            SingleSender.publish.emit = None

        program, _, _ = _single_program(SingleSender)
        definition = compile_program(program).definitions[SingleSender]
        plan = definition.action_injections[SingleSender.publish]
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIs(Emit, plan.capability_type)
        self.assertEqual((SingleSender.output,), plan.commands)

    def test_unsupported_decorator_forms_and_public_construction_are_rejected(self) -> None:
        self.assertFalse(hasattr(Automaton, "emit"))
        with self.assertRaises(TypeError):
            action()
        with self.assertRaises(TypeError):
            action(emits=())
        with self.assertRaises(TypeError):
            action(
                emit=SingleSender.output,
                emits=(SingleSender.output,),
            )
        with self.assertRaises(TypeError):
            action(text=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            guard()
        with self.assertRaises(TypeError):
            guard(text=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Emit()
        with self.assertRaises(TypeError):
            Emits()

    def test_behavior_text_is_optional_declarative_metadata(self) -> None:
        @guard(text="значение положительное")
        def positive(ctx: SenderContext) -> bool:
            return ctx.action_calls >= 0

        @action(text="обновляет значение")
        def update(ctx: SenderContext) -> None:
            ctx.action_calls += 1

        @action
        def unchanged(ctx: SenderContext) -> None:
            ctx.action_calls += 1

        self.assertEqual("значение положительное", positive.text)
        self.assertEqual("обновляет значение", update.text)
        self.assertIsNone(unchanged.text)

    def test_wrong_or_missing_di_annotation_is_rejected(self) -> None:
        class WrongType(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emit=output)
            def publish(self, ctx: SenderContext, capability: Emits) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        object_ref = AutomatonObject("wrong", WrongType, SenderContext())
        with self.assertRaisesRegex(ModelValidationError, "точной аннотацией Emit"):
            Runtime(Program(objects=(object_ref,)))

        class OptionalType(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emit=output)
            def publish(
                self,
                ctx: SenderContext,
                capability: Optional[Emit],
            ) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        object_ref = AutomatonObject("optional", OptionalType, SenderContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))

        class AnnotatedType(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emit=output)
            def publish(
                self,
                ctx: SenderContext,
                capability: Annotated[Emit, "not-exact"],
            ) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        object_ref = AutomatonObject("annotated", AnnotatedType, SenderContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))

    def test_invalid_command_metadata_is_rejected(self) -> None:
        class Foreign(Automaton[SenderContext]):
            ready = State(initial=True)

            @required_command
            def output(self, value: int) -> None:
                ...

        class Invalid(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def value(self) -> int:
                ...

            @action(emits=(Foreign.output, Foreign.output))
            def publish(self, ctx: SenderContext, capabilities: Emits) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        object_ref = AutomatonObject("invalid", Invalid, SenderContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))

    def test_duplicate_provided_and_query_commands_are_rejected(self) -> None:
        class Duplicate(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emits=(output, output))
            def publish(self, ctx: SenderContext, capabilities: Emits) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        class Provided(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @action(emit=start)
            def publish(self, ctx: SenderContext, capability: Emit) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        class Query(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def value(self) -> int:
                ...

            @action(emit=value)
            def publish(self, ctx: SenderContext, capability: Emit) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        for automaton_type in (Duplicate, Provided, Query):
            with self.subTest(automaton=automaton_type.__name__):
                object_ref = AutomatonObject(
                    "invalid",
                    automaton_type,
                    SenderContext(),
                )
                with self.assertRaises(ModelValidationError):
                    Runtime(Program(objects=(object_ref,)))

    def test_di_parameter_default_is_rejected(self) -> None:
        class Invalid(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emit=output)
            def publish(
                self,
                ctx: SenderContext,
                capability: Emit = None,  # type: ignore[assignment]
            ) -> None:
                ...

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        object_ref = AutomatonObject("invalid", Invalid, SenderContext())
        with self.assertRaises(ModelValidationError):
            Runtime(Program(objects=(object_ref,)))

    def test_inherited_action_keeps_command_identity_when_subclass_shadows_name(self) -> None:
        class Base(Automaton[SenderContext]):
            ready = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self, value: int) -> None:
                ...

            @action(emit=output)
            def publish(self, ctx: SenderContext, capability: Emit) -> None:
                capability(value=33)

            on_start = transition(
                source=ready,
                event=start,
                actions=(publish,),
                target=ready,
            )

        class Child(Base):
            @required_command
            def output(self, value: int) -> None:
                ...

        child = AutomatonObject("child", Child, SenderContext())
        receiver = AutomatonObject("receiver", Receiver, ReceiverContext())
        runtime = Runtime(
            Program(
                objects=(child, receiver),
                connections=(
                    Connection(
                        required=(child, Base.output),
                        provided=(receiver, Receiver.accept),
                    ),
                    Connection(
                        required=(child, Child.output),
                        provided=(receiver, Receiver.accept),
                    ),
                ),
            )
        )
        self.assertIs(Base.output, Child.publish.emit)

        runtime.send(child, Child.start)
        runtime.run()
        self.assertEqual([("accept", 33)], runtime.snapshot(receiver).events)


if __name__ == "__main__":
    unittest.main()
