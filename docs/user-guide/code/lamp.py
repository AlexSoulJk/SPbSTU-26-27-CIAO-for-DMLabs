from __future__ import annotations

from dataclasses import dataclass

from ciao import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Program,
    State,
    action,
    provided_command,
    transition,
)


@dataclass
class LampContext(AutomatonContext):
    switch_on_count: int = 0


class Lamp(Automaton[LampContext]):
    off = State(initial=True)
    on = State()

    @provided_command(external=True)
    def switch_on(self) -> None: ...

    @provided_command(external=True)
    def switch_off(self) -> None: ...

    @action(text="Увеличивает счетчик включения")
    def increment_switch_on_count(self, ctx: LampContext) -> None:
        ctx.switch_on_count += 1

    turn_on = transition(
        source=off,
        event=switch_on,
        actions=(increment_switch_on_count,),
        target=on,
    )
    turn_off = transition(
        source=on,
        event=switch_off,
        target=off,
    )

def build_program() -> tuple[Program, AutomatonObject]:
    lamp = AutomatonObject("lamp", Lamp, LampContext())
    return Program(objects=(lamp,)), lamp