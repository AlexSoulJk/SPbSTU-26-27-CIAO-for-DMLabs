"""Сквозные acceptance-тесты интерактивного варианта ArraySum."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ciao import Runtime
from examples.array_sum.interactive import (
    CalculationMode,
    ControlsPresentation,
    DataPresentation,
    InteractiveSumController,
    InteractiveSumView,
    SnapshotPhase,
    StartInput,
    StatusPresentation,
    build_interactive_sample,
)
from ciao.visualization.drawio import export_program_drawio


class _Presentations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def render_data(self, presentation: DataPresentation) -> None:
        self.calls.append(("render_data", presentation))

    def render_controls(self, presentation: ControlsPresentation) -> None:
        self.calls.append(("render_controls", presentation))

    def render_status(self, presentation: StatusPresentation) -> None:
        self.calls.append(("render_status", presentation))


def _runtime_with_presentations():
    sample = build_interactive_sample()
    runtime = Runtime(sample.program)
    presentations = _Presentations()
    runtime.bind_external(
        (sample.view, InteractiveSumView.render_data), presentations.render_data,
    )
    runtime.bind_external(
        (sample.view, InteractiveSumView.render_controls),
        presentations.render_controls,
    )
    runtime.bind_external(
        (sample.view, InteractiveSumView.render_status), presentations.render_status,
    )
    return sample, runtime, presentations


class InteractiveArraySumTests(unittest.TestCase):
    def test_step_mode_processes_exactly_one_element_per_click(self) -> None:
        sample, runtime, presentations = _runtime_with_presentations()
        runtime.send(
            sample.view,
            InteractiveSumView.init_clicked,
            StartInput((2, 4, 6), CalculationMode.STEP_BY_STEP),
        )
        runtime.run()
        self.assertIs(
            runtime.snapshot(sample.controller).state,
            InteractiveSumController.running_step,
        )
        self.assertIs(runtime.snapshot(sample.view).state, InteractiveSumView.step_ready)

        for expected_index in (1, 2, 3):
            runtime.send(sample.view, InteractiveSumView.next_clicked)
            runtime.run()
            self.assertEqual(expected_index, runtime.snapshot(sample.controller).index)

        controller = runtime.snapshot(sample.controller)
        view = runtime.snapshot(sample.view)
        self.assertIs(controller.state, InteractiveSumController.completed)
        self.assertIs(view.state, InteractiveSumView.completed)
        self.assertEqual((12, 3, 3), (controller.total, controller.index, controller.tick_count))
        self.assertEqual(3, sum(event.operation == "tick" for event in runtime.trace))

        snapshots = [
            event.parameters["snapshot"]
            for event in runtime.trace
            if event.operation == "draw"
        ]
        self.assertEqual(
            [SnapshotPhase.RUNNING, SnapshotPhase.RUNNING, SnapshotPhase.COMPLETED],
            [snapshot.phase for snapshot in snapshots],
        )
        self.assertEqual(
            ["render_data", "render_controls", "render_status"],
            [name for name, _ in presentations.calls[-3:]],
        )
        operations = [event.operation for event in runtime.trace]
        last_draw = len(operations) - 1 - operations[::-1].index("draw")
        self.assertEqual(
            ["draw", "render_data", "render_controls", "render_status", "draw_completed"],
            operations[last_draw:last_draw + 5],
        )

    def test_automatic_mode_uses_self_connection_and_only_final_snapshot(self) -> None:
        sample, runtime, presentations = _runtime_with_presentations()
        runtime.send(
            sample.view,
            InteractiveSumView.init_clicked,
            StartInput((2, 4, 6), CalculationMode.RUN_TO_COMPLETION),
        )
        runtime.run()

        controller = runtime.snapshot(sample.controller)
        self.assertIs(controller.state, InteractiveSumController.completed)
        self.assertIs(runtime.snapshot(sample.view).state, InteractiveSumView.completed)
        self.assertEqual((12, 3, 3), (controller.total, controller.index, controller.tick_count))
        self.assertEqual(3, sum(event.operation == "tick" for event in runtime.trace))
        self.assertEqual(1, sum(event.operation == "draw" for event in runtime.trace))
        # Одна публикация показывает исходный ввод, вторая — единственный итог.
        self.assertEqual(2, sum(name == "render_data" for name, _ in presentations.calls))

    def test_empty_array_completes_without_tick_in_both_modes(self) -> None:
        for mode in CalculationMode:
            with self.subTest(mode=mode):
                sample, runtime, _ = _runtime_with_presentations()
                runtime.send(
                    sample.view,
                    InteractiveSumView.init_clicked,
                    StartInput((), mode),
                )
                runtime.run()
                controller = runtime.snapshot(sample.controller)
                self.assertIs(controller.state, InteractiveSumController.completed)
                self.assertIs(runtime.snapshot(sample.view).state, InteractiveSumView.completed)
                self.assertEqual(
                    (0, 0, 0),
                    (controller.total, controller.index, controller.tick_count),
                )
                self.assertFalse(any(event.operation == "tick" for event in runtime.trace))

    def test_reset_reinitialization_and_finish_follow_view_commands(self) -> None:
        sample, runtime, _ = _runtime_with_presentations()
        runtime.send(
            sample.view,
            InteractiveSumView.init_clicked,
            StartInput((5,), CalculationMode.RUN_TO_COMPLETION),
        )
        runtime.run()
        runtime.send(sample.view, InteractiveSumView.reset_clicked)
        runtime.run()
        self.assertIs(runtime.snapshot(sample.controller).state, InteractiveSumController.idle)
        self.assertIs(runtime.snapshot(sample.view).state, InteractiveSumView.idle)

        runtime.send(
            sample.view,
            InteractiveSumView.init_clicked,
            StartInput((7,), CalculationMode.STEP_BY_STEP),
        )
        runtime.run()
        runtime.send(sample.view, InteractiveSumView.next_clicked)
        runtime.run()
        runtime.send(sample.view, InteractiveSumView.finish_clicked)
        runtime.run()
        self.assertIs(runtime.snapshot(sample.controller).state, InteractiveSumController.done)
        self.assertIs(runtime.snapshot(sample.view).state, InteractiveSumView.final)
        self.assertEqual(
            ["finish_clicked", "finish", "render_controls", "render_status"],
            [event.operation for event in runtime.trace[-4:]],
        )

    def test_interactive_program_has_deterministic_drawio_export(self) -> None:
        sample = build_interactive_sample()
        with TemporaryDirectory() as directory:
            first = Path(directory) / "interactive-first.drawio"
            second = Path(directory) / "interactive-second.drawio"
            export_program_drawio(sample.program, first)
            export_program_drawio(sample.program, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertGreater(first.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
