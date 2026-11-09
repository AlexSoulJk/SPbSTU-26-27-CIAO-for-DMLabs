
import pytest

from ciao import Runtime

from examples.calculator.program import build_calculator_program
from examples.calculator.automatos import CalculatorController
from examples.calculator.automatos import tokenize


# expression, expected_result, expected_rpn
TEST_CASES = [
    ("2 + 3", 5.0, ["2", "3", "+"]),
    ("10 - 4", 6.0, ["10", "4", "-"]),
    ("6 * 7", 42.0, ["6", "7", "*"]),
    ("9 / 2", 4.5, ["9", "2", "/"]),

    # Приоритет операций
    ("2 + 3 * 4", 14.0, ["2", "3", "4", "*", "+"]),
    ("2 * 3 + 4", 10.0, ["2", "3", "*", "4", "+"]),

    # Скобки
    ("(2 + 3) * 4", 20.0, ["2", "3", "+", "4", "*"]),
    ("3 + 4 * (2 - 1)", 7.0,
     ["3", "4", "2", "1", "-", "*", "+"]),

    # Дробные числа и отрицательный результат
    ("1.5 * 4", 6.0, ["1.5", "4", "*"]),
    ("7 - 10", -3.0, ["7", "10", "-"]),

    # Вложенные скобки
    ("((2 + 3) * 4)", 20.0,
     ["2", "3", "+", "4", "*"]),
]


def run_calculator(expression: str, max_ticks: int = 100):
    """Запускает полноценную CIAO-программу до состояния done."""

    program, controller, operators, view = (
        build_calculator_program()
    )

    runtime = Runtime(program)

    runtime.send(
        controller,
        CalculatorController.start,
        expression=expression,
    )
    runtime.run()

    for _ in range(max_ticks):
        snapshot = runtime.snapshot(controller)

        if snapshot.state == CalculatorController.done:
            break

        runtime.send(
            controller,
            CalculatorController.tick,
        )
        runtime.run()

    else:
        pytest.fail(
            f"Calculator не завершился за {max_ticks} ticks: "
            f"{expression!r}"
        )

    return (
        runtime.snapshot(controller),
        runtime.snapshot(view),
    )


@pytest.mark.parametrize(
    "expression, expected, expected_rpn",
    TEST_CASES,
)
def test_calculator(expression, expected, expected_rpn):
    controller, view = run_calculator(expression)

    ctx = controller.context
    view_ctx = view.context

    # Результат вычисления
    assert ctx.result == pytest.approx(expected)

    # Преобразование выражения в ОПН
    assert ctx.rpn == expected_rpn

    # Конечное состояние
    assert controller.state == CalculatorController.done

    # View получил итоговый результат
    assert view_ctx.result == pytest.approx(expected)
    assert view_ctx.phase == "done"

    # Проверяем обработку снимков
    assert view_ctx.update_count > 0


def test_all_tokens_processed():
    controller, _ = run_calculator("3 + 4 * (2 - 1)")
    ctx = controller.context

    assert ctx.token_index == len(ctx.tokens)
    assert ctx.eval_index == len(ctx.rpn)

    assert ctx.operators == []
    assert ctx.stack == [7.0]


def test_view_receives_every_snapshot():
    controller, view = run_calculator("2 + 3")

    ctx = controller.context
    view_ctx = view.context

    # Один снимок на токен преобразования,
    # один на токен ОПН и два финальных снимка.
    expected_updates = len(ctx.tokens) + len(ctx.rpn) + 2

    assert view_ctx.update_count == expected_updates


@pytest.mark.parametrize(
    "expression",
    ["2 ^ 3", "abc + 1", "2 @ 5", ""],
)
def test_invalid_tokenization(expression):
    with pytest.raises(ValueError):
        tokenize(expression)
