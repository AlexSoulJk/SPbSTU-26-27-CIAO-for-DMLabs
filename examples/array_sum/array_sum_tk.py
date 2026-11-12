"""Tkinter-запуск интерактивного сценария ArraySum через CIAO bindings."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ciao import FactoryPayloadSource, Runtime
from ciao.visualization.tkinter_connection import TkConnection

from examples.array_sum.interactive import (
    InteractiveSample,
    InteractiveSumView,
    StartInput,
    build_interactive_sample,
)
from examples.array_sum.interactive.window import ArraySumWindow


def _bind_window(
    root: tk.Misc,
    runtime: Runtime,
    sample: InteractiveSample,
    window: ArraySumWindow,
) -> TkConnection:
    """Создаёт все UI-привязки одной конфигурации запуска примера."""

    connection = TkConnection(root, runtime, window)
    connection.bind_event(
        window.init_button,
        (sample.view, InteractiveSumView.init_clicked),
        payload_source=FactoryPayloadSource(StartInput, window.read_start_input),
    )
    connection.bind_event(
        window.next_button,
        (sample.view, InteractiveSumView.next_clicked),
    )
    connection.bind_event(
        window.reset_button,
        (sample.view, InteractiveSumView.reset_clicked),
    )
    connection.bind_event(
        window.finish_button,
        (sample.view, InteractiveSumView.finish_clicked),
    )
    connection.bind_command(
        (sample.view, InteractiveSumView.render_data),
        window.render_data,
    )
    connection.bind_command(
        (sample.view, InteractiveSumView.render_controls),
        window.render_controls,
    )
    connection.bind_command(
        (sample.view, InteractiveSumView.render_status),
        window.render_status,
    )
    return connection


def main() -> None:
    sample = build_interactive_sample()
    runtime = Runtime(sample.program)

    root = tk.Tk()
    root.title("CIAO — сумма массива")
    root.columnconfigure(0, weight=1)
    window = ArraySumWindow(root)
    window.grid(row=0, column=0, sticky="nsew")

    # Подключение владеет только привязками. Window не получает Runtime и не
    # читает снимки автоматов: состояние UI приходит командами самого View.
    _bind_window(root, runtime, sample, window)

    root.mainloop()


if __name__ == "__main__":
    main()
