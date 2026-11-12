"""Сборка интерактивной программы ArraySum без зависимости от Tkinter."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program

from .controller import InteractiveSumContext, InteractiveSumController
from .view import InteractiveSumView, InteractiveViewContext


@dataclass(frozen=True)
class InteractiveSample:
    program: Program
    controller: AutomatonObject
    view: AutomatonObject


def build_interactive_sample() -> InteractiveSample:
    """Создаёт Controller/View, включая self-connection автоматического режима."""

    controller = AutomatonObject(
        "interactive_controller", InteractiveSumController, InteractiveSumContext(),
    )
    view = AutomatonObject(
        "interactive_view", InteractiveSumView, InteractiveViewContext(),
    )
    program = Program(
        objects=(controller, view),
        connections=(
            Connection(
                (view, InteractiveSumView.start),
                (controller, InteractiveSumController.start),
            ),
            Connection(
                (view, InteractiveSumView.tick),
                (controller, InteractiveSumController.tick),
            ),
            Connection(
                (view, InteractiveSumView.reset),
                (controller, InteractiveSumController.reset),
            ),
            Connection(
                (view, InteractiveSumView.finish),
                (controller, InteractiveSumController.finish),
            ),
            Connection(
                (controller, InteractiveSumController.draw),
                (view, InteractiveSumView.draw),
            ),
            Connection(
                (view, InteractiveSumView.draw_completed),
                (controller, InteractiveSumController.draw_completed),
            ),
            Connection(
                (controller, InteractiveSumController.continue_run),
                (controller, InteractiveSumController.tick),
            ),
        ),
    )
    return InteractiveSample(program, controller, view)


__all__ = ["InteractiveSample", "build_interactive_sample"]
