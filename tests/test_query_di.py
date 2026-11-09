"""Сквозные проверки DI-контракта ``Query`` / ``Queries``."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Optional
from xml.etree import ElementTree as ET

from ciao import (
    ActionExecutionError,
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Connection,
    Emit,
    GuardExecutionError,
    InvalidRuntimeCallError,
    ModelValidationError,
    Program,
    Queries,
    Query,
    QueryExecutionError,
    Runtime,
    State,
    StepStatus,
    action,
    compile_program,
    guard,
    provided_command,
    provided_query,
    required_command,
    required_query,
    transition,
)
from ciao.visualization.drawio import export_program_drawio


@dataclass
class SensorContext(AutomatonContext):
    value: int = 10
    ready: bool = True
    calls: int = 0


class Sensor(Automaton[SensorContext]):
    idle = State(initial=True)

    @provided_query
    def read(self, ctx: SensorContext, scale: int = 1) -> int:
        # Счётчик нужен только для доказательства отсутствия неявного кэша.
        ctx.calls += 1
        return ctx.value * scale

    @provided_query
    def is_ready(self, ctx: SensorContext) -> bool:
        return ctx.ready


class ExplodingSensor(Sensor):
    @provided_query
    def read(self, ctx: SensorContext, scale: int = 1) -> int:
        raise ValueError("датчик недоступен")


@dataclass
class SinkContext(AutomatonContext):
    values: list[int] = field(default_factory=list)


class Sink(Automaton[SinkContext]):
    idle = State(initial=True)

    @provided_command
    def accept(self, value: int) -> None:
        ...

    @action
    def store(self, ctx: SinkContext, value: int) -> None:
        ctx.values.append(value)

    on_accept = transition(
        source=idle,
        event=accept,
        actions=(store,),
        target=idle,
    )


@dataclass
class ControllerContext(AutomatonContext):
    last_value: int | None = None


_captured_queries: list[Query] = []


class Controller(Automaton[ControllerContext]):
    idle = State(initial=True)
    passed = State()
    failed = State()

    @provided_command
    def check(self, threshold: int) -> None:
        ...

    @provided_command
    def check_both(self, threshold: int) -> None:
        ...

    @provided_command
    def read_once(self, scale: int = 1) -> None:
        ...

    @provided_command
    def read_twice(self) -> None:
        ...

    @provided_command
    def publish(self) -> None:
        ...

    @provided_command
    def capture(self) -> None:
        ...

    @required_query(text="прочитать значение")
    def sensor_value(self, scale: int = 1) -> int:
        ...

    @required_query(text="проверить готовность")
    def sensor_ready(self) -> bool:
        ...

    @required_command(text="опубликовать значение")
    def output(self, value: int) -> None:
        ...

    @guard(query=sensor_value, text="значение выше порога")
    def above_threshold(
        self,
        ctx: ControllerContext,
        threshold: int,
        query: Query,
    ) -> bool:
        return query() > threshold

    @guard(
        queries=(sensor_value, sensor_ready),
        text="значение выше порога и датчик готов",
    )
    def both_available(
        self,
        ctx: ControllerContext,
        queries: Queries,
        threshold: int,
    ) -> bool:
        return (
            queries[self.sensor_value]() > threshold
            and queries[self.sensor_ready]()
        )

    @action(query=sensor_value, text="сохраняет показание")
    def store_reading(
        self,
        ctx: ControllerContext,
        scale: int,
        *,
        query: Query,
    ) -> None:
        ctx.last_value = query(scale=scale)

    @action(query=sensor_value)
    def store_two_reads(self, ctx: ControllerContext, query: Query) -> None:
        ctx.last_value = query() + query()

    @action(query=sensor_value, emit=output, text="скрытое составное действие")
    def read_and_publish(
        self,
        ctx: ControllerContext,
        emit: Emit,
        query: Query,
    ) -> None:
        value = query()
        ctx.last_value = value
        emit(value=value)

    @action(query=sensor_value)
    def capture_query(self, ctx: ControllerContext, query: Query) -> None:
        _captured_queries.append(query)
        ctx.last_value = query()

    check_passed = transition(
        source=idle,
        event=check,
        guard=above_threshold,
        target=passed,
    )
    check_failed = transition(
        source=idle,
        event=check,
        otherwise=True,
        target=failed,
    )
    both_passed = transition(
        source=idle,
        event=check_both,
        guard=both_available,
        target=passed,
    )
    both_failed = transition(
        source=idle,
        event=check_both,
        otherwise=True,
        target=failed,
    )
    on_read = transition(
        source=idle,
        event=read_once,
        actions=(store_reading,),
        target=passed,
    )
    on_read_twice = transition(
        source=idle,
        event=read_twice,
        actions=(store_two_reads,),
        target=passed,
    )
    on_publish = transition(
        source=idle,
        event=publish,
        actions=(read_and_publish,),
        target=passed,
    )
    on_capture = transition(
        source=idle,
        event=capture,
        actions=(capture_query,),
        target=passed,
    )


def _program(
    *,
    sensor_type: type[Sensor] = Sensor,
    sensor_context: SensorContext | None = None,
) -> tuple[Program, AutomatonObject, AutomatonObject, AutomatonObject]:
    sensor = AutomatonObject(
        "sensor",
        sensor_type,
        sensor_context or SensorContext(),
    )
    controller = AutomatonObject("controller", Controller, ControllerContext())
    sink = AutomatonObject("sink", Sink, SinkContext())
    return (
        Program(
            objects=(controller, sensor, sink),
            connections=(
                Connection(
                    required=(controller, Controller.sensor_value),
                    provided=(sensor, sensor_type.read),
                ),
                Connection(
                    required=(controller, Controller.sensor_ready),
                    provided=(sensor, sensor_type.is_ready),
                ),
                Connection(
                    required=(controller, Controller.output),
                    provided=(sink, Sink.accept),
                ),
            ),
        ),
        controller,
        sensor,
        sink,
    )


class QueryRuntimeTests(unittest.TestCase):
    def test_query_in_guard_selects_main_or_otherwise_transition(self) -> None:
        true_program, controller, _, _ = _program(
            sensor_context=SensorContext(value=11)
        )
        true_runtime = Runtime(true_program)
        true_runtime.send(controller, Controller.check, threshold=10)
        true_result = true_runtime.step()
        self.assertEqual(StepStatus.PROCESSED, true_result.status)
        self.assertIs(Controller.passed, true_runtime.snapshot(controller).state)

        false_program, false_controller, _, _ = _program(
            sensor_context=SensorContext(value=9)
        )
        false_runtime = Runtime(false_program)
        false_runtime.send(false_controller, Controller.check, threshold=10)
        false_runtime.step()
        self.assertIs(
            Controller.failed,
            false_runtime.snapshot(false_controller).state,
        )

    def test_queries_in_guard_use_declared_operations(self) -> None:
        program, controller, sensor, _ = _program(
            sensor_context=SensorContext(value=15, ready=True)
        )
        runtime = Runtime(program)
        runtime.send(controller, Controller.check_both, threshold=10)
        runtime.step()

        self.assertIs(Controller.passed, runtime.snapshot(controller).state)
        self.assertEqual(1, runtime.snapshot(sensor).calls)
        self.assertEqual(0, runtime.pending_messages)

    def test_query_in_action_returns_immediately_and_accepts_keyword_only_di(self) -> None:
        program, controller, sensor, _ = _program(
            sensor_context=SensorContext(value=7)
        )
        runtime = Runtime(program)
        runtime.send(controller, Controller.read_once, scale=3)
        result = runtime.step()

        self.assertEqual(21, runtime.snapshot(controller).last_value)
        self.assertEqual(1, runtime.snapshot(sensor).calls)
        self.assertEqual((), result.emitted)
        self.assertEqual(0, runtime.pending_messages)

    def test_query_and_emit_keep_synchronous_and_fifo_order(self) -> None:
        program, controller, sensor, sink = _program(
            sensor_context=SensorContext(value=23)
        )
        runtime = Runtime(program)
        runtime.send(controller, Controller.publish)
        first = runtime.step()

        self.assertEqual(23, runtime.snapshot(controller).last_value)
        self.assertEqual(1, runtime.snapshot(sensor).calls)
        self.assertEqual([], runtime.snapshot(sink).values)
        self.assertEqual(("accept",), tuple(item.operation for item in first.emitted))
        self.assertEqual(1, runtime.pending_messages)

        runtime.step()
        self.assertEqual([23], runtime.snapshot(sink).values)

    def test_query_is_not_cached_within_one_action(self) -> None:
        program, controller, sensor, _ = _program(
            sensor_context=SensorContext(value=5)
        )
        runtime = Runtime(program)
        runtime.send(controller, Controller.read_twice)
        runtime.step()

        self.assertEqual(10, runtime.snapshot(controller).last_value)
        self.assertEqual(2, runtime.snapshot(sensor).calls)

    def test_query_is_invalid_after_handler_returns(self) -> None:
        _captured_queries.clear()
        program, controller, _, _ = _program()
        runtime = Runtime(program)
        runtime.send(controller, Controller.capture)
        runtime.step()

        self.assertEqual(1, len(_captured_queries))
        with self.assertRaises(InvalidRuntimeCallError):
            _captured_queries[0]()

    def test_two_instances_route_query_to_their_own_sensor(self) -> None:
        first_sensor = AutomatonObject("sensor-1", Sensor, SensorContext(value=3))
        second_sensor = AutomatonObject("sensor-2", Sensor, SensorContext(value=8))
        first = AutomatonObject("controller-1", Controller, ControllerContext())
        second = AutomatonObject("controller-2", Controller, ControllerContext())
        first_sink = AutomatonObject("sink-1", Sink, SinkContext())
        second_sink = AutomatonObject("sink-2", Sink, SinkContext())

        connections: list[Connection] = []
        for controller, sensor, sink in (
            (first, first_sensor, first_sink),
            (second, second_sensor, second_sink),
        ):
            connections.extend(
                (
                    Connection(
                        required=(controller, Controller.sensor_value),
                        provided=(sensor, Sensor.read),
                    ),
                    Connection(
                        required=(controller, Controller.sensor_ready),
                        provided=(sensor, Sensor.is_ready),
                    ),
                    Connection(
                        required=(controller, Controller.output),
                        provided=(sink, Sink.accept),
                    ),
                )
            )
        runtime = Runtime(
            Program(
                objects=(first, second, first_sensor, second_sensor, first_sink, second_sink),
                connections=tuple(connections),
            )
        )
        runtime.send(first, Controller.read_once)
        runtime.send(second, Controller.read_once)
        runtime.run()

        self.assertEqual(3, runtime.snapshot(first).last_value)
        self.assertEqual(8, runtime.snapshot(second).last_value)

    def test_provider_error_is_not_false_or_otherwise_even_when_not_strict(self) -> None:
        program, controller, _, _ = _program(sensor_type=ExplodingSensor)
        runtime = Runtime(program, strict=False)
        runtime.send(controller, Controller.check, threshold=10)

        with self.assertRaises(GuardExecutionError) as captured:
            runtime.step()
        query_error = captured.exception.__cause__
        self.assertIsInstance(query_error, QueryExecutionError)
        assert query_error is not None
        self.assertIsInstance(query_error.__cause__, ValueError)
        self.assertIn("controller.sensor_value", str(query_error))
        self.assertIn("sensor.read", str(query_error))
        self.assertIs(Controller.idle, runtime.snapshot(controller).state)
        self.assertEqual(StepStatus.ERROR, runtime.trace[-1].status)

    def test_external_provided_query_uses_same_execution_error(self) -> None:
        program, _, sensor, _ = _program(sensor_type=ExplodingSensor)
        runtime = Runtime(program)
        with self.assertRaises(QueryExecutionError) as captured:
            runtime.query(sensor, ExplodingSensor.read)
        self.assertIsInstance(captured.exception.__cause__, ValueError)


class QueryValidationTests(unittest.TestCase):
    def test_metadata_preserves_singular_plural_forms_and_compiled_plans(self) -> None:
        self.assertIs(Controller.sensor_value, Controller.above_threshold.query)
        self.assertIsNone(Controller.above_threshold.queries)
        self.assertEqual(
            (Controller.sensor_value,),
            Controller.above_threshold.outgoing_queries,
        )
        self.assertEqual(
            (Controller.sensor_value, Controller.sensor_ready),
            Controller.both_available.queries,
        )
        self.assertEqual("прочитать значение", Controller.sensor_value.text)
        self.assertEqual("опубликовать значение", Controller.output.text)

        program, _, _, _ = _program()
        definition = compile_program(program).definitions[Controller]
        guard_plan = definition.guard_query_injections[Controller.above_threshold]
        action_plan = definition.action_query_injections[Controller.read_and_publish]
        self.assertIsNotNone(guard_plan)
        self.assertIsNotNone(action_plan)
        assert guard_plan is not None and action_plan is not None
        self.assertIs(Query, guard_plan.capability_type)
        self.assertEqual((Controller.sensor_value,), guard_plan.queries)
        self.assertIs(Query, action_plan.capability_type)
        self.assertIsNotNone(definition.action_injections[Controller.read_and_publish])

    def test_public_construction_and_unsupported_decorator_forms_are_rejected(self) -> None:
        self.assertFalse(hasattr(Automaton, "query"))
        with self.assertRaises(TypeError):
            Query()
        with self.assertRaises(TypeError):
            Queries()
        with self.assertRaises(TypeError):
            guard()
        with self.assertRaises(TypeError):
            guard(queries=())
        with self.assertRaises(TypeError):
            action(query=Controller.sensor_value, queries=(Controller.sensor_value,))
        with self.assertRaises(TypeError):
            required_query()
        with self.assertRaises(TypeError):
            required_command()
        with self.assertRaises(TypeError):
            required_query(text=1)  # type: ignore[arg-type]

    def test_queries_rejects_operation_not_declared_for_action(self) -> None:
        class Invalid(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def first(self, scale: int = 1) -> int:
                ...

            @required_query
            def second(self, scale: int = 1) -> int:
                ...

            @action(queries=(first,))
            def read(self, ctx: ControllerContext, queries: Queries) -> None:
                ctx.last_value = queries[self.second]()

            on_start = transition(
                source=idle,
                event=start,
                actions=(read,),
                target=idle,
            )

        invalid = AutomatonObject("invalid", Invalid, ControllerContext())
        sensor = AutomatonObject("sensor", Sensor, SensorContext())
        runtime = Runtime(
            Program(
                objects=(invalid, sensor),
                connections=(
                    Connection(
                        required=(invalid, Invalid.first),
                        provided=(sensor, Sensor.read),
                    ),
                    Connection(
                        required=(invalid, Invalid.second),
                        provided=(sensor, Sensor.read),
                    ),
                ),
            )
        )
        runtime.send(invalid, Invalid.start)
        with self.assertRaises(ActionExecutionError) as captured:
            runtime.step()
        self.assertIsInstance(captured.exception.__cause__, InvalidRuntimeCallError)

    def test_invalid_query_metadata_is_rejected(self) -> None:
        class Foreign(Automaton[ControllerContext]):
            idle = State(initial=True)

            @required_query
            def value(self) -> int:
                ...

        class Invalid(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_command
            def output(self) -> None:
                ...

            @provided_query
            def local(self, ctx: ControllerContext) -> int:
                return 1

            @guard(query=local)
            def provided(self, ctx: ControllerContext, query: Query) -> bool:
                return True

            @action(query=output)
            def command(self, ctx: ControllerContext, query: Query) -> None:
                ...

            @action(queries=(Foreign.value, Foreign.value))
            def foreign(self, ctx: ControllerContext, queries: Queries) -> None:
                ...

            provided_transition = transition(
                source=idle,
                event=start,
                guard=provided,
                target=idle,
            )
            command_transition = transition(
                source=idle,
                event=start,
                actions=(command, foreign),
                target=idle,
            )

        invalid = AutomatonObject("invalid", Invalid, ControllerContext())
        with self.assertRaises(ModelValidationError):
            compile_program(Program(objects=(invalid,)))

    def test_wrong_optional_annotated_and_missing_declarations_are_rejected(self) -> None:
        cases: list[type[Automaton[ControllerContext]]] = []

        class Wrong(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def value(self) -> int:
                ...

            @action(query=value)
            def read(self, ctx: ControllerContext, query: Queries) -> None:
                ...

            on_start = transition(source=idle, event=start, actions=(read,), target=idle)

        cases.append(Wrong)

        class OptionalQuery(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def value(self) -> int:
                ...

            @action(query=value)
            def read(
                self,
                ctx: ControllerContext,
                query: Optional[Query],
            ) -> None:
                ...

            on_start = transition(source=idle, event=start, actions=(read,), target=idle)

        cases.append(OptionalQuery)

        class AnnotatedQuery(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @required_query
            def value(self) -> int:
                ...

            @action(query=value)
            def read(
                self,
                ctx: ControllerContext,
                query: Annotated[Query, "not-exact"],
            ) -> None:
                ...

            on_start = transition(source=idle, event=start, actions=(read,), target=idle)

        cases.append(AnnotatedQuery)

        class Undeclared(Automaton[ControllerContext]):
            idle = State(initial=True)

            @provided_command
            def start(self) -> None:
                ...

            @action
            def read(self, ctx: ControllerContext, query: Query) -> None:
                ...

            on_start = transition(source=idle, event=start, actions=(read,), target=idle)

        cases.append(Undeclared)

        for automaton_type in cases:
            with self.subTest(automaton=automaton_type.__name__):
                object_ref = AutomatonObject(
                    "invalid",
                    automaton_type,
                    ControllerContext(),
                )
                with self.assertRaises(ModelValidationError):
                    compile_program(Program(objects=(object_ref,)))

    def test_unconnected_required_query_is_compile_error(self) -> None:
        controller = AutomatonObject("controller", Controller, ControllerContext())
        with self.assertRaisesRegex(ModelValidationError, "не задан Connection"):
            compile_program(Program(objects=(controller,)))

    def test_provided_query_cannot_request_query_di(self) -> None:
        with self.assertRaises(TypeError):
            provided_query(query=Controller.sensor_value)  # type: ignore[call-arg]


class QueryDrawioTests(unittest.TestCase):
    def test_query_blocks_operation_text_and_metadata_are_exported(self) -> None:
        program, _, _, _ = _program()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "query.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()

        transitions = {
            cell.get("ciaoTransition"): cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition")
        }
        guard_label = transitions["both_passed"].get("value", "")
        self.assertIn("&lt;&lt;Query&gt;&gt;:", guard_label)
        self.assertLess(
            guard_label.index("sensor_value(scale=1)"),
            guard_label.index("sensor_ready()"),
        )
        self.assertIn("прочитать значение", guard_label)
        self.assertIn("проверить готовность", guard_label)

        action_label = transitions["on_read"].get("value", "")
        self.assertIn("store_reading", action_label)
        self.assertIn("&lt;&lt;Query&gt;&gt;:", action_label)

        combined = transitions["on_publish"]
        combined_label = combined.get("value", "")
        self.assertNotIn("read_and_publish", combined_label)
        self.assertNotIn("скрытое составное действие", combined_label)
        self.assertIn("&lt;&lt;Query&gt;&gt;:", combined_label)
        self.assertIn("output(value)", combined_label)
        self.assertIn("опубликовать значение", combined_label)
        self.assertEqual(
            "Controller.sensor_value",
            combined.get("ciaoQueries"),
        )

        required_half = next(
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoElement") == "connectionRequired"
            and cell.get("ciaoOperation") == "sensor_value"
        )
        self.assertEqual("прочитать значение", required_half.get("ciaoText"))


if __name__ == "__main__":
    unittest.main()
