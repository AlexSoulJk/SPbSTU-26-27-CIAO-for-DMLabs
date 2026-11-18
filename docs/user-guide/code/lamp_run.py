from ciao.infrastructure.errors import NoTransitionError
from lamp import Lamp, build_program
from ciao import (
    Runtime,
)

def main() -> None:
    program, lamp = build_program()
    runtime = Runtime(program)

    snapshot_init = runtime.snapshot(lamp)

    assert snapshot_init.state is Lamp.off
    assert snapshot_init.context.switch_on_count == 0
    
    runtime.send(lamp, Lamp.switch_on)
    result = runtime.step()
    snapshot_after_switch_on = runtime.snapshot(lamp)

    assert result.transition == "turn_on"
    assert snapshot_after_switch_on.state is Lamp.on
    assert snapshot_after_switch_on.context.switch_on_count == 1

    runtime.send(lamp, Lamp.switch_off)
    runtime.run()

    snapshot_after_switch_off = runtime.snapshot(lamp)

    assert snapshot_after_switch_off.state is Lamp.off
    assert snapshot_after_switch_off.context.switch_on_count == 1

    try:
        runtime.send(lamp, Lamp.switch_off)
        runtime.run()
    except NoTransitionError as e:
        print(e)

if __name__ == "__main__":
    main()
