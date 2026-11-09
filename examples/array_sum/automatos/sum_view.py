"""View-автомат учебного примера пошагового суммирования массива."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import (
    AutomatonContext,
    Emit,
    State,
    ViewAutomaton,
    action,
    provided_command,
    required_command,
    transition,
)


@dataclass
class ViewContext(AutomatonContext):
    """Последний снимок, полученный headless-представлением."""

    values: tuple[int, ...] = ()
    index: int = 0
    total: int = 0
    tick_count: int = 0


class SumView(ViewAutomaton[ViewContext]):
    """Минимальный автомат представления без зависимости от Tkinter."""

    ready = State(initial=True)

    @provided_command
    def draw(
        self,
        values: tuple[int, ...],
        index: int,
        total: int,
        tick_count: int,
    ) -> None:
        ...

    @required_command
    def draw_completed(self) -> None:
        ...

    @action
    def apply_snapshot(
        self,
        ctx: ViewContext,
        values: tuple[int, ...],
        index: int,
        total: int,
        tick_count: int,
    ) -> None:
        ctx.values = values
        ctx.index = index
        ctx.total = total
        ctx.tick_count = tick_count

    @action(emit=draw_completed)
    def notify_draw_completed(self, ctx: ViewContext, emit: Emit) -> None:
        # Подтверждение возвращает Controller из publishing только после
        # фактической обработки команды draw объектом View.
        emit()

    on_draw = transition(
        source=ready,
        event=draw,
        actions=(apply_snapshot, notify_draw_completed),
        target=ready,
    )


__all__ = ["SumView", "ViewContext"]
