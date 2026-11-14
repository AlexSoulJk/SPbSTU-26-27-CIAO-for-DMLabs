"""Tkinter Window примера суммы массива без доступа к Runtime."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from ciao.visualization import BaseWindow, UIErrorInfo

from ..contracts import (
    CalculationMode,
    ControlsPresentation,
    DataPresentation,
    StartInput,
    StatusPresentation,
)

INITIAL_VALUES = (2, 4, 6, 10, -1)


@dataclass(frozen=True, slots=True)
class _InitialWindowConfig:
    """Начальные presentation-объекты, принадлежащие только слою UI."""

    data: DataPresentation
    controls: ControlsPresentation
    status: StatusPresentation


_INITIAL_WINDOW_CONFIG = _InitialWindowConfig(
    data=DataPresentation(INITIAL_VALUES, None, 0, 0, 0),
    controls=ControlsPresentation(True, True, False, False, False, False),
    status=StatusPresentation("Введите массив и выберите режим"),
)


class _SumDataControl(ttk.Frame):
    """Единственное место преобразования DataPresentation в Tk-текст."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._array = ttk.Label(self)
        self._array.grid(row=0, column=0, pady=(0, 4))
        self._details = ttk.Label(self)
        self._details.grid(row=1, column=0)

    def render(self, presentation: DataPresentation) -> None:
        """Атомарно обновляет связанные данные и детали вычисления."""

        rendered = [
            f"[{value}]" if index == presentation.selected_index else str(value)
            for index, value in enumerate(presentation.values)
        ]
        self._array.configure(text="[" + ", ".join(rendered) + "]")
        self._details.configure(
            text=(
                f"Сумма: {presentation.total}; индекс: {presentation.index}; "
                f"tick: {presentation.tick_count}"
            )
        )


class ArraySumWindow(ttk.Frame, BaseWindow):
    """Отображает presentation-DTO и предоставляет чистые источники событий."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=12)
        self.columnconfigure(0, weight=1)

        self._build_input_section(_INITIAL_WINDOW_CONFIG.data.values)
        self._build_presentation_section()
        self._build_action_section()
        self._apply_initial_config(_INITIAL_WINDOW_CONFIG)

    def _build_input_section(self, values: tuple[int, ...]) -> None:
        """Создаёт поля, из которых формируется StartInput."""

        input_frame = ttk.Frame(self)
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)
        ttk.Label(input_frame, text="Массив:").grid(row=0, column=0, sticky="w")
        self._values = tk.StringVar(
            master=self,
            value=", ".join(map(str, values)),
        )
        self.values_entry = ttk.Entry(input_frame, textvariable=self._values)
        self.values_entry.grid(row=0, column=1, padx=8, sticky="ew")

        ttk.Label(input_frame, text="Режим:").grid(row=1, column=0, sticky="w")
        self._mode = tk.StringVar(
            master=self,
            value=CalculationMode.STEP_BY_STEP.value,
        )
        self.mode_box = ttk.Combobox(
            input_frame,
            state="readonly",
            textvariable=self._mode,
            values=tuple(mode.value for mode in CalculationMode),
        )
        self.mode_box.grid(row=1, column=1, padx=8, pady=(6, 0), sticky="ew")

    def _build_presentation_section(self) -> None:
        """Создаёт контролы, содержимое которых приходит из render-методов."""

        self._data_control = _SumDataControl(self)
        self._data_control.grid(row=1, column=0, pady=(16, 0))
        self._status = ttk.Label(self)
        self._status.grid(row=2, column=0, pady=8)

    def _build_action_section(self) -> None:
        """Создаёт источники внешних команд View-автомата."""

        controls = ttk.Frame(self)
        controls.grid(row=3, column=0, pady=(4, 0))
        self.init_button = ttk.Button(controls, text="Начать")
        self.next_button = ttk.Button(controls, text="Следующий шаг")
        self.reset_button = ttk.Button(controls, text="Сброс")
        self.finish_button = ttk.Button(controls, text="Завершить")
        for column, button in enumerate(
            (
                self.init_button,
                self.next_button,
                self.reset_button,
                self.finish_button,
            )
        ):
            button.grid(row=0, column=column, padx=4)

    def _apply_initial_config(self, config: _InitialWindowConfig) -> None:
        """Инициализирует окно через те же каналы, что и команды View."""

        self.render_data(config.data)
        self.render_controls(config.controls)
        self.render_status(config.status)

    def read_start_input(self) -> StartInput:
        """Снимает актуальные значения виджетов ровно в момент UI-события."""

        tokens = self._values.get().replace(",", " ").split()
        return StartInput(
            values=tuple(int(token) for token in tokens),
            mode=CalculationMode(self._mode.get()),
        )

    def render_data(self, presentation: DataPresentation) -> None:
        self._data_control.render(presentation)

    def render_controls(self, presentation: ControlsPresentation) -> None:
        self._set_button(self.init_button, presentation.show_init, True)
        self._set_button(
            self.next_button,
            presentation.show_next,
            presentation.next_enabled,
        )
        self._set_button(self.reset_button, presentation.show_reset, True)
        self._set_button(self.finish_button, presentation.show_finish, True)
        self.values_entry.configure(
            state="normal" if presentation.mode_enabled else "disabled"
        )
        self.mode_box.configure(
            state="readonly" if presentation.mode_enabled else "disabled"
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


__all__ = ["ArraySumWindow"]
