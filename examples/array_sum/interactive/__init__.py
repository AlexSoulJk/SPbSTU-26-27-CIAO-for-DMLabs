"""Интерактивный вариант ArraySum с явными Controller, View и Window."""

from .contracts import (
    CalculationMode,
    ControlsPresentation,
    DataPresentation,
    SnapshotPhase,
    StartInput,
    StatusPresentation,
    SumSnapshot,
)
from .controller import InteractiveSumContext, InteractiveSumController
from .program import InteractiveSample, build_interactive_sample
from .view import InteractiveSumView, InteractiveViewContext

__all__ = [
    "CalculationMode", "ControlsPresentation", "DataPresentation",
    "InteractiveSample", "InteractiveSumContext", "InteractiveSumController",
    "InteractiveSumView", "InteractiveViewContext", "SnapshotPhase", "StartInput",
    "StatusPresentation", "SumSnapshot", "build_interactive_sample",
]
