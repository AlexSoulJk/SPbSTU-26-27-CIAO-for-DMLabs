"""Учебный пример пошагового вычисления суммы массива."""

from .automatos import SumContext, SumController, SumView, ViewContext
from .program import Sample, build_sample

__all__ = [
    "Sample",
    "SumContext",
    "SumController",
    "SumView",
    "ViewContext",
    "build_sample",
]
