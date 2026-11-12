"""Сборка программы учебного примера суммы массива."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program

from .automatos import SumContext, SumController, SumView, ViewContext


@dataclass(frozen=True)
class Sample:
    program: Program
    controller: AutomatonObject
    view: AutomatonObject


def build_sample() -> Sample:
    """Создаёт Controller/View, включая self-connection автоматического режима."""

    controller = AutomatonObject("controller", SumController, SumContext())
    view = AutomatonObject("view", SumView, ViewContext())
    program = Program(
        objects=(controller, view),
        connections=(
            Connection((view, SumView.start), (controller, SumController.start)),
            Connection((view, SumView.tick), (controller, SumController.tick)),
            Connection((view, SumView.reset), (controller, SumController.reset)),
            Connection((view, SumView.finish), (controller, SumController.finish)),
            Connection((controller, SumController.draw), (view, SumView.draw)),
            Connection(
                (view, SumView.draw_completed),
                (controller, SumController.draw_completed),
            ),
            Connection(
                (controller, SumController.continue_run),
                (controller, SumController.tick),
            ),
        ),
    )
    return Sample(program, controller, view)


__all__ = ["Sample", "build_sample"]
