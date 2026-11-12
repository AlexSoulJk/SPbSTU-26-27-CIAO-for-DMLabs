"""Headless-запуск той же программы ArraySum без Window и Tkinter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ciao import Runtime, TraceEvent

from . import CalculationMode, StartInput, SumController, SumView, ViewContext
from .program import build_sample


@dataclass(frozen=True)
class CalculationResult:
    total: int
    view: ViewContext
    trace: tuple[TraceEvent, ...]


def _format_parameters(parameters: Mapping[str, Any]) -> str:
    return ", ".join(f"{name}={value!r}" for name, value in parameters.items())


def format_operation_trace(trace: Sequence[TraceEvent]) -> str:
    """Форматирует последовательные события Runtime."""

    lines: list[str] = []
    for event in trace:
        parameters = _format_parameters(event.parameters)
        lines.append(
            f"#{event.step_number:02d} "
            f"{event.object_name}.{event.operation}({parameters})"
        )
        transition = event.transition or "без перехода"
        lines.append(
            f"    {event.source_state} --{transition}--> "
            f"{event.target_state} [{event.status.value}]"
        )
        for emitted in event.emitted:
            emitted_parameters = _format_parameters(emitted.parameters)
            lines.append(
                f"    emit -> {emitted.target}.{emitted.operation}"
                f"({emitted_parameters})"
            )
    return "\n".join(lines)


def run_calculation(
    values: Sequence[int],
    mode: CalculationMode = CalculationMode.RUN_TO_COMPLETION,
) -> CalculationResult:
    """Выполняет ту же View-команду Init напрямую, без UI-инфраструктуры."""

    sample = build_sample()
    runtime = Runtime(sample.program)
    runtime.send(
        sample.view,
        SumView.init_clicked,
        StartInput(tuple(values), mode),
    )
    runtime.run()

    while runtime.snapshot(sample.controller).state is SumController.running_step:
        runtime.send(sample.view, SumView.next_clicked)
        runtime.run()

    controller = runtime.snapshot(sample.controller)
    return CalculationResult(
        total=controller.total,
        view=runtime.snapshot(sample.view).context,
        trace=runtime.trace,
    )


def calculate_sum(
    values: Sequence[int],
    mode: CalculationMode = CalculationMode.RUN_TO_COMPLETION,
) -> tuple[int, ViewContext]:
    """Возвращает компактный результат headless-выполнения."""

    result = run_calculation(values, mode)
    return result.total, result.view


def main() -> None:
    for values in ((), (7,), (2, 4, 6)):
        result = run_calculation(values)
        print(f"Массив: {list(values)}; сумма: {result.total}")
        print(format_operation_trace(result.trace))
        print()


if __name__ == "__main__":
    main()
