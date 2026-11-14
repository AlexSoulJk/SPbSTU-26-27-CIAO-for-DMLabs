"""Headless-запуск той же View-команды калькулятора без Tkinter."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import Runtime, TraceEvent

from . import (
    CalculatorContext,
    CalculatorController,
    CalculatorView,
    CalculatorViewContext,
    StartInput,
    build_sample,
)


@dataclass(frozen=True)
class CalculationResult:
    result: float
    controller: CalculatorContext
    view: CalculatorViewContext
    trace: tuple[TraceEvent, ...]


def run_calculation(
    expression: str,
    *,
    max_steps: int = 100,
) -> CalculationResult:
    """Выполняет UI-сценарий до результата и явного Finish."""

    sample = build_sample()
    runtime = Runtime(sample.program)
    runtime.send(
        sample.view,
        CalculatorView.start_clicked,
        StartInput(expression),
    )
    runtime.run()

    for _ in range(max_steps):
        if runtime.snapshot(sample.controller).state is CalculatorController.completed:
            break
        runtime.send(sample.view, CalculatorView.next_clicked)
        runtime.run()
    else:
        raise RuntimeError(
            f"Калькулятор не завершился за {max_steps} шагов: {expression!r}"
        )

    runtime.send(sample.view, CalculatorView.finish_clicked)
    runtime.run()
    controller = runtime.snapshot(sample.controller)
    if controller.result is None:
        raise RuntimeError("Калькулятор завершился без результата")
    return CalculationResult(
        result=controller.result,
        controller=controller.context,
        view=runtime.snapshot(sample.view).context,
        trace=runtime.trace,
    )


def calculate(expression: str) -> float:
    return run_calculation(expression).result


def main() -> None:
    expression = "3 + 4 * (2 - 1)"
    result = run_calculation(expression)
    print(f"{expression} = {result.result}")
    for event in result.trace:
        print(
            f"#{event.step_number:02d} {event.object_name}."
            f"{event.operation} -> {event.target_state}"
        )


if __name__ == "__main__":
    main()
