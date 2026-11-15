from dataclasses import dataclass
from ciao import (
    AutomatonContext,
    State,
    ControllerAutomaton,
    action,
    provided_command,
    transition, guard,
    required_command, required_query,
    Emits,
    Query,
    Emit
)

@dataclass
class ElevatorControllerContext(AutomatonContext):
    """No local data needed: occupancy is obtained via a required query."""
    pass


class ElevatorController(ControllerAutomaton[ElevatorControllerContext]):
    """CIAO v.3 Controller from Listing 1."""

    Idle = State(initial=True)
    I2B = State()
    Busy = State()
    B2I = State()

    # Public events. `in_` is used because `in` is a Python keyword.
    @provided_command(external=True)
    def try_in(self) -> None:
        pass

    @provided_command(external=True)
    def out(self) -> None:
        pass

    @provided_command(external=True)
    def enter(self) -> None:
        pass

    @provided_command(external=True)
    def exit(self) -> None:
        pass

    # Adaptation of CIAO after(t1) / after(t2):
    # the scheduler sends these events after the respective delay.
    @provided_command
    def t1_expired(self) -> None:
        pass

    @provided_command
    def t2_expired(self) -> None:
        pass

    # Required commands: connected externally to Device.on / Device.off.
    @required_command
    def open_door(self) -> None:
        pass

    @required_command
    def close_door(self) -> None:
        pass

    @required_command
    def switch_on(self) -> None:
        pass

    @required_command
    def switch_off(self) -> None:
        pass

    @required_command
    def occupy(self) -> None:
        pass

    @required_command
    def free(self) -> None:
        pass

    @required_query
    def occupied(self) -> bool:
        raise NotImplementedError

    @guard(query=occupied)
    def is_occupied(self, ctx: ElevatorControllerContext, query: Query) -> bool:
        return query()

    @guard(query=occupied)
    def is_empty(self, ctx: ElevatorControllerContext, query: Query) -> bool:
        return not query()

    @action(emits=(switch_on, open_door))
    def invite(self, ctx: ElevatorControllerContext, emits: Emits) -> None:
        emits[self.switch_on]()
        emits[self.open_door]()

    @action(emits=(close_door, switch_off))
    def cancel_invitation(self, ctx: ElevatorControllerContext, emits: Emits) -> None:
        emits[self.close_door]()
        emits[self.switch_off]()

    @action(emits=(close_door, occupy))
    def passenger_entered(self, ctx: ElevatorControllerContext, emits: Emits) -> None:
        emits[self.close_door]()
        emits[self.occupy]()

    @action(emit=open_door)
    def invite_to_exit(self, ctx: ElevatorControllerContext, emit: Emit) -> None:
        emit()

    @action(emit=close_door)
    def cancel_exit(self, ctx: ElevatorControllerContext, emit: Emit) -> None:
        emit()

    @action(emits=(close_door, switch_off, free))
    def passenger_exited(self, ctx: ElevatorControllerContext, emits: Emits) -> None:
        emits[self.close_door]()
        emits[self.switch_off]()
        emits[self.free]()

    # Exact behavioral topology of Listing 1.
    reject_occupied_entry = transition(
        source=Idle,
        event=try_in,
        guard=is_occupied,
        target=Idle,
        )

    invite_passenger = transition(
        source=Idle,
        event=try_in,
        otherwise=True,
        actions=(invite,),
        target=I2B,
    )

    entry_timeout = transition(
        source=I2B,
        event=t1_expired,
        actions=(cancel_invitation,),
        target=Idle,
    )

    passenger_enters = transition(
        source=I2B,
        event=enter,
        actions=(passenger_entered,),
        target=Busy,
    )

    request_exit = transition(
        source=Busy,
        event=out,
        actions=(invite_to_exit,),
        target=B2I,
    )

    exit_timeout = transition(
        source=B2I,
        event=t2_expired,
        actions=(cancel_exit,),
        target=Busy,
    )

    passenger_exits = transition(
        source=B2I,
        event=exit,
        actions=(passenger_exited,),
        target=Idle,
    )