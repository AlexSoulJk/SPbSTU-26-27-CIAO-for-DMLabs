"""Снимок сборки программы Array Sum для главы 4."""

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program
from examples.array_sum.automatos import SumContext, SumController, SumView, ViewContext


@dataclass(frozen=True)
class Sample:
    program: Program
    controller: AutomatonObject
    view: AutomatonObject


def build_sample() -> Sample:
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

