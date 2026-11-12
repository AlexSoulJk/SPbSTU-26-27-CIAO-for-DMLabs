"""Общие компоненты необязательного слоя визуализации без eager Tkinter import."""

from .drawio import export_program_drawio
from .ui import (
    BaseWindow,
    DisposedConnectionError,
    UIBindingConflictError,
    UIConnection,
    UIErrorInfo,
    UIErrorPhase,
)

__all__ = [
    "BaseWindow",
    "DisposedConnectionError",
    "TkConnection",
    "TkTraceAdapter",
    "UIBindingConflictError",
    "UIConnection",
    "UIErrorInfo",
    "UIErrorPhase",
    "export_program_drawio",
]


def __getattr__(name: str) -> object:
    if name == "TkTraceAdapter":
        from .tkinter_adapter import TkTraceAdapter

        return TkTraceAdapter
    if name == "TkConnection":
        from .tkinter_connection import TkConnection

        return TkConnection
    raise AttributeError(name)
