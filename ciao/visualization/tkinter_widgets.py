"""Небольшие Tkinter-виджеты и адаптеры для учебных примеров."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any
from tkinter import ttk

from ciao.infrastructure.runtime import Runtime, TraceEvent


class ArrayView(ttk.Frame):
    """Отображает последовательность значений и выделенный элемент."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        highlight_color: str = "#ffd966",
        padding: int = 4,
    ) -> None:
        super().__init__(master)
        self._highlight_color = highlight_color
        self._padding = padding
        self._labels: list[tk.Label] = []

    def set_values(
        self,
        values: Sequence[Any],
        *,
        selected_index: int | None = None,
    ) -> None:
        """Перерисовывает значения, не сохраняя ссылку на исходную коллекцию."""

        for label in self._labels:
            label.destroy()
        self._labels.clear()

        for index, value in enumerate(tuple(values)):
            options: dict[str, Any] = {}
            if selected_index is not None and index == selected_index:
                options["background"] = self._highlight_color
            label = tk.Label(
                self,
                text=str(value),
                relief="solid",
                borderwidth=1,
                padx=self._padding,
                pady=self._padding,
                **options,
            )
            label.grid(row=0, column=index, padx=2)
            self._labels.append(label)


class ValueView(ttk.Frame):
    """Показывает заголовок и одно обновляемое значение."""

    def __init__(self, master: tk.Misc, title: str, *, value: Any = "—") -> None:
        super().__init__(master)
        self._value = tk.StringVar(master=self, value=str(value))
        ttk.Label(self, text=f"{title}:").grid(row=0, column=0, sticky="w")
        ttk.Label(self, textvariable=self._value).grid(
            row=0,
            column=1,
            padx=(6, 0),
            sticky="w",
        )

    def set_value(self, value: Any) -> None:
        """Обновляет отображаемое значение."""

        self._value.set(str(value))


class CounterView(ValueView):
    """Специализированное отображение целочисленного счётчика."""

    def __init__(self, master: tk.Misc, title: str, *, value: int = 0) -> None:
        super().__init__(master, title, value=value)

    def set_value(self, value: int) -> None:
        if not isinstance(value, int):
            raise TypeError("CounterView принимает только int")
        super().set_value(value)


class StepController(ttk.Frame):
    """Кнопка, планирующая один пользовательский шаг через ``after``."""

    def __init__(
        self,
        master: tk.Misc,
        on_step: Callable[[], None],
        *,
        text: str = "Следующий шаг",
    ) -> None:
        super().__init__(master)
        self._on_step = on_step
        self._scheduled = False
        self._enabled = True
        self.button = ttk.Button(self, text=text, command=self.schedule_step)
        self.button.pack()

    def schedule_step(self) -> None:
        """Не допускает повторного запуска до завершения текущего callback."""

        if self._scheduled:
            return
        self._scheduled = True
        self.button.state(["disabled"])
        self.after(0, self._perform_step)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.button.state(["!disabled"] if enabled else ["disabled"])

    def _perform_step(self) -> None:
        try:
            self._on_step()
        finally:
            self._scheduled = False
            self.button.state(["!disabled"] if self._enabled else ["disabled"])


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
