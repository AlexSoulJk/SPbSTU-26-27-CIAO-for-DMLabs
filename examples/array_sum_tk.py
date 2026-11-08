"""Tkinter-визуализация пошагового примера суммы массива."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ciao import Runtime
from ciao.visualization import (
    ArrayView,
    CounterView,
    StepController,
    TkTraceAdapter,
    ValueView,
)

try:
    from .test_mock_sample import SumController, build_sample
except ImportError:
    from test_mock_sample import SumController, build_sample


class StatusView(ttk.Label):
    """Демонстрирует подключение собственного виджета без изменения ядра."""

    def show_state(self, state_name: str) -> None:
        self.configure(text=f"Состояние: {state_name}")


def main() -> None:
    values = [2, 4, 6]
    sample = build_sample()
    runtime = Runtime(sample.program)

    root = tk.Tk()
    root.title("CIAO — сумма массива")
    root.columnconfigure(0, weight=1)

    array_view = ArrayView(root)
    array_view.grid(row=0, column=0, padx=12, pady=8)
    total_view = ValueView(root, "Сумма", value=0)
    total_view.grid(row=1, column=0, sticky="w", padx=12)
    index_view = CounterView(root, "Следующий индекс", value=0)
    index_view.grid(row=2, column=0, sticky="w", padx=12)
    tick_view = CounterView(root, "tick", value=0)
    tick_view.grid(row=3, column=0, sticky="w", padx=12)
    status_view = StatusView(root)
    status_view.grid(row=4, column=0, sticky="w", padx=12, pady=(4, 8))

    def render() -> None:
        view = runtime.snapshot(sample.view)
        controller = runtime.snapshot(sample.controller)
        selected = view.index if view.index < len(view.values) else None
        array_view.set_values(view.values or tuple(values), selected_index=selected)
        total_view.set_value(view.total)
        index_view.set_value(view.index)
        tick_view.set_value(view.tick_count)
        status_view.show_state(controller.state.name)
        step_controller.set_enabled(controller.state is not SumController.done)

    def next_tick() -> None:
        if runtime.snapshot(sample.controller).state is SumController.done:
            return
        runtime.send(sample.controller, SumController.tick)
        runtime.run()

    step_controller = StepController(root, next_tick)
    step_controller.grid(row=5, column=0, pady=10)

    # Адаптер обновляет GUI через очередь Tkinter после каждого runtime-события.
    TkTraceAdapter(root, runtime, lambda _event: render())

    runtime.send(sample.controller, SumController.start, values=values)
    runtime.run()
    render()
    root.mainloop()


if __name__ == "__main__":
    main()
