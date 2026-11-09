from ciao import Program, AutomatonObject, Connection

from .automatos import (
    CalculatorController,
    CalculatorContext,
    CalculatorView,
    CalculatorViewContext,
    OperatorService,
    OperatorContext,
)


def build_calculator_program():
    controller = AutomatonObject(
        name="calculator",
        automaton=CalculatorController,
        initial_context=CalculatorContext(),
    )

    operators = AutomatonObject(
        name="operators",
        automaton=OperatorService,
        initial_context=OperatorContext(),
    )

    view = AutomatonObject(
        name="view",
        automaton=CalculatorView,
        initial_context=CalculatorViewContext(),
    )

    program = Program(
        objects=(controller, operators, view),
        connections=(
            # Синхронные запросы
            Connection(
                required=(
                    controller,
                    CalculatorController.classify_token,
                ),
                provided=(operators, OperatorService.classify),
            ),
            Connection(
                required=(
                    controller,
                    CalculatorController.precedence,
                ),
                provided=(operators, OperatorService.precedence),
            ),
            Connection(
                required=(
                    controller,
                    CalculatorController.calculate,
                ),
                provided=(operators, OperatorService.calculate),
            ),

            # Асинхронные команды
            Connection(
                required=(controller, CalculatorController.draw),
                provided=(view, CalculatorView.draw),
            ),
            Connection(
                required=(view, CalculatorView.draw_completed),
                provided=(
                    controller,
                    CalculatorController.draw_completed,
                ),
            ),
        ),
    )

    return program, controller, operators, view