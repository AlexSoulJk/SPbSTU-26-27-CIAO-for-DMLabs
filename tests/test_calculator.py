"""Сквозные тесты Calculator через публичные команды View."""

from __future__ import annotations

import pytest

from ciao import ActionExecutionError, Runtime
from examples.calculator import (
    CalculationPhase,
    CalculatorController,
    CalculatorView,
    ControlsPresentation,
    DataPresentation,
    StartInput,
    StatusPresentation,
    build_sample,
    tokenize,
)
from examples.calculator.headless_run import calculate


TEST_CASES = [
    ("2 + 3", 5.0, ["2", "3", "+"]),
    ("10 - 4", 6.0, ["10", "4", "-"]),
    ("6 * 7", 42.0, ["6", "7", "*"]),
    ("9 / 2", 4.5, ["9", "2", "/"]),
    ("2 + 3 * 4", 14.0, ["2", "3", "4", "*", "+"]),
    ("2 * 3 + 4", 10.0, ["2", "3", "*", "4", "+"]),
    ("(2 + 3) * 4", 20.0, ["2", "3", "+", "4", "*"]),
    (
        "3 + 4 * (2 - 1)",
        7.0,
        ["3", "4", "2", "1", "-", "*", "+"],
    ),
    ("1.5 * 4", 6.0, ["1.5", "4", "*"]),
    ("7 - 10", -3.0, ["7", "10", "-"]),
    ("((2 + 3) * 4)", 20.0, ["2", "3", "+", "4", "*"]),
]


class _Presentations:
    def __init__(self) -> None:
        self.data: list[DataPresentation] = []
        self.controls: list[ControlsPresentation] = []
        self.statuses: list[StatusPresentation] = []

    def render_data(self, presentation: DataPresentation) -> None:
        self.data.append(presentation)

    def render_controls(self, presentation: ControlsPresentation) -> None:
        self.controls.append(presentation)

    def render_status(self, presentation: StatusPresentation) -> None:
        self.statuses.append(presentation)


def _run_to_completed(expression: str, max_steps: int = 100):
    sample = build_sample()
    runtime = Runtime(sample.program)
    presentations = _Presentations()
    runtime.bind_external(
        (sample.view, CalculatorView.render_data),
        presentations.render_data,
    )
    runtime.bind_external(
        (sample.view, CalculatorView.render_controls),
        presentations.render_controls,
    )
    runtime.bind_external(
        (sample.view, CalculatorView.render_status),
        presentations.render_status,
    )
    runtime.send(
        sample.view,
        CalculatorView.start_clicked,
        StartInput(expression),
    )
    runtime.run()

    for _ in range(max_steps):
        if runtime.snapshot(sample.controller).state is CalculatorController.completed:
            break
        assert runtime.snapshot(sample.view).state is CalculatorView.running
        runtime.send(sample.view, CalculatorView.next_clicked)
        runtime.run()
    else:
        pytest.fail(
            f"Calculator не завершился за {max_steps} шагов: {expression!r}"
        )
    return sample, runtime, presentations


@pytest.mark.parametrize("expression, expected, expected_rpn", TEST_CASES)
def test_calculator(expression, expected, expected_rpn):
    sample, runtime, presentations = _run_to_completed(expression)
    controller = runtime.snapshot(sample.controller)
    view = runtime.snapshot(sample.view)

    assert controller.result == pytest.approx(expected)
    assert controller.rpn == expected_rpn
    assert controller.state is CalculatorController.completed
    assert view.state is CalculatorView.completed
    assert view.result == pytest.approx(expected)
    assert view.phase is CalculationPhase.COMPLETED
    assert presentations.data[-1].result == pytest.approx(expected)
    assert presentations.controls[-1] == ControlsPresentation(
        False,
        False,
        False,
        False,
        True,
        True,
    )

    runtime.send(sample.view, CalculatorView.finish_clicked)
    runtime.run()
    assert runtime.snapshot(sample.controller).state is CalculatorController.done
    assert runtime.snapshot(sample.view).state is CalculatorView.final


def test_all_tokens_and_snapshots_are_processed() -> None:
    sample, runtime, _ = _run_to_completed("3 + 4 * (2 - 1)")
    controller = runtime.snapshot(sample.controller)
    view = runtime.snapshot(sample.view)
    assert controller.token_index == len(controller.tokens)
    assert controller.eval_index == len(controller.rpn)
    assert controller.operators == []
    assert controller.stack == [7.0]
    assert view.update_count == len(controller.tokens) + len(controller.rpn) + 2


def test_reset_preserves_expression_and_clears_progress() -> None:
    sample, runtime, presentations = _run_to_completed("2 + 3")
    runtime.send(sample.view, CalculatorView.reset_clicked)
    runtime.run()

    controller = runtime.snapshot(sample.controller)
    view = runtime.snapshot(sample.view)
    assert controller.state is CalculatorController.idle
    assert view.state is CalculatorView.idle
    assert controller.expression == "2 + 3"
    assert view.expression == "2 + 3"
    assert controller.rpn == []
    assert controller.stack == []
    assert controller.result is None
    assert presentations.data[-1] == DataPresentation(
        "2 + 3",
        CalculationPhase.IDLE,
        None,
        (),
        (),
        None,
    )

    runtime.send(
        sample.view,
        CalculatorView.start_clicked,
        StartInput("6 * 7"),
    )
    runtime.run()
    assert runtime.snapshot(sample.controller).expression == "6 * 7"


def test_headless_entry_point_uses_the_same_view_scenario() -> None:
    assert calculate("2 + 3 * 4") == pytest.approx(14.0)


def test_invalid_view_input_does_not_desynchronize_automata() -> None:
    sample = build_sample()
    runtime = Runtime(sample.program)
    runtime.send(
        sample.view,
        CalculatorView.start_clicked,
        StartInput("2 ^ 3"),
    )
    with pytest.raises(ActionExecutionError, match="Недопустимый символ"):
        runtime.run()
    assert runtime.snapshot(sample.view).state is CalculatorView.idle
    assert runtime.snapshot(sample.controller).state is CalculatorController.idle


@pytest.mark.parametrize("expression", ["2 ^ 3", "abc + 1", "2 @ 5", ""])
def test_invalid_tokenization(expression):
    with pytest.raises(ValueError):
        tokenize(expression)
