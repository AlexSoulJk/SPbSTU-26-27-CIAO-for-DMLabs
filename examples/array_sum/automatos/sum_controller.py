"""Controller учебного примера пошагового суммирования массива."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ciao import (
    AutomatonContext,
    ControllerAutomaton,
    Emit,
    State,
    action,
    guard,
    provided_command,
    required_command,
    transition,
)


@dataclass
class SumContext(AutomatonContext):
    """Локальные данные одного исполняемого экземпляра контроллера."""

    values: list[int] = field(default_factory=list)
    index: int = 0
    total: int = 0
    tick_count: int = 0


class SumController(ControllerAutomaton[SumContext]):
    """Пошагово вычисляет сумму и публикует снимки для представления."""

    idle = State(initial=True)
    running = State()
    publishing = State()
    done = State(final=True)

    @provided_command(external=True)
    def start(self, values: Sequence[int]) -> None:
        ...

    @provided_command
    def tick(self) -> None:
        ...

    @provided_command
    def reset(self) -> None:
        ...

    @provided_command
    def draw_completed(self) -> None:
        """Подтверждает обработку опубликованного снимка представлением."""

        ...

    @required_command
    def draw(
        self,
        values: tuple[int, ...],
        index: int,
        total: int,
        tick_count: int,
    ) -> None:
        ...

    @guard(text="\nindex < len(values)")
    def has_current(self, ctx: SumContext) -> bool:
        """Проверяет, что текущий индекс всё ещё указывает на элемент."""

        return not self._is_out_of_bounds(ctx)

    @staticmethod
    def _is_out_of_bounds(ctx: SumContext) -> bool:
        """Задаёт единственное бинарное условие развилки в ``running``."""

        return ctx.index >= len(ctx.values)

    @action
    def initialize(
        self,
        ctx: SumContext,
        values: Sequence[int],
    ) -> None:
        ctx.values = list(values)
        ctx.index = 0
        ctx.total = 0
        ctx.tick_count = 0

    @action(text="\ntotal += values[index];\nindex++")
    def add_current(self, ctx: SumContext) -> None:
        # Guard выбранного перехода гарантирует допустимость индекса.
        ctx.total += ctx.values[ctx.index]
        ctx.index += 1

    @action(text="\ntick_count++")
    def count_tick(self, ctx: SumContext) -> None:
        ctx.tick_count += 1

    @action(emit=draw, text="\nпубликует снимок для представления")
    def publish_draw(self, ctx: SumContext, emit: Emit) -> None:
        # Capability привязан к draw, а runtime помещает команду в FIFO
        # только после успешного выполнения всего перехода.
        emit(
            values=tuple(ctx.values),
            index=ctx.index,
            total=ctx.total,
            tick_count=ctx.tick_count,
        )

    @action(text="clear all context values")
    def clear(self, ctx: SumContext) -> None:
        ctx.values.clear()
        ctx.index = 0
        ctx.total = 0
        ctx.tick_count = 0

    on_start = transition(
        source=idle,
        event=start,
        actions=(initialize,),
        target=running,
    )

    on_tick_with_current_element = transition(
        source=running,
        event=tick,
        guard=has_current,
        actions=(add_current, count_tick, publish_draw),
        target=publishing,
    )

    on_tick_when_complete = transition(
        source=running,
        event=tick,
        otherwise=True,
        actions=(),
        target=done,
    )

    on_draw_completed = transition(
        source=publishing,
        event=draw_completed,
        target=running,
    )

    on_reset = transition(
        source=done,
        event=reset,
        actions=(clear,),
        target=idle,
    )


__all__ = ["SumContext", "SumController"]
