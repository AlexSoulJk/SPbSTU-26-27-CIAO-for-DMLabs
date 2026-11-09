"""Сборка декларативной программы примера суммы массива."""

from __future__ import annotations

from dataclasses import dataclass

from ciao import AutomatonObject, Connection, Program

from .automatos import SumContext, SumController, SumView, ViewContext


@dataclass(frozen=True)
class Sample:
    """Программа и адресуемые объекты, необходимые сценариям запуска."""

    program: Program
    controller: AutomatonObject
    view: AutomatonObject


def build_sample() -> Sample:
    """Создаёт два объекта и явные соединения их операций."""

    controller = AutomatonObject(
        name="controller",
        automaton=SumController,
        initial_context=SumContext(),
    )
    view = AutomatonObject(
        name="view",
        automaton=SumView,
        initial_context=ViewContext(),
    )

    program = Program(
        objects=(controller, view),
        connections=(
            Connection(
                required=(controller, SumController.draw),
                provided=(view, SumView.draw),
            ),
            Connection(
                required=(view, SumView.draw_completed),
                provided=(controller, SumController.draw_completed),
            ),
        ),
    )
    return Sample(program=program, controller=controller, view=view)


__all__ = ["Sample", "build_sample"]
