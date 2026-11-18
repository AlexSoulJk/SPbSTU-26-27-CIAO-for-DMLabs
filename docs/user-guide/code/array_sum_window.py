
import tkinter as tk
from tkinter import ttk


class SumWindow(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, padding=12)

        self.values_entry = ttk.Entry(self)
        self.values_entry.insert(0, "1, 2, 3")
        self.values_entry.pack()

        self.start_button = ttk.Button(self, text="Старт")
        self.start_button.pack()

        self.next_button = ttk.Button(self, text="Следующий шаг")
        self.next_button.pack()

        self.total_label = ttk.Label(self, text="Сумма: 0")
        self.total_label.pack()

    def read_values(self) -> list[int]:
        return [
            int(value.strip())
            for value in self.values_entry.get().split(",")
            if value.strip()
        ]

    def render_data(self, total: int) -> None:
        self.total_label.configure(text=f"Сумма: {total}")

    def render_controls(self, can_step: bool) -> None:
        self.next_button.configure(
            state="normal" if can_step else "disabled"
        )
