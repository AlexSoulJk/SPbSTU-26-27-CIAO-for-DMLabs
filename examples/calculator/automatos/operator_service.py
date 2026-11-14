
"""Сервис классификации токенов и выполнения бинарных операций."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from collections.abc import Callable

from ciao import Automaton, AutomatonContext, State, provided_query


class TokenKind(Enum):
    """Категория токена арифметического выражения."""

    NUMBER = auto()
    OPERATOR = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    INVALID = auto()


@dataclass
class OperatorContext(AutomatonContext):
    """Таблицы операторов, принадлежащие экземпляру сервиса."""

    priorities: dict[str, int] = field(
        default_factory=lambda: {
            "+": 1,
            "-": 1,
            "*": 2,
            "/": 2,
        }
    )

    operations: dict[str, Callable[[float, float], float]] = field(
        default_factory=lambda: {
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: a / b,
        }
    )


class OperatorService(Automaton[OperatorContext]):
    """Предоставляет информацию об операциях и токенах."""

    ready = State(initial=True)

    @provided_query
    def classify(
        self,
        ctx: OperatorContext,
        token: str,
    ) -> TokenKind:
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return TokenKind.NUMBER

        if token in ctx.operations:
            return TokenKind.OPERATOR

        if token == "(":
            return TokenKind.LEFT_PAREN

        if token == ")":
            return TokenKind.RIGHT_PAREN

        return TokenKind.INVALID

    @provided_query
    def precedence(
        self,
        ctx: OperatorContext,
        symbol: str,
    ) -> int:
        return ctx.priorities[symbol]

    @provided_query
    def calculate(
        self,
        ctx: OperatorContext,
        symbol: str,
        left: float,
        right: float,
    ) -> float:
        operation = ctx.operations[symbol]
        return operation(left, right)
