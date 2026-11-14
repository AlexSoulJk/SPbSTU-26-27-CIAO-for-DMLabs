"""View-автомат пошагового калькулятора."""

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
    CalculationPhase,
    CalculatorSnapshot,
    ControlsPresentation,
    DataPresentation,
    StartInput,
    StatusPresentation,
)
from .utils import tokenize


@dataclass
class CalculatorViewContext(AutomatonContext):
    expression: str = ""
    phase: CalculationPhase = CalculationPhase.IDLE
    current_token: str | None = None
    rpn: tuple[str, ...] = ()
    stack: tuple[float, ...] = ()
    result: float | None = None
    update_count: int = 0


class CalculatorView(ViewAutomaton[CalculatorViewContext]):
    """Маршрутизирует Window-события и публикует presentation-DTO."""

    idle = State(initial=True)
    running = State()
    step_pending = State()
    completed = State()
    reset_pending = State()
    final = State(final=True)

    @provided_command(external=True)
    def start_clicked(self, request: StartInput) -> None: ...

    @provided_command(external=True)
    def next_clicked(self) -> None: ...

    @provided_command(external=True)
    def reset_clicked(self) -> None: ...

    @provided_command(external=True)
    def finish_clicked(self) -> None: ...

    @provided_command
    def draw(self, snapshot: CalculatorSnapshot) -> None: ...

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

    @guard(text="получен итоговый снимок")
    def completed_snapshot(
        self,
        ctx: CalculatorViewContext,
        snapshot: CalculatorSnapshot,
    ) -> bool:
        return snapshot.phase is CalculationPhase.COMPLETED

    @action
    def remember_start(
        self,
        ctx: CalculatorViewContext,
        request: StartInput,
    ) -> None:
        # Проверяем ввод до emit(start), чтобы ошибка не оставила View в running
        # при всё ещё idle Controller. Само вычисление остаётся в Controller.
        tokenize(request.expression)
        ctx.expression = request.expression
        ctx.phase = CalculationPhase.IDLE
        ctx.current_token = None
        ctx.rpn = ()
        ctx.stack = ()
        ctx.result = None

    @action(text="Обновить данные представления")
    def apply_snapshot(
        self,
        ctx: CalculatorViewContext,
        snapshot: CalculatorSnapshot,
    ) -> None:
        ctx.expression = snapshot.expression
        ctx.phase = snapshot.phase
        ctx.current_token = snapshot.current_token
        ctx.rpn = snapshot.rpn
        ctx.stack = snapshot.stack
        ctx.result = snapshot.result
        ctx.update_count += 1

    @staticmethod
    def _data(ctx: CalculatorViewContext) -> DataPresentation:
        return DataPresentation(
            expression=ctx.expression,
            phase=ctx.phase,
            current_token=ctx.current_token,
            rpn=ctx.rpn,
            stack=ctx.stack,
            result=ctx.result,
        )

    @staticmethod
    def _idle_controls() -> ControlsPresentation:
        return ControlsPresentation(True, True, False, False, False, False)

    @staticmethod
    def _step_controls(*, enabled: bool) -> ControlsPresentation:
        return ControlsPresentation(False, False, True, enabled, False, False)

    @staticmethod
    def _busy_controls() -> ControlsPresentation:
        return ControlsPresentation(False, False, False, False, False, False)

    @staticmethod
    def _completed_controls() -> ControlsPresentation:
        return ControlsPresentation(False, False, False, False, True, True)

    @action(emits=(start, render_data, render_controls, render_status))
    def publish_start(
        self,
        ctx: CalculatorViewContext,
        request: StartInput,
        emits: Emits,
    ) -> None:
        emits[self.start](request)
        emits[self.render_data](self._data(ctx))
        emits[self.render_controls](self._step_controls(enabled=True))
        emits[self.render_status](
            StatusPresentation("Нажмите «Следующий шаг»")
        )

    @action(emits=(tick, render_controls, render_status))
    def publish_next(self, ctx: CalculatorViewContext, emits: Emits) -> None:
        emits[self.tick]()
        emits[self.render_controls](self._step_controls(enabled=False))
        emits[self.render_status](StatusPresentation("Выполняется один шаг"))

    @action(
        emits=(render_data, render_controls, render_status, draw_completed)
    )
    def publish_snapshot(
        self,
        ctx: CalculatorViewContext,
        emits: Emits,
    ) -> None:
        emits[self.render_data](self._data(ctx))
        if ctx.phase is CalculationPhase.COMPLETED:
            controls = self._completed_controls()
            status = f"Готово: результат {ctx.result}"
        elif ctx.phase is CalculationPhase.CONVERTING:
            controls = self._step_controls(enabled=True)
            status = "Преобразование выражения в ОПН"
        elif ctx.phase is CalculationPhase.EVALUATING:
            controls = self._step_controls(enabled=True)
            status = "Вычисление выражения в ОПН"
        else:
            controls = self._idle_controls()
            status = "Введите выражение"
        emits[self.render_controls](controls)
        emits[self.render_status](StatusPresentation(status))
        emits[self.draw_completed]()

    @action(emits=(reset, render_controls, render_status))
    def publish_reset(self, ctx: CalculatorViewContext, emits: Emits) -> None:
        emits[self.reset]()
        emits[self.render_controls](self._busy_controls())
        emits[self.render_status](StatusPresentation("Выполняется сброс"))

    @action(emits=(finish, render_controls, render_status))
    def publish_finish(self, ctx: CalculatorViewContext, emits: Emits) -> None:
        emits[self.finish]()
        emits[self.render_controls](self._busy_controls())
        emits[self.render_status](StatusPresentation("Работа завершена"))

    on_start = transition(
        source=idle,
        event=start_clicked,
        actions=(remember_start, publish_start),
        target=running,
    )
    on_next = transition(
        source=running,
        event=next_clicked,
        actions=(publish_next,),
        target=step_pending,
    )
    on_completed_draw = transition(
        source=step_pending,
        event=draw,
        guard=completed_snapshot,
        actions=(apply_snapshot, publish_snapshot),
        target=completed,
    )
    on_progress_draw = transition(
        source=step_pending,
        event=draw,
        otherwise=True,
        actions=(apply_snapshot, publish_snapshot),
        target=running,
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


__all__ = ["CalculatorView", "CalculatorViewContext"]
