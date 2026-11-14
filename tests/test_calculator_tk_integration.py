"""Интеграция Calculator с настоящим Tk event loop."""

from __future__ import annotations

import tkinter as tk
import unittest
from time import monotonic, sleep

from ciao import Runtime
from examples.calculator import (
    CalculationPhase,
    CalculatorController,
    CalculatorView,
    DataPresentation,
    build_sample,
)
from examples.calculator.interactive_run import _bind_window
from examples.calculator.ui import CalculatorWindow
from examples.calculator.ui.calculator_window import INITIAL_EXPRESSION


class _RecordingWindow(CalculatorWindow):
    def __init__(self, master: tk.Misc) -> None:
        self.data_presentations: list[DataPresentation] = []
        super().__init__(master)

    def render_data(self, presentation: DataPresentation) -> None:
        self.data_presentations.append(presentation)
        super().render_data(presentation)


class CalculatorTkIntegrationTests(unittest.TestCase):
    def _pump(self, root: tk.Tk, runtime: Runtime) -> None:
        deadline = monotonic() + 2.0
        while monotonic() < deadline:
            root.update()
            if runtime.pending_messages == 0:
                root.update()
                return
            sleep(0.001)
        self.fail("Tk-pump не обработал очередь Calculator за 2 секунды")

    def test_buttons_drive_view_and_render_typed_presentations(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display недоступен: {error}")

        root.withdraw()
        connection = None
        try:
            sample = build_sample()
            runtime = Runtime(sample.program)
            window = _RecordingWindow(root)
            self.assertEqual(INITIAL_EXPRESSION, window.data_presentations[0].expression)
            connection = _bind_window(root, runtime, sample, window)

            window.expression_entry.delete(0, tk.END)
            window.expression_entry.insert(0, "2 + 3")
            window.start_button.invoke()
            self._pump(root, runtime)

            for _ in range(10):
                if (
                    runtime.snapshot(sample.controller).state
                    is CalculatorController.completed
                ):
                    break
                window.next_button.invoke()
                self._pump(root, runtime)
            else:
                self.fail("Calculator не завершился через UI за 10 шагов")

            self.assertEqual(5.0, runtime.snapshot(sample.controller).result)
            self.assertIs(
                runtime.snapshot(sample.view).state,
                CalculatorView.completed,
            )
            self.assertEqual(5.0, window.data_presentations[-1].result)

            window.reset_button.invoke()
            self._pump(root, runtime)
            self.assertIs(
                runtime.snapshot(sample.controller).state,
                CalculatorController.idle,
            )
            self.assertEqual("2 + 3", window.data_presentations[-1].expression)
            self.assertIs(
                window.data_presentations[-1].phase,
                CalculationPhase.IDLE,
            )
        finally:
            if connection is not None:
                connection.dispose()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
