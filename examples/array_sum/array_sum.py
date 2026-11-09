"""Headless-запуск суммы массива с трассой операций runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ciao import Runtime, TraceEvent

from .automatos import SumController, ViewContext
from .program import build_sample


@dataclass(frozen=True)
class CalculationResult:
    """Результат вычисления вместе со снимком View и полной трассой."""

    total: int
    view: ViewContext
    trace: tuple[TraceEvent, ...]


def _format_parameters(parameters: Mapping[str, Any]) -> str:
    return ", ".join(f"{name}={value!r}" for name, value in parameters.items())


def format_operation_trace(trace: Sequence[TraceEvent]) -> str:
    """Форматирует события как читаемый стек последовательных операций."""

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

        if event.error is not None:
            lines.append(f"    ошибка: {event.error}")

    return "\n".join(lines)


def run_calculation(values: Sequence[int]) -> CalculationResult:
    """Выполняет модель до ``done`` и сохраняет трассу всех операций."""

    sample = build_sample()
    runtime = Runtime(sample.program)

    runtime.send(sample.controller, SumController.start, values=values)
    runtime.run()

    while runtime.snapshot(sample.controller).state is not SumController.done:
        # tick остаётся пользовательской командой. Вызов run() затем доставляет
        # draw объекту View и подтверждение обратно по общей FIFO-очереди.
        runtime.send(sample.controller, SumController.tick)
        runtime.run()

    controller = runtime.snapshot(sample.controller)
    view = runtime.snapshot(sample.view)
    return CalculationResult(
        total=controller.total,
        view=view,
        trace=runtime.trace,
    )


def calculate_sum(values: Sequence[int]) -> tuple[int, ViewContext]:
    """Возвращает прежний компактный результат без обязательной трассы."""

    result = run_calculation(values)
    return result.total, result.view


def main() -> None:
    """Показывает результат и стек операций на трёх граничных сценариях."""

    cases = (
        ([], 0),
        ([7], 7),
        ([2, 4, 6], 12),
    )

    for values, expected in cases:
        result = run_calculation(values)
        assert result.total == expected
        assert result.view.total == expected

        print(f"Массив: {values}")
        print(
            f"Результат: total={result.total}, index={result.view.index}, "
            f"ticks={result.view.tick_count}"
        )
        print("Трасса операций:")
        print(format_operation_trace(result.trace))
        print()


if __name__ == "__main__":
    main()
