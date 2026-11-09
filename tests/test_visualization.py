"""Безэкранные тесты адаптера событий визуализации."""

from __future__ import annotations

import unittest
from typing import Any

from ciao import Runtime, TraceEvent
from ciao.visualization import TkTraceAdapter
from examples.array_sum.automatos import SumController
from examples.array_sum.program import build_sample


class FakeTkRoot:
    """Минимальная замена ``tk.Misc`` для проверки планирования через after."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, Any, tuple[Any, ...]]] = []

    def after(self, delay: int, callback: Any, *args: Any) -> None:
        self.calls.append((delay, callback, args))
        callback(*args)


class VisualizationTests(unittest.TestCase):
    def test_trace_adapter_schedules_handler_via_after(self) -> None:
        sample = build_sample()
        runtime = Runtime(sample.program)
        root = FakeTkRoot()
        received: list[TraceEvent] = []
        TkTraceAdapter(root, runtime, received.append)  # type: ignore[arg-type]

        runtime.send(sample.controller, SumController.start, values=[])
        runtime.step()

        self.assertEqual(1, len(root.calls))
        self.assertEqual(0, root.calls[0][0])
        self.assertEqual(1, len(received))
        self.assertEqual("start", received[0].operation)
