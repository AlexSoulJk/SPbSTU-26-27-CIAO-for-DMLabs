"""Tkinter-визуализация пошагового примера суммы массива."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

# При прямом запуске файла Python добавляет в sys.path только каталог array_sum,
# поэтому корневые пакеты ciao и examples недоступны. Запуск через ``-m`` уже
# содержит корень проекта и в корректировке пути не нуждается.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ciao import Runtime
from ciao.visualization import TkTraceAdapter

from examples.array_sum.automatos import SumController
from examples.array_sum.program import build_sample
from examples.array_sum.ui import ArraySumView


def main() -> None:
    values = [2, 4, 6, 10, -1]
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

    def reset() -> None:
        if runtime.snapshot(sample.controller).state is not SumController.completed:
            return
        runtime.send(sample.controller, SumController.reset)
        runtime.run()

    def finish() -> None:
        if runtime.snapshot(sample.controller).state is not SumController.completed:
            return
        runtime.send(sample.controller, SumController.tick)
        runtime.run()

    sample_view = ArraySumView(
        root,
        on_initialize=initialize,
        on_step=next_tick,
        on_reset=reset,
        on_finish=finish,
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
            show_completed_actions=(
                controller.state is SumController.completed
            ),
        )

    # Адаптер обновляет GUI через очередь Tkinter после каждого runtime-события.
    TkTraceAdapter(root, runtime, lambda _event: render())

    # Первая отрисовка предшествует start, поэтому пользователь видит настоящее
    # начальное состояние idle и сам инициирует переход кнопкой Init.
    render()
    root.mainloop()


if __name__ == "__main__":
    main()
