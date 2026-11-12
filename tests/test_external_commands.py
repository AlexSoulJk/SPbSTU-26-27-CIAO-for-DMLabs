"""Тесты external required-команд и общего механизма Runtime binding."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from functools import partial

from ciao import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Connection,
    Emit,
    Emits,
    ExternalBindingConflictError,
    ExternalHandlerExecutionError,
    ExternalHandlerSignatureError,
    ModelValidationError,
    Program,
    Runtime,
    State,
    StepStatus,
    action,
    compile_program,
    provided_command,
    required_command,
    transition,
)


@dataclass
class SourceContext(AutomatonContext):
    publications: int = 0


class ExternalSource(Automaton[SourceContext]):
    idle = State(initial=True)
    done = State()

    @provided_command(external=True)
    def start(self, values: list[int]) -> None:
        ...

    @required_command(external=True, text="показать снимок")
    def render(self, data: list[int], *, label: str) -> None:
        ...

    @required_command
    def forward(self, value: int) -> None:
        ...

    @action(emits=(render, forward))
    def publish(
        self,
        ctx: SourceContext,
        values: list[int],
        emits: Emits,
    ) -> None:
        emits[self.render](values, label="snapshot")
        values.append(99)
        emits[self.forward](len(values))
        ctx.publications += 1

    on_start = transition(
        source=idle,
        event=start,
        actions=(publish,),
        target=done,
    )


@dataclass
class SinkContext(AutomatonContext):
    received: list[int] = field(default_factory=list)


class Sink(Automaton[SinkContext]):
    ready = State(initial=True)

    @provided_command
    def receive(self, value: int) -> None:
        ...

    @action
    def remember(self, ctx: SinkContext, value: int) -> None:
        ctx.received.append(value)

    on_receive = transition(
        source=ready,
        event=receive,
        actions=(remember,),
        target=ready,
    )


class MissingRoute(Automaton[SourceContext]):
    ready = State(initial=True)

    @required_command
    def ordinary(self) -> None:
        ...


def _program() -> tuple[Program, AutomatonObject, AutomatonObject]:
    source = AutomatonObject("source", ExternalSource, SourceContext())
    sink = AutomatonObject("sink", Sink, SinkContext())
    return (
        Program(
            objects=(source, sink),
            connections=(
                Connection(
                    (source, ExternalSource.forward),
                    (sink, Sink.receive),
                ),
            ),
        ),
        source,
        sink,
    )


class ExternalCommandTests(unittest.TestCase):
    def test_external_required_compiles_without_domain_connection(self) -> None:
        program, _, _ = _program()
        compile_program(program)

        invalid = AutomatonObject("invalid", MissingRoute, SourceContext())
        with self.assertRaises(ModelValidationError):
            compile_program(Program(objects=(invalid,)))

    def test_external_delivery_is_a_separate_fifo_step_with_snapshot(self) -> None:
        program, source, sink = _program()
        runtime = Runtime(program)
        handled: list[tuple[list[int], str]] = []

        def handler(value: list[int], *, label: str) -> None:
            handled.append((value, label))

        runtime.bind_external((source, ExternalSource.render), handler)
        original = [1]
        runtime.send(source, ExternalSource.start, values=original)

        transition_result = runtime.step()
        self.assertEqual([], handled)
        self.assertEqual([1], original)
        self.assertEqual(2, runtime.pending_messages)
        self.assertEqual(
            ["<external>", "sink"],
            [message.target for message in transition_result.emitted],
        )
        self.assertEqual((1,), transition_result.emitted[0].parameters["data"])

        delivery_result = runtime.step()
        self.assertEqual([([1], "snapshot")], handled)
        self.assertEqual("render", delivery_result.operation)
        self.assertEqual(StepStatus.PROCESSED, delivery_result.status)
        self.assertEqual("done", delivery_result.source_state)
        self.assertEqual("done", delivery_result.target_state)

        runtime.step()
        self.assertEqual([2], runtime.snapshot(sink).context.received)
        self.assertEqual(["start", "render", "receive"], [e.operation for e in runtime.trace])

    def test_missing_or_disposed_handler_does_not_cancel_delivery(self) -> None:
        program, source, _ = _program()
        runtime = Runtime(program)
        handled: list[list[int]] = []

        def handler(value: list[int], *, label: str) -> None:
            handled.append(value)

        subscription = runtime.bind_external(
            (source, ExternalSource.render),
            handler,
        )
        runtime.send(source, ExternalSource.start, values=[3])
        runtime.step()
        subscription.dispose()
        subscription.dispose()
        self.assertFalse(subscription.active)

        result = runtime.step()
        self.assertEqual(StepStatus.PROCESSED, result.status)
        self.assertEqual([], handled)

        # После удаления прежней регистрации endpoint можно связать заново.
        replacement = runtime.bind_external(
            (source, ExternalSource.render),
            handler,
        )
        self.assertTrue(replacement.active)

    def test_second_live_handler_is_rejected(self) -> None:
        program, source, _ = _program()
        runtime = Runtime(program)

        def handler(value: list[int], *, label: str) -> None:
            pass

        runtime.bind_external((source, ExternalSource.render), handler)
        with self.assertRaises(ExternalBindingConflictError):
            runtime.bind_external((source, ExternalSource.render), handler)

    def test_handler_signature_is_checked_at_registration(self) -> None:
        program, source, _ = _program()

        def wrong_type(value: str, *, label: str) -> None:
            pass

        def wrong_keyword(value: list[int], *, caption: str) -> None:
            pass

        def wrong_return(value: list[int], *, label: str) -> int:
            return 1

        def variadic(*args: object) -> None:
            pass

        for callback in (wrong_type, wrong_keyword, wrong_return, variadic):
            runtime = Runtime(program)
            with self.subTest(callback=callback.__name__):
                with self.assertRaises(ExternalHandlerSignatureError):
                    runtime.bind_external(
                        (source, ExternalSource.render),
                        callback,
                    )

    def test_bound_method_callable_object_and_partial_are_supported(self) -> None:
        program, source, _ = _program()

        class Receiver:
            def __init__(self) -> None:
                self.values: list[list[int]] = []

            def method(self, value: list[int], *, label: str) -> None:
                self.values.append(value)

            def __call__(self, value: list[int], *, label: str) -> None:
                self.values.append(value)

        receiver = Receiver()
        callbacks = [receiver.method, receiver, partial(receiver)]

        def prefixed(
            prefix: str,
            value: list[int],
            *,
            label: str,
        ) -> None:
            receiver.values.append(value)

        callbacks.append(partial(prefixed, "prefix"))
        for callback in callbacks:
            runtime = Runtime(program)
            token = runtime.bind_external(
                (source, ExternalSource.render),
                callback,
            )
            self.assertTrue(token.active)

    def test_handler_error_belongs_to_delivery_and_keeps_remaining_fifo(self) -> None:
        program, source, sink = _program()
        runtime = Runtime(program)

        def failing(value: list[int], *, label: str) -> None:
            raise ValueError("UI failed")

        runtime.bind_external((source, ExternalSource.render), failing)
        runtime.send(source, ExternalSource.start, values=[5])
        runtime.step()

        with self.assertRaises(ExternalHandlerExecutionError) as caught:
            runtime.step()
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertEqual("done", runtime.snapshot(source).state.name)
        self.assertEqual(1, runtime.pending_messages)
        self.assertEqual(StepStatus.ERROR, runtime.trace[-1].status)
        self.assertEqual("render", runtime.trace[-1].operation)

        runtime.step()
        self.assertEqual([2], runtime.snapshot(sink).context.received)

    def test_subscribe_returns_independent_subscription(self) -> None:
        program, source, _ = _program()
        runtime = Runtime(program)
        first_events: list[str] = []
        second_events: list[str] = []
        first = runtime.subscribe(lambda event: first_events.append(event.operation))
        second = runtime.subscribe(lambda event: second_events.append(event.operation))
        first.dispose()

        runtime.send(source, ExternalSource.start, values=[])
        runtime.run()
        self.assertEqual([], first_events)
        self.assertEqual(["start", "render", "receive"], second_events)
        self.assertTrue(second.active)


if __name__ == "__main__":
    unittest.main()
