from dataclasses import dataclass

from ciao import (
    AutomatonContext,
    State,
    ControllerAutomaton,
    action,
    provided_command,
    provided_query,
    transition,
)


@dataclass
class DeviceContext(AutomatonContext):
    enabled: bool = False



class Device(ControllerAutomaton[DeviceContext]):
    """Reusable two-state automaton for light, door or occupancy."""

    Off = State(initial=True)
    On = State()

    @provided_command
    def on(self) -> None:
        pass

    @provided_command
    def off(self) -> None:
        pass

    @provided_query
    def is_on(self, ctx: DeviceContext) -> bool:
        return ctx.enabled

    @action
    def enable(self, ctx: DeviceContext) -> None:
        ctx.enabled = True

    @action
    def disable(self, ctx: DeviceContext) -> None:
        ctx.enabled = False

    off_to_on = transition(
        source=Off,
        event=on,
        actions=(enable,),
        target=On,
    )

    off_to_off = transition(
        source=Off,
        event=off,
        actions=(disable,),
        target=Off,
    )

    on_to_on = transition(
        source=On,
        event=on,
        actions=(enable,),
        target=On,
    )

    on_to_off = transition(
        source=On,
        event=off,
        actions=(disable,),
        target=Off,
    )