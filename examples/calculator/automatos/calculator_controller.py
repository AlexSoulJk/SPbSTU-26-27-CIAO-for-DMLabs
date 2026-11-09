from ciao import (
    ControllerAutomaton, State, guard,
    AutomatonContext, required_query,
    provided_command, required_command, transition, action,
    Queries, Emit, Query)
from dataclasses import dataclass, field

from .operator_service import TokenKind
from .utils import tokenize

## Контроллер калькулятора

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
    phase: str = "idle"


class CalculatorController(ControllerAutomaton[CalculatorContext]):
    
    idle = State(initial=True)
    converting = State()
    waiting_conversion = State()
    waiting_evaluation = State()
    evaluating = State()
    waiting_result = State()
    waiting_finish = State()
    done = State(final=True)

    @provided_command(external=True)
    def start(self, expression: str) -> None:
        ...

    @provided_command(external=True)
    def tick(self) -> None:
        ...
    
    @provided_command
    def draw_completed(self) -> None:
        ...
    
    @required_command
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
    
    # Требуемые запросы OperatorService
    @required_query
    def classify_token(self, token: str) -> TokenKind:
        ...

    @required_query
    def precedence(self, symbol: str) -> int:
        ...

    @required_query
    def calculate(
        self,
        symbol: str,
        left: float,
        right: float,
    ) -> float:
        ...
    
    # Guards

    @guard(text="Есть необработанный входной токен")
    def has_input(self, ctx: CalculatorContext) -> bool:
        return ctx.token_index < len(ctx.tokens)

    @guard(text="Есть необработанный токен ОПН")
    def has_rpn(self, ctx: CalculatorContext) -> bool:
        return ctx.eval_index < len(ctx.rpn)

    # Локальные действия

    @action(text="Инициализировать вычисление")
    def initialize(
        self,
        ctx: CalculatorContext,
        expression: str,
    ) -> None:
        ctx.expression = expression
        ctx.tokens = tokenize(expression)

        ctx.token_index = 0
        ctx.operators.clear()
        ctx.rpn.clear()

        ctx.eval_index = 0
        ctx.stack.clear()

        ctx.current_token = None
        ctx.result = None
        ctx.phase = "converting"

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

        if kind == TokenKind.NUMBER:
            ctx.rpn.append(token)

        elif kind == TokenKind.LEFT_PAREN:
            ctx.operators.append(token)

        elif kind == TokenKind.RIGHT_PAREN:
            while ctx.operators and ctx.operators[-1] != "(":
                ctx.rpn.append(ctx.operators.pop())

            if not ctx.operators:
                raise ValueError("Несогласованные скобки")

            ctx.operators.pop()

        elif kind == TokenKind.OPERATOR:
            priority = queries[self.precedence](
                symbol=token
            )

            while ctx.operators and ctx.operators[-1] != "(":
                top = ctx.operators[-1]
                top_priority = queries[self.precedence](
                    symbol=top
                )

                if top_priority < priority:
                    break

                ctx.rpn.append(ctx.operators.pop())

            ctx.operators.append(token)

        else:
            raise ValueError(f"Недопустимый токен: {token}")

        ctx.token_index += 1

    @action(text="Вытолкнуть оставшиеся операторы")
    def finish_conversion(self, ctx: CalculatorContext) -> None:
        while ctx.operators:
            operator = ctx.operators.pop()

            if operator == "(":
                raise ValueError("Несогласованные скобки")

            ctx.rpn.append(operator)

        ctx.phase = "evaluating"
        ctx.current_token = None

    @action(
        query=calculate,
        text="Вычислить очередной токен ОПН",
    )
    def evaluate_token(
        self,
        ctx: CalculatorContext,
        query: Query,
    ) -> None:
        token = ctx.rpn[ctx.eval_index]
        ctx.current_token = token

        # После преобразования числа и операторы
        # различаются по принадлежности таблице символов.
        if token not in ("+", "-", "*", "/"):
            ctx.stack.append(float(token))

        else:
            if len(ctx.stack) < 2:
                raise ValueError("Недостаточно операндов")

            right = ctx.stack[-1]
            left = ctx.stack[-2]

            result = query(
                symbol=token,
                left=left,
                right=right,
            )

            ctx.stack[-2:] = [result]

        ctx.eval_index += 1

    @action(text="Получить окончательный результат")
    def finish_evaluation(self, ctx: CalculatorContext) -> None:
        if len(ctx.stack) != 1:
            raise ValueError("Некорректное выражение")

        ctx.result = ctx.stack[0]
        ctx.current_token = None
        ctx.phase = "done"

    # Публикация снимка

    @action(emit=draw, text="Опубликовать состояние")
    def publish(
        self,
        ctx: CalculatorContext,
        emit: Emit,
    ) -> None:
        emit(
            expression=ctx.expression,
            phase=ctx.phase,
            current_token=ctx.current_token,
            rpn=tuple(ctx.rpn),
            stack=tuple(ctx.stack),
            result=ctx.result,
        )

    # Переходы

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
        target=waiting_conversion,
    )

    on_convert_complete = transition(
        source=converting,
        event=tick,
        otherwise=True,
        actions=(finish_conversion, publish),
        target=waiting_evaluation,
    )

    on_conversion_drawn = transition(
        source=waiting_conversion,
        event=draw_completed,
        target=converting,
    )

    on_conversion_finished_drawn = transition(
        source=waiting_evaluation,
        event=draw_completed,
        target=evaluating,
    )

    on_evaluate_token = transition(
        source=evaluating,
        event=tick,
        guard=has_rpn,
        actions=(evaluate_token, publish),
        target=waiting_result,
    )

    on_evaluation_complete = transition(
        source=evaluating,
        event=tick,
        otherwise=True,
        actions=(finish_evaluation, publish),
        target=waiting_finish,
    )

    on_result_drawn = transition(
        source=waiting_result,
        event=draw_completed,
        target=evaluating,
    )

    on_finished_drawn = transition(
        source=waiting_finish,
        event=draw_completed,
        target=done,
    )