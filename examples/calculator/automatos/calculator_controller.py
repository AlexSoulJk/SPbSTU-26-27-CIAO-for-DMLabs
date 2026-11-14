"""Controller пошагового калькулятора."""

from __future__ import annotations

from dataclasses import dataclass, field

from ciao import (
    AutomatonContext,
    ControllerAutomaton,
    Emit,
    Queries,
    Query,
    State,
    action,
    guard,
    provided_command,
    required_command,
    required_query,
    transition,
)

from ..contracts import CalculationPhase, CalculatorSnapshot, StartInput
from .operator_service import TokenKind
from .utils import tokenize


@dataclass
class CalculatorContext(AutomatonContext):
    expression: str = ""
    tokens: list[str] = field(default_factory=list)
    token_index: int = 0
    operators: list[str] = field(default_factory=list)
    rpn: list[str] = field(default_factory=list)
    eval_index: int = 0
    stack: list[float] = field(default_factory=list)
    current_token: str | None = None
    result: float | None = None
    phase: CalculationPhase = CalculationPhase.IDLE
    pending_phase: CalculationPhase = CalculationPhase.IDLE


class CalculatorController(ControllerAutomaton[CalculatorContext]):
    """Преобразует выражение в ОПН и вычисляет его по одному токену."""

    idle = State(initial=True)
    converting = State()
    evaluating = State()
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

    @required_command
    def draw(self, snapshot: CalculatorSnapshot) -> None: ...

    @required_query
    def classify_token(self, token: str) -> TokenKind: ...

    @required_query
    def precedence(self, symbol: str) -> int: ...

    @required_query
    def calculate(
        self,
        symbol: str,
        left: float,
        right: float,
    ) -> float: ...

    @guard(text="Есть необработанный входной токен")
    def has_input(self, ctx: CalculatorContext) -> bool:
        return ctx.token_index < len(ctx.tokens)

    @guard(text="Есть необработанный токен ОПН")
    def has_rpn(self, ctx: CalculatorContext) -> bool:
        return ctx.eval_index < len(ctx.rpn)

    @guard(text="ожидается продолжение преобразования")
    def pending_conversion(self, ctx: CalculatorContext) -> bool:
        return ctx.pending_phase is CalculationPhase.CONVERTING

    @guard(text="ожидается продолжение вычисления")
    def pending_evaluation(self, ctx: CalculatorContext) -> bool:
        return ctx.pending_phase is CalculationPhase.EVALUATING

    @guard(text="ожидается завершение")
    def pending_completed(self, ctx: CalculatorContext) -> bool:
        return ctx.pending_phase is CalculationPhase.COMPLETED

    @action(text="Инициализировать вычисление")
    def initialize(self, ctx: CalculatorContext, request: StartInput) -> None:
        ctx.expression = request.expression
        ctx.tokens = tokenize(request.expression)
        ctx.token_index = 0
        ctx.operators.clear()
        ctx.rpn.clear()
        ctx.eval_index = 0
        ctx.stack.clear()
        ctx.current_token = None
        ctx.result = None
        ctx.phase = CalculationPhase.CONVERTING
        ctx.pending_phase = CalculationPhase.CONVERTING

    @action(
        queries=(classify_token, precedence),
        text="Преобразовать текущий токен в ОПН",
    )
    def convert_token(
        self,
        ctx: CalculatorContext,
        queries: Queries,
    ) -> None:
        token = ctx.tokens[ctx.token_index]
        kind = queries[self.classify_token](token=token)
        ctx.current_token = token

        if kind is TokenKind.NUMBER:
            ctx.rpn.append(token)
        elif kind is TokenKind.LEFT_PAREN:
            ctx.operators.append(token)
        elif kind is TokenKind.RIGHT_PAREN:
            while ctx.operators and ctx.operators[-1] != "(":
                ctx.rpn.append(ctx.operators.pop())
            if not ctx.operators:
                raise ValueError("Несогласованные скобки")
            ctx.operators.pop()
        elif kind is TokenKind.OPERATOR:
            priority = queries[self.precedence](symbol=token)
            while ctx.operators and ctx.operators[-1] != "(":
                top = ctx.operators[-1]
                if queries[self.precedence](symbol=top) < priority:
                    break
                ctx.rpn.append(ctx.operators.pop())
            ctx.operators.append(token)
        else:
            raise ValueError(f"Недопустимый токен: {token}")

        ctx.token_index += 1
        ctx.pending_phase = CalculationPhase.CONVERTING

    @action(text="Вытолкнуть оставшиеся операторы")
    def finish_conversion(self, ctx: CalculatorContext) -> None:
        while ctx.operators:
            operator = ctx.operators.pop()
            if operator == "(":
                raise ValueError("Несогласованные скобки")
            ctx.rpn.append(operator)
        ctx.phase = CalculationPhase.EVALUATING
        ctx.pending_phase = CalculationPhase.EVALUATING
        ctx.current_token = None

    @action(query=calculate, text="Вычислить очередной токен ОПН")
    def evaluate_token(
        self,
        ctx: CalculatorContext,
        query: Query,
    ) -> None:
        token = ctx.rpn[ctx.eval_index]
        ctx.current_token = token
        if token not in ("+", "-", "*", "/"):
            ctx.stack.append(float(token))
        else:
            if len(ctx.stack) < 2:
                raise ValueError("Недостаточно операндов")
            right = ctx.stack[-1]
            left = ctx.stack[-2]
            ctx.stack[-2:] = [query(symbol=token, left=left, right=right)]
        ctx.eval_index += 1
        ctx.pending_phase = CalculationPhase.EVALUATING

    @action(text="Получить окончательный результат")
    def finish_evaluation(self, ctx: CalculatorContext) -> None:
        if len(ctx.stack) != 1:
            raise ValueError("Некорректное выражение")
        ctx.result = ctx.stack[0]
        ctx.current_token = None
        ctx.phase = CalculationPhase.COMPLETED
        ctx.pending_phase = CalculationPhase.COMPLETED

    @action(text="Сбросить прогресс вычисления")
    def reset_progress(self, ctx: CalculatorContext) -> None:
        # Выражение сохраняется для повторного запуска и согласованного UI.
        ctx.tokens.clear()
        ctx.token_index = 0
        ctx.operators.clear()
        ctx.rpn.clear()
        ctx.eval_index = 0
        ctx.stack.clear()
        ctx.current_token = None
        ctx.result = None
        ctx.phase = CalculationPhase.IDLE
        ctx.pending_phase = CalculationPhase.IDLE

    @action(emit=draw, text="Опубликовать состояние")
    def publish(self, ctx: CalculatorContext, emit: Emit) -> None:
        emit(
            CalculatorSnapshot(
                expression=ctx.expression,
                phase=ctx.phase,
                current_token=ctx.current_token,
                rpn=tuple(ctx.rpn),
                stack=tuple(ctx.stack),
                result=ctx.result,
            )
        )

    on_start = transition(
        source=idle,
        event=start,
        actions=(initialize,),
        target=converting,
    )
    on_convert_token = transition(
        source=converting,
        event=tick,
        guard=has_input,
        actions=(convert_token, publish),
        target=publishing,
    )
    on_convert_complete = transition(
        source=converting,
        event=tick,
        otherwise=True,
        actions=(finish_conversion, publish),
        target=publishing,
    )
    on_conversion_drawn = transition(
        source=publishing,
        event=draw_completed,
        guard=pending_conversion,
        target=converting,
    )
    on_conversion_finished_drawn = transition(
        source=publishing,
        event=draw_completed,
        guard=pending_evaluation,
        target=evaluating,
    )
    on_evaluate_token = transition(
        source=evaluating,
        event=tick,
        guard=has_rpn,
        actions=(evaluate_token, publish),
        target=publishing,
    )
    on_evaluation_complete = transition(
        source=evaluating,
        event=tick,
        otherwise=True,
        actions=(finish_evaluation, publish),
        target=publishing,
    )
    on_finished_drawn = transition(
        source=publishing,
        event=draw_completed,
        guard=pending_completed,
        target=completed,
    )
    on_reset = transition(
        source=completed,
        event=reset,
        actions=(reset_progress, publish),
        target=publishing,
    )
    on_reset_drawn = transition(
        source=publishing,
        event=draw_completed,
        otherwise=True,
        target=idle,
    )
    on_finish = transition(source=completed, event=finish, target=done)


__all__ = ["CalculatorContext", "CalculatorController"]
