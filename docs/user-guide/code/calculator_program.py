"""Снимок сборки пошагового Calculator для главы 8."""

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program
from examples.calculator.automatos import (
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
    controller = AutomatonObject(
        "calculator", CalculatorController, CalculatorContext()
    )
    operators = AutomatonObject("operators", OperatorService, OperatorContext())
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
                (controller, CalculatorController.draw),
                (view, CalculatorView.draw),
            ),
        ),
    )
    return Sample(program, controller, operators, view)

