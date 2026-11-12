"""Минимальная интеграционная проверка ArraySum с настоящим Tk event loop."""

from __future__ import annotations

import tkinter as tk
import unittest
from threading import get_ident
from time import monotonic, sleep

from ciao import Runtime
from examples.array_sum.array_sum_tk import _bind_window
from examples.array_sum.interactive import (
    CalculationMode,
    InteractiveSumController,
    InteractiveSumView,
    StatusPresentation,
    build_interactive_sample,
)
from examples.array_sum.interactive.window import ArraySumWindow


class _RecordingWindow(ArraySumWindow):
    """Фиксирует поток реального external-handler без подмены Tk widgets."""

    def __init__(self, master: tk.Misc) -> None:
        self.handler_threads: list[int] = []
        super().__init__(master)

    def render_status(self, presentation: StatusPresentation) -> None:
        self.handler_threads.append(get_ident())
        super().render_status(presentation)


class ArraySumTkIntegrationTests(unittest.TestCase):
    def test_button_after_pump_and_window_handler_use_real_tk_loop(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display недоступен: {error}")

        root.withdraw()
        connection = None
        try:
            sample = build_interactive_sample()
            runtime = Runtime(sample.program)
            window = _RecordingWindow(root)
            connection = _bind_window(root, runtime, sample, window)

            window.values_entry.delete(0, tk.END)
            window.values_entry.insert(0, "2, 4, 6")
            window.mode_box.set(CalculationMode.RUN_TO_COMPLETION.value)
            window.init_button.invoke()

            deadline = monotonic() + 2.0
            while monotonic() < deadline:
                root.update()
                if (
                    runtime.pending_messages == 0
                    and runtime.snapshot(sample.controller).state
                    is InteractiveSumController.completed
                ):
                    break
                sleep(0.001)

            controller = runtime.snapshot(sample.controller)
            self.assertIs(controller.state, InteractiveSumController.completed)
            self.assertIs(
                runtime.snapshot(sample.view).state,
                InteractiveSumView.completed,
            )
            self.assertEqual((12, 3), (controller.total, controller.tick_count))
            self.assertTrue(window.handler_threads)
            self.assertEqual({get_ident()}, set(window.handler_threads))
        finally:
            if connection is not None:
                connection.dispose()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
