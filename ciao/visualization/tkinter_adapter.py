"""Общий адаптер между событиями runtime и циклом Tkinter."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from ciao.infrastructure.runtime import Runtime, TraceEvent


class TkTraceAdapter:
    """Переносит события runtime в очередь событий Tkinter через ``after``."""

    def __init__(
        self,
        master: tk.Misc,
        runtime: Runtime,
        handler: Callable[[TraceEvent], None],
    ) -> None:
        self._master = master
        self._handler = handler
        runtime.subscribe(self._on_trace)

    def _on_trace(self, event: TraceEvent) -> None:
        self._master.after(0, self._handler, event)
