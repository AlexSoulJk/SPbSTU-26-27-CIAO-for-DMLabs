"""Фрагмент конфигурации TkConnection для главы 7."""

import tkinter as tk

from ciao import FactoryPayloadSource, Runtime
from ciao.visualization.tkinter_connection import TkConnection
from examples.array_sum import Sample, StartInput, SumView
from examples.array_sum.ui import ArraySumWindow


def bind_window(
    root: tk.Misc,
    runtime: Runtime,
    sample: Sample,
    window: ArraySumWindow,
) -> TkConnection:
    connection = TkConnection(root, runtime, window)
    connection.bind_event(
        window.init_button,
        (sample.view, SumView.init_clicked),
        payload_source=FactoryPayloadSource(StartInput, window.read_start_input),
    )
    connection.bind_event(window.next_button, (sample.view, SumView.next_clicked))
    connection.bind_command((sample.view, SumView.render_data), window.render_data)
    connection.bind_command(
        (sample.view, SumView.render_controls),
        window.render_controls,
    )
    connection.bind_command(
        (sample.view, SumView.render_status),
        window.render_status,
    )
    return connection

