"""Общие компоненты необязательного слоя визуализации."""

from .tkinter_adapter import TkTraceAdapter
from .drawio import export_program_drawio

__all__ = ["TkTraceAdapter", "export_program_drawio"]
