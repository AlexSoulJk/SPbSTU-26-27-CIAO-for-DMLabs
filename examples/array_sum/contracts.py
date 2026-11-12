"""DTO учебного примера суммы массива."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CalculationMode(str, Enum):
    """Режим продвижения алгоритма после команды Init."""

    STEP_BY_STEP = "step_by_step"
    RUN_TO_COMPLETION = "run_to_completion"


class SnapshotPhase(str, Enum):
    """Семантическая фаза доменного снимка Controller."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class StartInput:
    values: tuple[int, ...]
    mode: CalculationMode


@dataclass(frozen=True, slots=True)
class SumSnapshot:
    values: tuple[int, ...]
    index: int
    total: int
    tick_count: int
    phase: SnapshotPhase


@dataclass(frozen=True, slots=True)
class DataPresentation:
    values: tuple[int, ...]
    selected_index: int | None
    total: int
    index: int
    tick_count: int


@dataclass(frozen=True, slots=True)
class ControlsPresentation:
    show_init: bool
    mode_enabled: bool
    show_next: bool
    next_enabled: bool
    show_reset: bool
    show_finish: bool


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    text: str


__all__ = [
    "CalculationMode",
    "ControlsPresentation",
    "DataPresentation",
    "SnapshotPhase",
    "StartInput",
    "StatusPresentation",
    "SumSnapshot",
]
