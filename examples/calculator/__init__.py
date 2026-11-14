"""Учебный калькулятор с разделёнными Controller, View и Window."""

from .automatos import (
    CalculatorContext,
    CalculatorController,
    CalculatorView,
    CalculatorViewContext,
    OperatorContext,
    OperatorService,
    TokenKind,
    tokenize,
)
from .contracts import (
    CalculationPhase,
    CalculatorSnapshot,
    ControlsPresentation,
    DataPresentation,
    StartInput,
    StatusPresentation,
)
from .program import Sample, build_sample

__all__ = [
    "CalculationPhase",
    "CalculatorContext",
    "CalculatorController",
    "CalculatorSnapshot",
    "CalculatorView",
    "CalculatorViewContext",
    "ControlsPresentation",
    "DataPresentation",
    "OperatorContext",
    "OperatorService",
    "Sample",
    "StartInput",
    "StatusPresentation",
    "TokenKind",
    "build_sample",
    "tokenize",
]
