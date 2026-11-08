"""Tkinter-визуализация пошагового примера суммы массива."""

from __future__ import annotations

import tkinter as tk

from ciao import Runtime
from ciao.visualization import TkTraceAdapter
from ciao.visualization.array_sample import ArraySumView

try:
    from .test_mock_sample import SumController, build_sample
except ImportError:
    from test_mock_sample import SumController, build_sample


def main() -> None:
    values = [2, 4, 6]
    sample = build_sample()
    runtime = Runtime(sample.program)

    root = tk.Tk()
    root.title("CIAO — сумма массива")
    root.columnconfigure(0, weight=1)

    def initialize() -> None:
        if runtime.snapshot(sample.controller).state is not SumController.idle:
            return
        runtime.send(sample.controller, SumController.start, values=values)
        runtime.run()

    def next_tick() -> None:
        if runtime.snapshot(sample.controller).state is not SumController.running:
            return
        runtime.send(sample.controller, SumController.tick)
        runtime.run()

    sample_view = ArraySumView(
        root,
        on_initialize=initialize,
        on_step=next_tick,
    )
    sample_view.grid(row=0, column=0, sticky="nsew")

    def render() -> None:
        view = runtime.snapshot(sample.view)
        controller = runtime.snapshot(sample.controller)
        shown_values = view.values or tuple(values)
        initialized = controller.state is not SumController.idle
        selected = (
            view.index
            if initialized and view.index < len(shown_values)
            else None
        )
        sample_view.render(
            values=shown_values,
            selected_index=selected,
            total=view.total,
            index=view.index,
            tick_count=view.tick_count,
            state_name=controller.state.name,
            show_initialize=not initialized,
            step_enabled=controller.state is SumController.running,
        )

    # Адаптер обновляет GUI через очередь Tkinter после каждого runtime-события.
    TkTraceAdapter(root, runtime, lambda _event: render())

    # Первая отрисовка предшествует start, поэтому пользователь видит настоящее
    # начальное состояние idle и сам инициирует переход кнопкой Init.
    render()
    root.mainloop()


if __name__ == "__main__":
    main()
