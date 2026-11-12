"""Тесты TkConnection на детерминированном fake event loop без дисплея."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

from ciao import (
    AutomatonContext,
    AutomatonObject,
    Emit,
    Program,
    Runtime,
    State,
    ViewAutomaton,
    action,
    provided_command,
    required_command,
    transition,
)
from ciao.visualization import BaseWindow, UIBindingConflictError, UIErrorInfo
from ciao.visualization.tkinter_connection import TkConnection


@dataclass
class ViewContext(AutomatonContext):
    count: int = 0


class TkView(ViewAutomaton[ViewContext]):
    ready = State(initial=True)

    @provided_command(external=True)
    def clicked(self) -> None:
        ...

    @required_command(external=True)
    def render(self, value: int) -> None:
        ...

    @action(emit=render)
    def increment(self, ctx: ViewContext, emit: Emit) -> None:
        ctx.count += 1
        emit(ctx.count)

    on_clicked = transition(
        source=ready,
        event=clicked,
        actions=(increment,),
        target=ready,
    )


class FakeMaster:
    def __init__(self) -> None:
        self._next_id = 0
        self._sequence = 0
        self.callbacks: dict[str, tuple[int, int, Callable[[], None]]] = {}
        self.bindings: dict[tuple[str, str], Callable[[object], None]] = {}
        self.reported: list[tuple[type[BaseException], BaseException]] = []

    def after(self, delay: int, callback: Callable[[], None]) -> str:
        self._next_id += 1
        self._sequence += 1
        identifier = f"after-{self._next_id}"
        self.callbacks[identifier] = (delay, self._sequence, callback)
        return identifier

    def after_cancel(self, identifier: str) -> None:
        self.callbacks.pop(identifier, None)

    def bind(
        self,
        sequence: str,
        callback: Callable[[object], None],
        add: str | None = None,
    ) -> str:
        identifier = f"bind-{len(self.bindings) + 1}"
        self.bindings[(sequence, identifier)] = callback
        return identifier

    def unbind(self, sequence: str, identifier: str) -> None:
        self.bindings.pop((sequence, identifier), None)

    def report_callback_exception(
        self,
        error_type: type[BaseException],
        error: BaseException,
        traceback: object,
    ) -> None:
        self.reported.append((error_type, error))

    def run_next(self) -> None:
        identifier, (_, _, callback) = min(
            self.callbacks.items(),
            key=lambda item: (item[1][0], item[1][1]),
        )
        del self.callbacks[identifier]
        callback()


class FakeButton:
    def __init__(self, command: object = "") -> None:
        self.command = command
        self.exists = True
        self.bindings: dict[tuple[str, str], Callable[[object], None]] = {}

    def cget(self, name: str) -> object:
        assert name == "command"
        return self.command

    def configure(self, *, command: object) -> None:
        self.command = command

    def bind(
        self,
        sequence: str,
        callback: Callable[[object], None],
        add: str | None = None,
    ) -> str:
        identifier = f"bind-{len(self.bindings) + 1}"
        self.bindings[(sequence, identifier)] = callback
        return identifier

    def unbind(self, sequence: str, identifier: str) -> None:
        self.bindings.pop((sequence, identifier), None)

    def winfo_exists(self) -> bool:
        return self.exists

    def invoke(self) -> None:
        assert callable(self.command)
        self.command()

    def destroy(self) -> None:
        self.exists = False
        event = SimpleNamespace(widget=self)
        for (sequence, _), callback in tuple(self.bindings.items()):
            if sequence == "<Destroy>":
                callback(event)
        self.command = ""


class FakeWindow(BaseWindow):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.errors: list[UIErrorInfo] = []

    def show_error(self, error: UIErrorInfo) -> None:
        if self.fail:
            raise RuntimeError("presenter failed")
        self.errors.append(error)


def _runtime() -> tuple[Runtime, AutomatonObject]:
    view = AutomatonObject("view", TkView, ViewContext())
    return Runtime(Program(objects=(view,))), view


class TkConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tk_button_patch = patch(
            "ciao.visualization.tkinter_connection.tk.Button",
            FakeButton,
        )
        self.ttk_button_patch = patch(
            "ciao.visualization.tkinter_connection.ttk.Button",
            FakeButton,
        )
        self.tk_button_patch.start()
        self.ttk_button_patch.start()

    def tearDown(self) -> None:
        self.ttk_button_patch.stop()
        self.tk_button_patch.stop()

    def test_button_event_uses_one_runtime_step_per_after_callback(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        window = FakeWindow()
        button = FakeButton()
        rendered: list[int] = []

        def render(value: int) -> None:
            rendered.append(value)

        connection = TkConnection(master, runtime, window)
        connection.bind_command((view, TkView.render), render)
        connection.bind_event(button, (view, TkView.clicked))
        button.invoke()

        self.assertEqual(1, runtime.pending_messages)
        master.run_next()
        self.assertEqual([], rendered)
        self.assertEqual(1, runtime.pending_messages)
        master.run_next()
        self.assertEqual([1], rendered)
        self.assertEqual(0, runtime.pending_messages)

    def test_existing_command_and_second_binding_are_rejected(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        connection = TkConnection(master, runtime, FakeWindow())
        with self.assertRaises(UIBindingConflictError):
            connection.bind_event(
                FakeButton(command=lambda: None),
                (view, TkView.clicked),
            )

        button = FakeButton()
        connection.bind_event(button, (view, TkView.clicked))
        with self.assertRaises(UIBindingConflictError):
            connection.bind_event(button, (view, TkView.clicked))

    def test_external_handler_error_is_presented_after_failed_step(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        window = FakeWindow()
        button = FakeButton()

        def fail(value: int) -> None:
            raise ValueError("render failed")

        connection = TkConnection(master, runtime, window)
        connection.bind_command((view, TkView.render), fail)
        connection.bind_event(button, (view, TkView.clicked))
        button.invoke()
        master.run_next()
        master.run_next()

        self.assertEqual(1, len(window.errors))
        self.assertEqual("external_handler", window.errors[0].phase.value)
        self.assertIs(window.errors[0], connection.last_error)
        self.assertEqual(0, runtime.pending_messages)

    def test_presenter_error_is_reported_once_to_tk(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        button = FakeButton()

        def fail(value: int) -> None:
            raise ValueError("render failed")

        connection = TkConnection(master, runtime, FakeWindow(fail=True))
        connection.bind_command((view, TkView.render), fail)
        connection.bind_event(button, (view, TkView.clicked))
        button.invoke()
        master.run_next()
        master.run_next()
        self.assertEqual(1, len(master.reported))

    def test_dispose_clears_owned_command_and_releases_affinity(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        button = FakeButton()
        connection = TkConnection(master, runtime, FakeWindow())
        connection.bind_event(button, (view, TkView.clicked))

        connection.dispose()
        self.assertEqual("", button.command)
        self.assertEqual({}, master.callbacks)

        # После освобождения lease тот же Runtime можно присоединить заново.
        replacement = TkConnection(master, runtime, FakeWindow())
        replacement.dispose()

    def test_destroyed_button_only_removes_its_binding(self) -> None:
        runtime, view = _runtime()
        master = FakeMaster()
        first = FakeButton()
        second = FakeButton()
        connection = TkConnection(master, runtime, FakeWindow())
        connection.bind_event(first, (view, TkView.clicked))
        connection.bind_event(second, (view, TkView.clicked))

        first.destroy()
        self.assertFalse(callable(first.command))
        self.assertTrue(callable(second.command))


if __name__ == "__main__":
    unittest.main()
