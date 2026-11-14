"""Tkinter-запуск калькулятора через CIAO UI bindings."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ciao import FactoryPayloadSource, Runtime
from ciao.visualization.tkinter_connection import TkConnection

from examples.calculator import CalculatorView, Sample, StartInput, build_sample
from examples.calculator.ui import CalculatorWindow


def _bind_window(
    root: tk.Misc,
    runtime: Runtime,
    sample: Sample,
    window: CalculatorWindow,
) -> TkConnection:
    """Связывает Window только с external-операциями CalculatorView."""

    connection = TkConnection(root, runtime, window)
    connection.bind_event(
        window.start_button,
        (sample.view, CalculatorView.start_clicked),
        payload_source=FactoryPayloadSource(StartInput, window.read_start_input),
    )
    connection.bind_event(
        window.next_button,
        (sample.view, CalculatorView.next_clicked),
    )
    connection.bind_event(
        window.reset_button,
        (sample.view, CalculatorView.reset_clicked),
    )
    connection.bind_event(
        window.finish_button,
        (sample.view, CalculatorView.finish_clicked),
    )
    connection.bind_command(
        (sample.view, CalculatorView.render_data),
        window.render_data,
    )
    connection.bind_command(
        (sample.view, CalculatorView.render_controls),
        window.render_controls,
    )
    connection.bind_command(
        (sample.view, CalculatorView.render_status),
        window.render_status,
    )
    return connection


def main() -> None:
    sample = build_sample()
    runtime = Runtime(sample.program)
    root = tk.Tk()
    root.title("CIAO — пошаговый калькулятор")
    root.columnconfigure(0, weight=1)
    window = CalculatorWindow(root)
    window.grid(row=0, column=0, sticky="nsew")
    _bind_window(root, runtime, sample, window)
    root.mainloop()


if __name__ == "__main__":
    main()
