"""Конкретное Tkinter-представление учебного примера суммы массива."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any


class _ArrayView(ttk.Frame):
    """Отображает массив и выделяет текущий элемент примера."""

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
        selected_index: int | None,
    ) -> None:
        for label in self._labels:
            label.destroy()
        self._labels.clear()

        for index, value in enumerate(tuple(values)):
            options: dict[str, Any] = {}
            if selected_index == index:
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


class _ValueView(ttk.Frame):
    """Показывает одно именованное значение примера."""

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
        self._value.set(str(value))


class _ScheduledButton(ttk.Button):
    """Не допускает повторного вызова действия до завершения callback."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        command: Callable[[], None],
    ) -> None:
        self._command = command
        self._scheduled = False
        self._enabled = True
        super().__init__(master, text=text, command=self._schedule)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.state(["!disabled"] if enabled else ["disabled"])

    def _schedule(self) -> None:
        if self._scheduled or not self._enabled:
            return
        self._scheduled = True
        self.state(["disabled"])
        self.after(0, self._perform)

    def _perform(self) -> None:
        try:
            self._command()
        finally:
            self._scheduled = False
            self.state(["!disabled"] if self._enabled else ["disabled"])


class ArraySumView(ttk.Frame):
    """Составное представление и органы управления примером суммы массива."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_initialize: Callable[[], None],
        on_step: Callable[[], None],
        on_reset: Callable[[], None],
        on_finish: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)

        self._array = _ArrayView(self)
        self._array.grid(row=0, column=0, padx=12, pady=8)
        self._total = _ValueView(self, "Сумма", value=0)
        self._total.grid(row=1, column=0, sticky="w", padx=12)
        self._index = _ValueView(self, "Следующий индекс", value=0)
        self._index.grid(row=2, column=0, sticky="w", padx=12)
        self._ticks = _ValueView(self, "tick", value=0)
        self._ticks.grid(row=3, column=0, sticky="w", padx=12)
        self._state = ttk.Label(self)
        self._state.grid(row=4, column=0, sticky="w", padx=12, pady=(4, 8))

        self._controls = ttk.Frame(self)
        self._controls.grid(row=5, column=0, pady=10)
        self._initialize = _ScheduledButton(
            self._controls,
            text="Init",
            command=on_initialize,
        )
        self._initialize.grid(row=0, column=0, padx=4)
        self._step = _ScheduledButton(
            self._controls,
            text="Следующий шаг",
            command=on_step,
        )
        self._step.grid(row=0, column=0, padx=4)
        self._step.grid_remove()
        self._reset = _ScheduledButton(
            self._controls,
            text="Reset",
            command=on_reset,
        )
        self._reset.grid(row=0, column=0, padx=4)
        self._reset.grid_remove()
        self._finish = _ScheduledButton(
            self._controls,
            text="Finish",
            command=on_finish,
        )
        self._finish.grid(row=0, column=1, padx=4)
        self._finish.grid_remove()

    def render(
        self,
        *,
        values: Sequence[Any],
        selected_index: int | None,
        total: int,
        index: int,
        tick_count: int,
        state_name: str,
        show_initialize: bool,
        step_enabled: bool,
        show_completed_actions: bool,
    ) -> None:
        """Обновляет данные и выбирает органы управления по состоянию автомата."""

        self._array.set_values(values, selected_index=selected_index)
        self._total.set_value(total)
        self._index.set_value(index)
        self._ticks.set_value(tick_count)
        self._state.configure(text=f"Состояние: {state_name}")

        for button in (
            self._initialize,
            self._step,
            self._reset,
            self._finish,
        ):
            button.set_enabled(False)
            button.grid_remove()

        # В completed пользователь явно выбирает возврат к idle или отдельный
        # завершающий tick, который переводит автомат в терминальный Exit.
        if show_initialize:
            self._initialize.grid()
            self._initialize.set_enabled(True)
        elif show_completed_actions:
            self._reset.grid()
            self._finish.grid()
            self._reset.set_enabled(True)
            self._finish.set_enabled(True)
        else:
            self._step.grid()
            self._step.set_enabled(step_enabled)


__all__ = ["ArraySumView"]
