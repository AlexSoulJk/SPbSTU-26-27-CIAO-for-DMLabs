"""Цельный headless-пример согласованного публичного API CIAO.

Название начинается с ``test_`` по запросу автора проекта, но файл является
запускаемым примером, а не pytest-тестом.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ciao import (
    AutomatonContext,
    AutomatonObject,
    Connection,
    ControllerAutomaton,
    Emit,
    Program,
    Runtime,
    State,
    ViewAutomaton,
    action,
    guard,
    provided_command,
    required_command,
    transition,
)

__test__ = False


@dataclass
class SumContext(AutomatonContext):
    """Локальные данные одного исполняемого экземпляра контроллера."""

    values: list[int] = field(default_factory=list)
    index: int = 0
    total: int = 0
    tick_count: int = 0


class SumController(ControllerAutomaton[SumContext]):
    """Пошагово вычисляет сумму и публикует снимки для представления."""

    # Управляющие состояния принадлежат описанию автоматного класса.
    idle = State(initial=True)
    running = State()
    publishing = State()
    done = State(final=True)

    # PROVIDED-команды являются событиями переходов.
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
        """Подтверждает, что представление обработало опубликованный снимок."""

        ...

    # REQUIRED-команда будет связана с PROVIDED-командой объекта SumView.
    @required_command
    def draw(
        self,
        values: tuple[int, ...],
        index: int,
        total: int,
        tick_count: int,
    ) -> None:
        ...

    @guard
    def has_current(self, ctx: SumContext) -> bool:
        """Текущий индекс всё ещё указывает на элемент массива."""

        return not self._is_out_of_bounds(ctx)

    @guard
    def is_complete(self, ctx: SumContext) -> bool:
        """Текущий индекс уже вышел за границу массива."""

        return self._is_out_of_bounds(ctx)

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

    @action
    def add_current(self, ctx: SumContext) -> None:
        # Guard выбранного перехода гарантирует допустимость индекса.
        ctx.total += ctx.values[ctx.index]
        ctx.index += 1

    @action
    def count_tick(self, ctx: SumContext) -> None:
        ctx.tick_count += 1

    @action(emit=draw)
    def publish_draw(self, ctx: SumContext, emit: Emit) -> None:
        # Emit выдан именно этому Action и уже привязан к draw;
        # runtime перенесёт команду в FIFO лишь после всего перехода.
        emit(
            values=tuple(ctx.values),
            index=ctx.index,
            total=ctx.total,
            tick_count=ctx.tick_count,
        )

    @action
    def clear(self, ctx: SumContext) -> None:
        ctx.values.clear()
        ctx.index = 0
        ctx.total = 0
        ctx.tick_count = 0

    # Переходы являются class-атрибутами и находятся рядом со всеми
    # элементами описания автомата. Runtime-контекста у них нет.
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
        guard=is_complete,
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
        # Подтверждение возвращает Controller из промежуточного состояния
        # publishing только после фактической обработки команды draw.
        emit()

    on_draw = transition(
        source=ready,
        event=draw,
        actions=(apply_snapshot, notify_draw_completed),
        target=ready,
    )


@dataclass(frozen=True)
class Sample:
    """Программа и адресуемые объекты, необходимые сценарию запуска."""

    program: Program
    controller: AutomatonObject
    view: AutomatonObject


def build_sample() -> Sample:
    """Создаёт два объекта и явное соединение их операций."""

    controller = AutomatonObject(
        name="controller",
        automaton=SumController,
        initial_context=SumContext(),
    )
    view = AutomatonObject(
        name="view",
        automaton=SumView,
        initial_context=ViewContext(),
    )

    program = Program(
        objects=(controller, view),
        connections=(
            Connection(
                required=(controller, SumController.draw),
                provided=(view, SumView.draw),
            ),
            Connection(
                required=(view, SumView.draw_completed),
                provided=(controller, SumController.draw_completed),
            ),
        ),
    )
    return Sample(program=program, controller=controller, view=view)


def calculate_sum(values: Sequence[int]) -> tuple[int, ViewContext]:
    """Выполняет модель до ``done`` и возвращает результат со снимком View."""

    sample = build_sample()
    runtime = Runtime(sample.program)

    runtime.send(sample.controller, SumController.start, values=values)
    runtime.run()

    while runtime.snapshot(sample.controller).state is not SumController.done:
        # tick — пользовательская команда. step() ниже обрабатывает ровно одно
        # сообщение; run() доставляет draw объекту View и подтверждение обратно.
        runtime.send(sample.controller, SumController.tick)
        runtime.step()
        runtime.run()

    controller = runtime.snapshot(sample.controller)
    view = runtime.snapshot(sample.view)
    return controller.total, view


def main() -> None:
    """Показывает ожидаемое поведение на трёх граничных сценариях."""

    cases = (
        ([], 0),
        ([7], 7),
        ([2, 4, 6], 12),
    )

    for values, expected in cases:
        actual, view = calculate_sum(values)
        assert actual == expected
        assert view.total == expected
        print(
            f"values={values}, total={actual}, "
            f"index={view.index}, ticks={view.tick_count}"
        )


if __name__ == "__main__":
    main()
