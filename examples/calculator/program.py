"""Сборка программы учебного пошагового калькулятора."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program

from .automatos import (
    CalculatorContext,
    CalculatorController,
    CalculatorView,
    CalculatorViewContext,
    OperatorContext,
    OperatorService,
)


@dataclass(frozen=True)
class Sample:
    program: Program
    controller: AutomatonObject
    operators: AutomatonObject
    view: AutomatonObject


def build_sample() -> Sample:
    """Создаёт Controller, OperatorService, View и все их соединения."""

    controller = AutomatonObject(
        "calculator",
        CalculatorController,
        CalculatorContext(),
    )
    operators = AutomatonObject(
        "operators",
        OperatorService,
        OperatorContext(),
    )
    view = AutomatonObject("view", CalculatorView, CalculatorViewContext())
    program = Program(
        objects=(controller, operators, view),
        connections=(
            Connection(
                (controller, CalculatorController.classify_token),
                (operators, OperatorService.classify),
            ),
            Connection(
                (controller, CalculatorController.precedence),
                (operators, OperatorService.precedence),
            ),
            Connection(
                (controller, CalculatorController.calculate),
                (operators, OperatorService.calculate),
            ),
            Connection(
                (view, CalculatorView.start),
                (controller, CalculatorController.start),
            ),
            Connection(
                (view, CalculatorView.tick),
                (controller, CalculatorController.tick),
            ),
            Connection(
                (view, CalculatorView.reset),
                (controller, CalculatorController.reset),
            ),
            Connection(
                (view, CalculatorView.finish),
                (controller, CalculatorController.finish),
            ),
            Connection(
                (controller, CalculatorController.draw),
                (view, CalculatorView.draw),
            ),
            Connection(
                (view, CalculatorView.draw_completed),
                (controller, CalculatorController.draw_completed),
            ),
        ),
    )
    return Sample(program, controller, operators, view)


__all__ = ["Sample", "build_sample"]
