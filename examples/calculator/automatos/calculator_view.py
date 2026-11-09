
from dataclasses import dataclass

from ciao import (
    AutomatonContext,
    ViewAutomaton,
    State,
    Emit,
    action,
    transition,
    provided_command,
    required_command,
)


@dataclass
class CalculatorViewContext(AutomatonContext):
    expression: str = ""
    phase: str = "idle"
    current_token: str | None = None

    rpn: tuple[str, ...] = ()
    stack: tuple[float, ...] = ()

    result: float | None = None
    update_count: int = 0


class CalculatorView(ViewAutomaton[CalculatorViewContext]):
    """Получает снимки вычисления и подтверждает обработку."""

    ready = State(initial=True)

    @provided_command
    def draw(
        self,
        expression: str,
        phase: str,
        current_token: str | None,
        rpn: tuple[str, ...],
        stack: tuple[float, ...],
        result: float | None,
    ) -> None:
        ...

    @required_command
    def draw_completed(self) -> None:
        ...

    @action(text="Обновить данные представления")
    def apply_snapshot(
        self,
        ctx: CalculatorViewContext,
        expression: str,
        phase: str,
        current_token: str | None,
        rpn: tuple[str, ...],
        stack: tuple[float, ...],
        result: float | None,
    ) -> None:
        ctx.expression = expression
        ctx.phase = phase
        ctx.current_token = current_token

        ctx.rpn = rpn
        ctx.stack = stack
        ctx.result = result

        ctx.update_count += 1

    @action(emit=draw_completed)
    def acknowledge(
        self,
        ctx: CalculatorViewContext,
        emit: Emit,
    ) -> None:
        emit()

    on_draw = transition(
        source=ready,
        event=draw,
        actions=(apply_snapshot, acknowledge),
        target=ready,
    )
