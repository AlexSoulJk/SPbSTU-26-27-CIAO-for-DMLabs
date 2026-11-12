"""Headless-тесты общей template-method части UIConnection."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Callable

from ciao import (
    AutomatonContext,
    AutomatonObject,
    Emit,
    FactoryPayloadSource,
    Program,
    Runtime,
    State,
    Subscription,
    ViewAutomaton,
    action,
    provided_command,
    required_command,
    transition,
)
from ciao.infrastructure.errors import InvalidRuntimeCallError
from ciao.visualization import (
    DisposedConnectionError,
    UIBindingConflictError,
    UIConnection,
    UIErrorInfo,
    UIErrorPhase,
)


@dataclass(frozen=True, slots=True)
class StartInput:
    values: tuple[int, ...]


@dataclass
class ViewContext(AutomatonContext):
    values: tuple[int, ...] = ()
    clicks: int = 0


class SampleView(ViewAutomaton[ViewContext]):
    ready = State(initial=True)

    @provided_command(external=True)
    def clicked(self) -> None:
        ...

    @provided_command(external=True)
    def initialized(self, payload: StartInput) -> None:
        ...

    @provided_command(external=True)
    def invalid_payload_shape(self, first: int, second: int) -> None:
        ...

    @required_command(external=True)
    def render_count(self, value: int) -> None:
        ...

    @action(emit=render_count)
    def register_click(self, ctx: ViewContext, emit: Emit) -> None:
        ctx.clicks += 1
        emit(ctx.clicks)

    @action
    def initialize(self, ctx: ViewContext, payload: StartInput) -> None:
        ctx.values = payload.values

    on_clicked = transition(
        source=ready,
        event=clicked,
        actions=(register_click,),
        target=ready,
    )
    on_initialized = transition(
        source=ready,
        event=initialized,
        actions=(initialize,),
        target=ready,
    )


class FakeSource:
    def __init__(self) -> None:
        self.callback: Callable[[], None] | None = None

    def fire(self) -> None:
        if self.callback is not None:
            self.callback()


class FakeUIConnection(UIConnection):
    def __init__(self, runtime: Runtime) -> None:
        super().__init__(runtime)
        self.processing_requests = 0
        self.errors: list[UIErrorInfo] = []
        self.platform_disposed = False

    def _install_event_callback(
        self,
        source: object,
        callback: Callable[[], None],
    ) -> Subscription:
        assert isinstance(source, FakeSource)
        if source.callback is not None:
            raise UIBindingConflictError("Источник уже занят")
        source.callback = callback

        def dispose() -> None:
            if source.callback is callback:
                source.callback = None

        return Subscription(dispose)

    def _request_processing(self) -> None:
        self.processing_requests += 1

    def _present_error(self, error: UIErrorInfo) -> None:
        self.errors.append(error)

    def _dispose_platform(self) -> None:
        self.platform_disposed = True


def _runtime() -> tuple[Runtime, AutomatonObject]:
    view = AutomatonObject("view", SampleView, ViewContext())
    return Runtime(Program(objects=(view,))), view


class UIConnectionTests(unittest.TestCase):
    def test_event_without_payload_sends_one_message(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        ui.bind_event(button, (view, SampleView.clicked))

        button.fire()
        self.assertEqual(1, runtime.pending_messages)
        self.assertEqual(1, ui.processing_requests)
        self.assertEqual([], ui.errors)

    def test_typed_payload_is_read_once_at_event_time(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        current = [1, 2]
        reads = 0

        def read_payload() -> StartInput:
            nonlocal reads
            reads += 1
            return StartInput(tuple(current))

        ui.bind_event(
            button,
            (view, SampleView.initialized),
            payload_source=FactoryPayloadSource(StartInput, read_payload),
        )
        current.append(3)
        button.fire()
        runtime.run()

        self.assertEqual(1, reads)
        self.assertEqual((1, 2, 3), runtime.snapshot(view).context.values)

    def test_payload_error_is_presented_without_runtime_message(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        ui.bind_event(
            button,
            (view, SampleView.initialized),
            payload_source=FactoryPayloadSource(StartInput, lambda: "wrong"),
        )

        button.fire()
        self.assertEqual(0, runtime.pending_messages)
        self.assertEqual(0, ui.processing_requests)
        self.assertEqual(UIErrorPhase.PAYLOAD_SOURCE, ui.errors[0].phase)
        self.assertEqual("view.initialized", ui.errors[0].endpoint)

    def test_payload_contract_is_checked_during_registration(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)

        with self.assertRaises(TypeError):
            ui.bind_event(
                FakeSource(),
                (view, SampleView.clicked),
                payload_source=FactoryPayloadSource(StartInput, lambda: StartInput(())),
            )
        with self.assertRaises(TypeError):
            ui.bind_event(FakeSource(), (view, SampleView.initialized))
        with self.assertRaises(TypeError):
            ui.bind_event(
                FakeSource(),
                (view, SampleView.initialized),
                payload_source=FactoryPayloadSource(int, lambda: 1),
            )
        with self.assertRaises(TypeError):
            ui.bind_event(FakeSource(), (view, SampleView.invalid_payload_shape))

    def test_bind_command_delegates_to_runtime_registry(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        rendered: list[int] = []

        def render(value: int) -> None:
            rendered.append(value)

        ui.bind_command((view, SampleView.render_count), render)
        ui.bind_event(button, (view, SampleView.clicked))
        button.fire()
        runtime.run()
        self.assertEqual([1], rendered)

    def test_invalid_endpoint_and_source_conflict_fail_before_event(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        ui.bind_event(button, (view, SampleView.clicked))
        with self.assertRaises(UIBindingConflictError):
            ui.bind_event(button, (view, SampleView.clicked))
        with self.assertRaises(InvalidRuntimeCallError):
            ui.bind_event(FakeSource(), (view, SampleView.render_count))

        foreign = AutomatonObject("foreign", SampleView, ViewContext())
        with self.assertRaises(InvalidRuntimeCallError):
            ui.bind_event(FakeSource(), (foreign, SampleView.clicked))

    def test_dispose_is_idempotent_and_makes_callbacks_noop(self) -> None:
        runtime, view = _runtime()
        ui = FakeUIConnection(runtime)
        button = FakeSource()
        ui.bind_event(button, (view, SampleView.clicked))

        ui.dispose()
        ui.dispose()
        button.fire()
        self.assertEqual(0, runtime.pending_messages)
        self.assertTrue(ui.platform_disposed)
        with self.assertRaises(DisposedConnectionError):
            ui.bind_event(FakeSource(), (view, SampleView.clicked))


if __name__ == "__main__":
    unittest.main()
