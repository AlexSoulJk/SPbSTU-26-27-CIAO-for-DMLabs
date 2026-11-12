"""Controller учебного примера суммы массива."""

from __future__ import annotations

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

from ..contracts import CalculationMode, SnapshotPhase, StartInput, SumSnapshot


@dataclass
class SumContext(AutomatonContext):
    """Вычислительные данные и назначение ожидаемого подтверждения View."""

    values: list[int] = field(default_factory=list)
    mode: CalculationMode = CalculationMode.STEP_BY_STEP
    index: int = 0
    total: int = 0
    tick_count: int = 0
    pending_phase: SnapshotPhase = SnapshotPhase.IDLE


class SumController(ControllerAutomaton[SumContext]):
    """Вычисляет сумму по одному элементу на каждый переход ``tick``."""

    idle = State(initial=True)
    running_step = State()
    running_all = State()
    publishing = State()
    completed = State()
    done = State(final=True)

    @provided_command
    def start(self, request: StartInput) -> None: ...

    @provided_command
    def tick(self) -> None: ...

    @provided_command
    def reset(self) -> None: ...

    @provided_command
    def finish(self) -> None: ...

    @provided_command
    def draw_completed(self) -> None: ...

    @required_command(text="публикует доменный снимок")
    def draw(self, snapshot: SumSnapshot) -> None: ...

    @required_command(text="планирует следующий вычислительный шаг")
    def continue_run(self) -> None: ...

    @guard(text="values пуст")
    def empty_request(self, ctx: SumContext, request: StartInput) -> bool:
        return not request.values

    @guard(text="режим пошаговый")
    def step_request(self, ctx: SumContext, request: StartInput) -> bool:
        return bool(request.values) and request.mode is CalculationMode.STEP_BY_STEP

    @guard(text="после текущего есть следующий элемент")
    def has_more_after_current(self, ctx: SumContext) -> bool:
        return ctx.index + 1 < len(ctx.values)

    @guard(text="ожидается продолжение пошагового режима")
    def pending_running(self, ctx: SumContext) -> bool:
        return ctx.pending_phase is SnapshotPhase.RUNNING

    @guard(text="ожидается завершение")
    def pending_completed(self, ctx: SumContext) -> bool:
        return ctx.pending_phase is SnapshotPhase.COMPLETED

    @action
    def initialize(self, ctx: SumContext, request: StartInput) -> None:
        ctx.values = list(request.values)
        ctx.mode = request.mode
        ctx.index = ctx.total = ctx.tick_count = 0
        ctx.pending_phase = SnapshotPhase.IDLE

    @action(text="total += values[index]; index++; tick_count++")
    def add_current(self, ctx: SumContext) -> None:
        # Доступность элемента гарантируют start-развилка и инвариант running-*.
        ctx.total += ctx.values[ctx.index]
        ctx.index += 1
        ctx.tick_count += 1

    @action
    def mark_running(self, ctx: SumContext) -> None:
        ctx.pending_phase = SnapshotPhase.RUNNING

    @action
    def mark_completed(self, ctx: SumContext) -> None:
        ctx.pending_phase = SnapshotPhase.COMPLETED

    @action
    def clear(self, ctx: SumContext) -> None:
        ctx.values.clear()
        ctx.index = ctx.total = ctx.tick_count = 0
        ctx.pending_phase = SnapshotPhase.IDLE

    @action(emit=draw)
    def publish_snapshot(self, ctx: SumContext, emit: Emit) -> None:
        emit(
            SumSnapshot(
                tuple(ctx.values),
                ctx.index,
                ctx.total,
                ctx.tick_count,
                ctx.pending_phase,
            )
        )

    @action(emit=continue_run)
    def schedule_next(self, ctx: SumContext, emit: Emit) -> None:
        emit()

    on_empty_start = transition(
        source=idle,
        event=start,
        guard=empty_request,
        actions=(initialize, mark_completed, publish_snapshot),
        target=publishing,
    )
    on_step_start = transition(
        source=idle,
        event=start,
        guard=step_request,
        actions=(initialize,),
        target=running_step,
    )
    on_automatic_start = transition(
        source=idle,
        event=start,
        otherwise=True,
        actions=(initialize, schedule_next),
        target=running_all,
    )
    on_step_tick = transition(
        source=running_step,
        event=tick,
        guard=has_more_after_current,
        actions=(add_current, mark_running, publish_snapshot),
        target=publishing,
    )
    on_last_step_tick = transition(
        source=running_step,
        event=tick,
        otherwise=True,
        actions=(add_current, mark_completed, publish_snapshot),
        target=publishing,
    )
    on_automatic_tick = transition(
        source=running_all,
        event=tick,
        guard=has_more_after_current,
        actions=(add_current, schedule_next),
        target=running_all,
    )
    on_last_automatic_tick = transition(
        source=running_all,
        event=tick,
        otherwise=True,
        actions=(add_current, mark_completed, publish_snapshot),
        target=publishing,
    )
    on_running_draw_completed = transition(
        source=publishing,
        event=draw_completed,
        guard=pending_running,
        target=running_step,
    )
    on_completed_draw_completed = transition(
        source=publishing,
        event=draw_completed,
        guard=pending_completed,
        target=completed,
    )
    on_idle_draw_completed = transition(
        source=publishing,
        event=draw_completed,
        otherwise=True,
        target=idle,
    )
    on_reset = transition(
        source=completed,
        event=reset,
        actions=(clear, publish_snapshot),
        target=publishing,
    )
    on_finish = transition(source=completed, event=finish, target=done)


__all__ = ["SumContext", "SumController"]
