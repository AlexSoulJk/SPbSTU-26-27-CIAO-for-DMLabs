"""View-автомат учебного примера суммы массива."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import (
    AutomatonContext,
    Emits,
    State,
    ViewAutomaton,
    action,
    guard,
    provided_command,
    required_command,
    transition,
)

from ..contracts import (
    CalculationMode,
    ControlsPresentation,
    DataPresentation,
    SnapshotPhase,
    StartInput,
    StatusPresentation,
    SumSnapshot,
)


@dataclass
class ViewContext(AutomatonContext):
    """Последние доменные данные, нужные для независимых UI-представлений."""

    values: tuple[int, ...] = ()
    mode: CalculationMode = CalculationMode.STEP_BY_STEP
    index: int = 0
    total: int = 0
    tick_count: int = 0
    phase: SnapshotPhase = SnapshotPhase.IDLE


class SumView(ViewAutomaton[ViewContext]):
    """Маршрутизирует намерения Window и формирует presentation-DTO."""

    idle = State(initial=True)
    step_ready = State()
    step_pending = State()
    continuous_running = State()
    completed = State()
    reset_pending = State()
    final = State(final=True)

    @provided_command(external=True)
    def init_clicked(self, request: StartInput) -> None: ...

    @provided_command(external=True)
    def next_clicked(self) -> None: ...

    @provided_command(external=True)
    def reset_clicked(self) -> None: ...

    @provided_command(external=True)
    def finish_clicked(self) -> None: ...

    @provided_command
    def draw(self, snapshot: SumSnapshot) -> None: ...

    @required_command
    def start(self, request: StartInput) -> None: ...

    @required_command
    def tick(self) -> None: ...

    @required_command
    def reset(self) -> None: ...

    @required_command
    def finish(self) -> None: ...

    @required_command
    def draw_completed(self) -> None: ...

    @required_command(external=True)
    def render_data(self, presentation: DataPresentation) -> None: ...

    @required_command(external=True)
    def render_controls(self, presentation: ControlsPresentation) -> None: ...

    @required_command(external=True)
    def render_status(self, presentation: StatusPresentation) -> None: ...

    @guard(text="выбран пошаговый режим")
    def step_mode(self, ctx: ViewContext, request: StartInput) -> bool:
        return bool(request.values) and request.mode is CalculationMode.STEP_BY_STEP

    @guard(text="values пуст")
    def empty_request(self, ctx: ViewContext, request: StartInput) -> bool:
        return not request.values

    @guard(text="получен итоговый снимок")
    def completed_snapshot(
        self,
        ctx: ViewContext,
        snapshot: SumSnapshot,
    ) -> bool:
        return snapshot.phase is SnapshotPhase.COMPLETED

    @action
    def remember_start(self, ctx: ViewContext, request: StartInput) -> None:
        ctx.values = request.values
        ctx.mode = request.mode
        ctx.index = ctx.total = ctx.tick_count = 0
        ctx.phase = SnapshotPhase.IDLE

    @action
    def apply_snapshot(self, ctx: ViewContext, snapshot: SumSnapshot) -> None:
        ctx.values = snapshot.values
        ctx.index = snapshot.index
        ctx.total = snapshot.total
        ctx.tick_count = snapshot.tick_count
        ctx.phase = snapshot.phase

    @staticmethod
    def _data(ctx: ViewContext) -> DataPresentation:
        selected = ctx.index - 1 if ctx.tick_count and ctx.index else None
        return DataPresentation(
            ctx.values,
            selected,
            ctx.total,
            ctx.index,
            ctx.tick_count,
        )

    @staticmethod
    def _idle_controls() -> ControlsPresentation:
        return ControlsPresentation(True, True, False, False, False, False)

    @staticmethod
    def _step_controls(*, enabled: bool) -> ControlsPresentation:
        return ControlsPresentation(False, False, True, enabled, False, False)

    @staticmethod
    def _running_controls() -> ControlsPresentation:
        return ControlsPresentation(False, False, False, False, False, False)

    @staticmethod
    def _completed_controls() -> ControlsPresentation:
        return ControlsPresentation(False, False, False, False, True, True)

    @action(emits=(start, render_data, render_controls, render_status))
    def publish_start(
        self,
        ctx: ViewContext,
        request: StartInput,
        emits: Emits,
    ) -> None:
        emits[self.start](request)
        emits[self.render_data](self._data(ctx))
        controls = self._running_controls()
        if request.values and request.mode is CalculationMode.STEP_BY_STEP:
            controls = self._step_controls(enabled=True)
        emits[self.render_controls](controls)
        emits[self.render_status](StatusPresentation("Вычисление запущено"))

    @action(emits=(tick, render_controls, render_status))
    def publish_next(self, ctx: ViewContext, emits: Emits) -> None:
        emits[self.tick]()
        emits[self.render_controls](self._step_controls(enabled=False))
        emits[self.render_status](StatusPresentation("Выполняется один шаг"))

    @action(emits=(render_data, render_controls, render_status, draw_completed))
    def publish_snapshot(self, ctx: ViewContext, emits: Emits) -> None:
        emits[self.render_data](self._data(ctx))
        if ctx.phase is SnapshotPhase.RUNNING:
            controls = self._step_controls(enabled=True)
            status = "Можно выполнить следующий шаг"
        elif ctx.phase is SnapshotPhase.COMPLETED:
            controls = self._completed_controls()
            status = f"Готово: сумма равна {ctx.total}"
        else:
            controls = self._idle_controls()
            status = "Введите массив и выберите режим"
        emits[self.render_controls](controls)
        emits[self.render_status](StatusPresentation(status))
        emits[self.draw_completed]()

    @action(emits=(reset, render_controls, render_status))
    def publish_reset(self, ctx: ViewContext, emits: Emits) -> None:
        emits[self.reset]()
        emits[self.render_controls](self._running_controls())
        emits[self.render_status](StatusPresentation("Выполняется сброс"))

    @action(emits=(finish, render_controls, render_status))
    def publish_finish(self, ctx: ViewContext, emits: Emits) -> None:
        emits[self.finish]()
        emits[self.render_controls](self._running_controls())
        emits[self.render_status](StatusPresentation("Работа завершена"))

    on_empty_init = transition(
        source=idle,
        event=init_clicked,
        guard=empty_request,
        actions=(remember_start, publish_start),
        target=step_pending,
    )
    on_step_init = transition(
        source=idle,
        event=init_clicked,
        guard=step_mode,
        actions=(remember_start, publish_start),
        target=step_ready,
    )
    on_automatic_init = transition(
        source=idle,
        event=init_clicked,
        otherwise=True,
        actions=(remember_start, publish_start),
        target=continuous_running,
    )
    on_next = transition(
        source=step_ready,
        event=next_clicked,
        actions=(publish_next,),
        target=step_pending,
    )
    on_completed_step_draw = transition(
        source=step_pending,
        event=draw,
        guard=completed_snapshot,
        actions=(apply_snapshot, publish_snapshot),
        target=completed,
    )
    on_running_step_draw = transition(
        source=step_pending,
        event=draw,
        otherwise=True,
        actions=(apply_snapshot, publish_snapshot),
        target=step_ready,
    )
    on_automatic_draw = transition(
        source=continuous_running,
        event=draw,
        actions=(apply_snapshot, publish_snapshot),
        target=completed,
    )
    on_reset = transition(
        source=completed,
        event=reset_clicked,
        actions=(publish_reset,),
        target=reset_pending,
    )
    on_reset_draw = transition(
        source=reset_pending,
        event=draw,
        actions=(apply_snapshot, publish_snapshot),
        target=idle,
    )
    on_finish = transition(
        source=completed,
        event=finish_clicked,
        actions=(publish_finish,),
        target=final,
    )


__all__ = ["SumView", "ViewContext"]
