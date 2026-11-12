"""Учебный пример суммы массива с разделёнными Controller, View и Window."""

from .automatos import SumContext, SumController, SumView, ViewContext
from .contracts import (
    CalculationMode,
    ControlsPresentation,
    DataPresentation,
    SnapshotPhase,
    StartInput,
    StatusPresentation,
    SumSnapshot,
)
from .program import Sample, build_sample

__all__ = [
    "CalculationMode",
    "ControlsPresentation",
    "DataPresentation",
    "Sample",
    "SnapshotPhase",
    "StartInput",
    "StatusPresentation",
    "SumContext",
    "SumController",
    "SumSnapshot",
    "SumView",
    "ViewContext",
    "build_sample",
]
