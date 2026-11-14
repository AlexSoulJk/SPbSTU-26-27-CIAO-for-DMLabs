"""Tkinter Window пошагового калькулятора без доступа к Runtime."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from ciao.visualization import BaseWindow, UIErrorInfo

from ..contracts import (
    CalculationPhase,
    ControlsPresentation,
    DataPresentation,
    StartInput,
    StatusPresentation,
)

INITIAL_EXPRESSION = "3 + 4 * (2 - 1)"


@dataclass(frozen=True, slots=True)
class _InitialWindowConfig:
    data: DataPresentation
    controls: ControlsPresentation
    status: StatusPresentation


_INITIAL_WINDOW_CONFIG = _InitialWindowConfig(
    data=DataPresentation(
        INITIAL_EXPRESSION,
        CalculationPhase.IDLE,
        None,
        (),
        (),
        None,
    ),
    controls=ControlsPresentation(True, True, False, False, False, False),
    status=StatusPresentation("Введите выражение и начните вычисление"),
)

_PHASE_LABELS = {
    CalculationPhase.IDLE: "ожидание",
    CalculationPhase.CONVERTING: "преобразование в ОПН",
    CalculationPhase.EVALUATING: "вычисление ОПН",
    CalculationPhase.COMPLETED: "завершено",
}


class _CalculatorDataControl(ttk.Frame):
    """Отображает одно типизированное представление калькулятора."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self._expression = ttk.Label(self, anchor="w")
        self._phase = ttk.Label(self, anchor="w")
        self._token = ttk.Label(self, anchor="w")
        self._rpn = ttk.Label(self, anchor="w")
        self._stack = ttk.Label(self, anchor="w")
        self._result = ttk.Label(self, anchor="w")
        for row, label in enumerate(
            (
                self._expression,
                self._phase,
                self._token,
                self._rpn,
                self._stack,
                self._result,
            )
        ):
            label.grid(row=row, column=0, sticky="w", pady=2)

    def render(self, presentation: DataPresentation) -> None:
        """Обновляет все связанные поля из одного immutable DTO."""

        token = presentation.current_token or "—"
        rpn = " ".join(presentation.rpn) or "—"
        stack = ", ".join(map(str, presentation.stack)) or "—"
        result = "—" if presentation.result is None else str(presentation.result)
        self._expression.configure(text=f"Выражение: {presentation.expression}")
        self._phase.configure(
            text=f"Фаза: {_PHASE_LABELS[presentation.phase]}"
        )
        self._token.configure(text=f"Текущий токен: {token}")
        self._rpn.configure(text=f"ОПН: {rpn}")
        self._stack.configure(text=f"Стек: {stack}")
        self._result.configure(text=f"Результат: {result}")


class CalculatorWindow(ttk.Frame, BaseWindow):
    """Предоставляет UI-события и отображает presentation-команды View."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=12)
        self.columnconfigure(0, weight=1)
        self._build_input_section(_INITIAL_WINDOW_CONFIG.data.expression)
        self._build_presentation_section()
        self._build_action_section()
        self._apply_initial_config(_INITIAL_WINDOW_CONFIG)

    def _build_input_section(self, expression: str) -> None:
        input_frame = ttk.Frame(self)
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)
        ttk.Label(input_frame, text="Выражение:").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self._expression = tk.StringVar(master=self, value=expression)
        self.expression_entry = ttk.Entry(
            input_frame,
            textvariable=self._expression,
        )
        self.expression_entry.grid(row=0, column=1, padx=(8, 0), sticky="ew")

    def _build_presentation_section(self) -> None:
        self._data_control = _CalculatorDataControl(self)
        self._data_control.grid(row=1, column=0, pady=(16, 4), sticky="ew")
        self._status = ttk.Label(self)
        self._status.grid(row=2, column=0, pady=8)

    def _build_action_section(self) -> None:
        controls = ttk.Frame(self)
        controls.grid(row=3, column=0, pady=(4, 0))
        self.start_button = ttk.Button(controls, text="Начать")
        self.next_button = ttk.Button(controls, text="Следующий шаг")
        self.reset_button = ttk.Button(controls, text="Сброс")
        self.finish_button = ttk.Button(controls, text="Завершить")
        for column, button in enumerate(
            (
                self.start_button,
                self.next_button,
                self.reset_button,
                self.finish_button,
            )
        ):
            button.grid(row=0, column=column, padx=4)

    def _apply_initial_config(self, config: _InitialWindowConfig) -> None:
        self.render_data(config.data)
        self.render_controls(config.controls)
        self.render_status(config.status)

    def read_start_input(self) -> StartInput:
        expression = self._expression.get().strip()
        if not expression:
            raise ValueError("Пустое выражение")
        return StartInput(expression)

    def render_data(self, presentation: DataPresentation) -> None:
        self._data_control.render(presentation)

    def render_controls(self, presentation: ControlsPresentation) -> None:
        self._set_button(self.start_button, presentation.show_start, True)
        self._set_button(
            self.next_button,
            presentation.show_next,
            presentation.next_enabled,
        )
        self._set_button(self.reset_button, presentation.show_reset, True)
        self._set_button(self.finish_button, presentation.show_finish, True)
        self.expression_entry.configure(
            state="normal" if presentation.input_enabled else "disabled"
        )

    def render_status(self, presentation: StatusPresentation) -> None:
        self._status.configure(text=presentation.text)

    def show_error(self, error: UIErrorInfo) -> None:
        messagebox.showerror(error.title, error.message, parent=self)

    @staticmethod
    def _set_button(button: ttk.Button, visible: bool, enabled: bool) -> None:
        if visible:
            button.grid()
        else:
            button.grid_remove()
        button.state(["!disabled"] if enabled else ["disabled"])


__all__ = ["CalculatorWindow"]
