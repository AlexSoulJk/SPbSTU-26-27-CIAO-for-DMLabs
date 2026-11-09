"""Headless-пример синхронного Query между двумя автоматными объектами."""

from dataclasses import dataclass

from ciao import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Connection,
    ControllerAutomaton,
    Program,
    Queries,
    Runtime,
    State,
    guard,
    provided_command,
    provided_query,
    required_query,
    transition,
)


@dataclass
class SensorContext(AutomatonContext):
    value: int
    ready: bool = True


class Sensor(Automaton[SensorContext]):
    idle = State(initial=True)

    @provided_query
    def get_value(self, ctx: SensorContext) -> int:
        return ctx.value

    @provided_query
    def is_ready(self, ctx: SensorContext) -> bool:
        return ctx.ready


@dataclass
class ControllerContext(AutomatonContext):
    threshold: int


class Controller(ControllerAutomaton[ControllerContext]):
    waiting = State(initial=True)
    accepted = State(final=True)
    rejected = State(final=True)

    @provided_command(external=True)
    def check(self) -> None:
        ...

    @required_query(text="получить текущее значение")
    def sensor_value(self) -> int:
        ...

    @required_query(text="проверить готовность датчика")
    def sensor_ready(self) -> bool:
        ...

    @guard(
        queries=(sensor_value, sensor_ready),
        text="датчик готов и значение достигло порога",
    )
    def can_accept(
        self,
        ctx: ControllerContext,
        queries: Queries,
    ) -> bool:
        return (
            queries[self.sensor_ready]()
            and queries[self.sensor_value]() >= ctx.threshold
        )

    accept = transition(
        source=waiting,
        event=check,
        guard=can_accept,
        target=accepted,
    )
    reject = transition(
        source=waiting,
        event=check,
        otherwise=True,
        target=rejected,
    )


def run_check(value: int, threshold: int, *, ready: bool = True) -> str:
    """Выполняет одну проверку и возвращает имя выбранного состояния."""

    sensor = AutomatonObject(
        "sensor",
        Sensor,
        SensorContext(value=value, ready=ready),
    )
    controller = AutomatonObject(
        "controller",
        Controller,
        ControllerContext(threshold=threshold),
    )
    program = Program(
        objects=(sensor, controller),
        connections=(
            Connection(
                required=(controller, Controller.sensor_value),
                provided=(sensor, Sensor.get_value),
            ),
            Connection(
                required=(controller, Controller.sensor_ready),
                provided=(sensor, Sensor.is_ready),
            ),
        ),
    )

    runtime = Runtime(program)
    runtime.send(controller, Controller.check)
    runtime.run()
    return runtime.snapshot(controller).state.name


def main() -> None:
    """Показывает выбор обычной и резервной ветвей без GUI."""

    print("value=12, threshold=10 ->", run_check(12, 10))
    print("value=7, threshold=10 ->", run_check(7, 10))


if __name__ == "__main__":
    main()
