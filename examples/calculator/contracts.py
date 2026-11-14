"""DTO учебного примера пошагового калькулятора."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CalculationPhase(str, Enum):
    """Семантическая фаза вычисления выражения."""

    IDLE = "idle"
    CONVERTING = "converting"
    EVALUATING = "evaluating"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class StartInput:
    expression: str


@dataclass(frozen=True, slots=True)
class CalculatorSnapshot:
    expression: str
    phase: CalculationPhase
    current_token: str | None
    rpn: tuple[str, ...]
    stack: tuple[float, ...]
    result: float | None


@dataclass(frozen=True, slots=True)
class DataPresentation:
    expression: str
    phase: CalculationPhase
    current_token: str | None
    rpn: tuple[str, ...]
    stack: tuple[float, ...]
    result: float | None


@dataclass(frozen=True, slots=True)
class ControlsPresentation:
    show_start: bool
    input_enabled: bool
    show_next: bool
    next_enabled: bool
    show_reset: bool
    show_finish: bool


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    text: str


__all__ = [
    "CalculationPhase",
    "CalculatorSnapshot",
    "ControlsPresentation",
    "DataPresentation",
    "StartInput",
    "StatusPresentation",
]
