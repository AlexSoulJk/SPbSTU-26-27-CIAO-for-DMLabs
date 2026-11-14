"""Детерминированная токенизация арифметических выражений."""

from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?|[()+*/-]")


def tokenize(expression: str) -> list[str]:
    """Разбивает поддерживаемое выражение или отклоняет посторонний текст."""

    tokens = []
    pos = 0

    for match in TOKEN_PATTERN.finditer(expression):
        if expression[pos:match.start()].strip():
            raise ValueError("Недопустимый символ")

        tokens.append(match.group())
        pos = match.end()

    if expression[pos:].strip():
        raise ValueError("Недопустимый символ")

    if not tokens:
        raise ValueError("Пустое выражение")

    return tokens
