"""Проверки публичного API ролей и одностороннего экспорта draw.io."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from ciao import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    AutomatonRole,
    Connection,
    ControllerAutomaton,
    Emits,
    ModelValidationError,
    OperationKind,
    Program,
    Runtime,
    State,
    ViewAutomaton,
    action,
    compile_program,
    guard,
    provided_command,
    provided_query,
    required_query,
    required_command,
    transition,
)
from ciao.visualization.drawio import export_program_drawio
from ciao.visualization.drawio.layout import layout_diagram
from examples.array_sum.automatos import SumController, SumView
from examples.array_sum.contracts import CalculationMode, StartInput
from examples.array_sum.program import build_sample
from examples.calculator.program import build_calculator_program


def _cells(root: ET.Element, kind: str) -> list[ET.Element]:
    return [
        cell
        for cell in root.findall(".//mxCell")
        if cell.get("ciaoElement") == kind
    ]


@dataclass
class QueryContext(AutomatonContext):
    value: int = 7


class QueryProvider(ViewAutomaton[QueryContext]):
    ready = State(initial=True)

    @provided_query
    def read(self, ctx: QueryContext, scale: int = 1) -> int:
        return ctx.value * scale


class QueryConsumer(ControllerAutomaton[QueryContext]):
    ready = State(initial=True)

    @required_query
    def source(self, scale: int = 1) -> int:
        ...


class PlainBaseContext(AutomatonContext):
    first: int


class PlainContext(PlainBaseContext):
    first: float
    second: str
    transient = "не является объявленным полем"


class PlainAutomaton(Automaton[PlainContext]):
    only = State(initial=True, final=True)
    alternative = State(final=True)


class SelfConnectedAutomaton(Automaton[QueryContext]):
    ready = State(initial=True)

    @required_command
    def send(self) -> None:
        ...

    @provided_command
    def receive(self) -> None:
        ...

    on_receive = transition(source=ready, event=receive, target=ready)


class MultiEmitProvider(ViewAutomaton[QueryContext]):
    ready = State(initial=True)

    @provided_command
    def first(self, value: int) -> None:
        ...

    @provided_command
    def second(self, text: str) -> None:
        ...


class MultiEmitConsumer(ControllerAutomaton[QueryContext]):
    ready = State(initial=True)

    @provided_command
    def trigger(self) -> None:
        ...

    @required_command
    def first(self, value: int) -> None:
        ...

    @required_command
    def second(self, text: str) -> None:
        ...

    @guard(text="разрешена\nпубликация")
    def may_publish(self, ctx: QueryContext) -> bool:
        return True

    @action(text="готовит данные")
    def prepare(self, ctx: QueryContext) -> None:
        ...

    @action(emits=(second, first), text="публикует сообщения")
    def publish(self, ctx: QueryContext, emits: Emits) -> None:
        ...

    on_trigger = transition(
        source=ready,
        event=trigger,
        guard=may_publish,
        actions=(prepare, publish),
        target=ready,
    )

    otherwise_trigger = transition(
        source=ready,
        event=trigger,
        otherwise=True,
        target=ready,
    )


class DrawioTests(unittest.TestCase):
    def _export_sample(self, directory: str) -> tuple[Path, ET.Element]:
        output = Path(directory) / "sample.drawio"
        export_program_drawio(build_sample().program, output)
        return output, ET.parse(output).getroot()

    def test_sample_contains_expected_native_elements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        self.assertEqual("mxfile", root.tag)
        cells = root.findall(".//mxCell")
        ids = [cell.get("id") for cell in cells]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(2, len(_cells(root, "automaton")))
        self.assertEqual(11, len(_cells(root, "state")))
        self.assertEqual(2, len(_cells(root, "exit")))
        self.assertEqual(2, len(_cells(root, "entry")))
        self.assertEqual(2, len(_cells(root, "entryTransition")))
        self.assertEqual(22, len([cell for cell in cells if cell.get("ciaoTransition")]))
        self.assertEqual(6, len(_cells(root, "decision")))
        self.assertEqual(7, len(_cells(root, "connectionJunction")))
        self.assertEqual(7, len(_cells(root, "connectionRequired")))
        self.assertEqual(7, len(_cells(root, "connectionProvided")))

        known_ids = set(ids)
        for edge in (cell for cell in cells if cell.get("edge") == "1"):
            self.assertIn(edge.get("source"), known_ids)
            self.assertIn(edge.get("target"), known_ids)

    def test_external_operations_are_outside_view_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        view = next(
            cell for cell in _cells(root, "automaton") if cell.get("ciaoObject") == "view"
        )
        init = next(
            cell
            for cell in _cells(root, "operation")
            if cell.get("ciaoOperation") == "init_clicked"
        )
        view_y = int(view.find("mxGeometry").get("y", "0"))
        init_geometry = init.find("mxGeometry")
        self.assertEqual("true", init.get("ciaoExternal"))
        self.assertLessEqual(
            int(init_geometry.get("y", "0")) + int(init_geometry.get("height", "0")),
            view_y,
        )
        self.assertIn("shape=lollipop", init.get("style", ""))
        init_label = next(
            cell
            for cell in _cells(root, "operationLabel")
            if cell.get("ciaoOperation") == "init_clicked"
        )
        self.assertEqual("init_clicked(request)", init_label.get("value"))
        self.assertLessEqual(
            int(init_label.find("mxGeometry").get("y", "0"))
            + int(init_label.find("mxGeometry").get("height", "0")),
            int(init_geometry.get("y", "0")),
        )
        self.assertEqual(3, len(_cells(root, "externalRequiredInterface")))

    def test_final_state_and_role_colors_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        done = next(
            cell for cell in _cells(root, "exit") if cell.get("ciaoState") == "done"
        )
        self.assertEqual("true", done.get("ciaoFinal"))
        self.assertIn("shape=endState", done.get("style", ""))
        self.assertIn("fillColor=#000000", done.get("style", ""))
        done_label = next(
            cell
            for cell in _cells(root, "exitLabel")
            if cell.get("ciaoState") == "done"
        )
        self.assertEqual("done", done_label.get("value"))

        automatons = {
            cell.get("ciaoObject"): cell for cell in _cells(root, "automaton")
        }
        roles = {name: cell.get("ciaoRole") for name, cell in automatons.items()}
        self.assertEqual("controller", roles["controller"])
        self.assertEqual("view", roles["view"])
        self.assertIn("fillColor=#FFFFFF", automatons["controller"].get("style", ""))
        self.assertIn("fillColor=#FFFFFF", automatons["view"].get("style", ""))

        controller_state = next(
            cell
            for cell in _cells(root, "state")
            if cell.get("ciaoState") == "idle" and "controller" in cell.get("id", "")
        )
        view_state = next(
            cell
            for cell in _cells(root, "state")
            if cell.get("ciaoState") == "idle" and "view" in cell.get("id", "")
        )
        self.assertIn("fillColor=#EAF5FD", controller_state.get("style", ""))
        self.assertIn("fillColor=#EBF9F3", view_state.get("style", ""))

    def test_connection_uses_socket_and_ball_at_common_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        automatons = {
            cell.get("ciaoObject"): cell for cell in _cells(root, "automaton")
        }
        required = next(
            cell
            for cell in _cells(root, "connectionRequired")
            if cell.get("ciaoOperation") == "draw"
        )
        provided = next(
            cell
            for cell in _cells(root, "connectionProvided")
            if cell.get("ciaoOperation") == "draw"
        )
        junction = next(
            cell
            for cell in _cells(root, "connectionJunction")
            if cell.get("id") == required.get("target")
        )
        label = next(
            cell
            for cell in _cells(root, "connectionLabel")
            if cell.get("value") == "draw"
        )

        self.assertEqual(automatons["controller"].get("id"), required.get("source"))
        self.assertEqual(automatons["view"].get("id"), provided.get("source"))
        self.assertEqual(junction.get("id"), required.get("target"))
        self.assertEqual(junction.get("id"), provided.get("target"))
        self.assertIn("endArrow=halfCircle", required.get("style", ""))
        self.assertIn("endArrow=oval", provided.get("style", ""))
        self.assertIn("edgeStyle=orthogonalEdgeStyle", required.get("style", ""))
        self.assertIn("edgeStyle=orthogonalEdgeStyle", provided.get("style", ""))
        self.assertEqual("draw", label.get("value"))
        self.assertEqual("draw", required.get("ciaoOperation"))
        self.assertEqual("draw", provided.get("ciaoOperation"))

        connected_draw_nodes = [
            cell
            for cell in _cells(root, "operation")
            if cell.get("ciaoOperation") == "draw"
        ]
        self.assertEqual([], connected_draw_nodes)

        acknowledgement = next(
            cell
            for cell in _cells(root, "connectionLabel")
            if cell.get("value") == "draw_completed"
        )
        self.assertIsNotNone(acknowledgement)

    def test_parallel_connections_use_separate_block_exit_points(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        halves = _cells(root, "connectionRequired") + _cells(
            root,
            "connectionProvided",
        )
        offsets_by_connection: dict[str, set[str]] = {}
        for half in halves:
            connection_id = half.get("ciaoConnection", "")
            style = half.get("style", "")
            offset = next(
                item.removeprefix("exitY=")
                for item in style.split(";")
                if item.startswith("exitY=")
            )
            offsets_by_connection.setdefault(connection_id, set()).add(offset)

        self.assertEqual(7, len(offsets_by_connection))
        self.assertGreaterEqual(
            len(set().union(*offsets_by_connection.values())),
            6,
        )

    def test_connection_labels_stay_inside_interblock_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        blocks = [cell.find("mxGeometry") for cell in _cells(root, "automaton")]
        for label in _cells(root, "connectionLabel"):
            geometry = label.find("mxGeometry")
            label_left = int(geometry.get("x", "0"))
            label_right = label_left + int(geometry.get("width", "0"))
            for block in blocks:
                block_left = int(block.get("x", "0"))
                block_right = block_left + int(block.get("width", "0"))
                self.assertTrue(
                    label_right <= block_left or label_left >= block_right,
                    "Подпись connection не должна заходить на блок автомата",
                )

    def test_transition_displays_emitted_commands_instead_of_action_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        controller_transition = next(
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition") == "on_last_step_tick"
        )
        controller_label = controller_transition.get("value", "")
        self.assertIn("draw(snapshot)", controller_label)
        self.assertNotIn("publish_snapshot", controller_label)
        self.assertTrue(
            any(
                cell.get("value") == "tick()"
                for cell in _cells(root, "decisionIncoming")
            )
        )

        view_transition = next(
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition") == "on_completed_step_draw"
        )
        view_label = view_transition.get("value", "")
        self.assertIn("render_data(presentation)", view_label)
        self.assertIn("draw_completed()", view_label)
        self.assertNotIn("publish_snapshot", view_label)
        self.assertTrue(
            any(
                cell.get("value") == "draw(snapshot)"
                for cell in _cells(root, "decisionIncoming")
            )
        )

    def test_otherwise_branch_is_last_and_marked_as_else(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        branches = [
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition")
            in {
                "on_step_tick",
                "on_last_step_tick",
            }
        ]
        self.assertEqual(
            ["on_step_tick", "on_last_step_tick"],
            [cell.get("ciaoTransition") for cell in branches],
        )
        guarded, fallback = branches
        self.assertIsNone(guarded.get("ciaoOtherwise"))
        self.assertEqual("true", fallback.get("ciaoOtherwise"))
        self.assertIn("[else]", fallback.get("value", ""))

    def test_emits_preserves_declared_command_order_in_transition(self) -> None:
        consumer = AutomatonObject(
            "consumer",
            MultiEmitConsumer,
            QueryContext(),
        )
        provider = AutomatonObject(
            "provider",
            MultiEmitProvider,
            QueryContext(),
        )
        program = Program(
            objects=(consumer, provider),
            connections=(
                Connection(
                    required=(consumer, MultiEmitConsumer.first),
                    provided=(provider, MultiEmitProvider.first),
                ),
                Connection(
                    required=(consumer, MultiEmitConsumer.second),
                    provided=(provider, MultiEmitProvider.second),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "emits.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()

        transition_cell = next(
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition") == "on_trigger"
        )
        label = transition_cell.get("value", "")
        self.assertIn("[may_publish: разрешена<br>публикация]", label)
        self.assertIn("<br>/ <b>prepare:</b> готовит данные", label)
        self.assertIn(
            "<br>/ <b>prepare:</b> готовит данные<br>second(text)<br>first(value)",
            label,
        )
        self.assertNotIn("<br>/ second(text)", label)
        self.assertNotIn("<br>/ first(value)", label)
        self.assertNotIn("<b>publish:</b>", label)
        self.assertNotIn("публикует сообщения", label)
        self.assertEqual("разрешена\nпубликация", MultiEmitConsumer.may_publish.text)
        self.assertEqual("публикует сообщения", MultiEmitConsumer.publish.text)

    def test_self_connection_halves_leave_block_at_different_points(self) -> None:
        object_ref = AutomatonObject(
            "self_connected",
            SelfConnectedAutomaton,
            QueryContext(),
        )
        program = Program(
            objects=(object_ref,),
            connections=(
                Connection(
                    required=(object_ref, SelfConnectedAutomaton.send),
                    provided=(object_ref, SelfConnectedAutomaton.receive),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "self.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()

        required = _cells(root, "connectionRequired")[0]
        provided = _cells(root, "connectionProvided")[0]
        self.assertIn("exitY=0.43", required.get("style", ""))
        self.assertIn("exitY=0.57", provided.get("style", ""))
        self.assertEqual(required.get("target"), provided.get("target"))

    def test_state_transition_routes_use_separate_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        transitions = {
            cell.get("ciaoTransition"): cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition")
        }
        tick_branches = [
            transitions["on_step_tick"],
            transitions["on_last_step_tick"],
        ]
        branch_routes = [
            tuple(
                (int(point.get("x", "0")), int(point.get("y", "0")))
                for point in branch.findall("./mxGeometry/Array/mxPoint")
            )
            for branch in tick_branches
        ]
        self.assertNotEqual(branch_routes[0], branch_routes[1])
        for branch in tick_branches:
            self.assertIsNotNone(
                branch.find("./mxGeometry/mxPoint[@as='offset']")
            )

    def test_transition_labels_keep_explicit_lines_and_use_sized_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        transitions = [
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition")
        ]
        self.assertTrue(transitions)
        for transition_cell in transitions:
            label = transition_cell.get("value", "")
            self.assertNotIn("\n", label)
            self.assertIn("resizable=1", transition_cell.get("style", ""))
            self.assertNotIn(
                transition_cell.get("ciaoTransition", ""),
                label,
            )
            geometry = transition_cell.find("mxGeometry")
            self.assertEqual("0", geometry.get("y"))
            width = int(geometry.get("width", "0"))
            height = int(geometry.get("height", "0"))
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
            offset = geometry.find("mxPoint[@as='offset']")
            self.assertIsNotNone(offset)
            self.assertIsNotNone(offset.get("x"))
            self.assertIsNotNone(offset.get("y"))
            offset_x = abs(int(offset.get("x")))
            offset_y = abs(int(offset.get("y")))
            edge_gap = (
                offset_x - width // 2
                if offset_x
                else offset_y - height // 2
            )
            self.assertGreaterEqual(edge_gap, 10)
            self.assertLessEqual(edge_gap, 54)

        emitted_label = next(
            cell.get("value", "")
            for cell in transitions
            if cell.get("ciaoTransition") == "on_last_step_tick"
        )
        emitted_call = emitted_label.split("draw(", 1)[1].split(")", 1)[0]
        self.assertNotIn("<br>", emitted_call)

    def test_transition_label_boxes_do_not_overlap_model_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        cells_by_id = {
            cell.get("id"): cell for cell in root.findall(".//mxCell")
        }

        def rectangle(cell: ET.Element) -> tuple[int, int, int, int]:
            geometry = cell.find("mxGeometry")
            return (
                int(geometry.get("x", "0")),
                int(geometry.get("y", "0")),
                int(geometry.get("width", "0")),
                int(geometry.get("height", "0")),
            )

        def center(cell: ET.Element) -> tuple[float, float]:
            x, y, width, height = rectangle(cell)
            return x + width / 2, y + height / 2

        def point_on_path(
            points: list[tuple[float, float]],
            fraction: float,
        ) -> tuple[float, float]:
            lengths = [
                hypot(right[0] - left[0], right[1] - left[1])
                for left, right in zip(points, points[1:])
            ]
            remaining = sum(lengths) * fraction
            for left, right, length in zip(points, points[1:], lengths):
                if remaining <= length:
                    ratio = remaining / length if length else 0
                    return (
                        left[0] + (right[0] - left[0]) * ratio,
                        left[1] + (right[1] - left[1]) * ratio,
                    )
                remaining -= length
            return points[-1]

        obstacles = [
            rectangle(cell)
            for kind in (
                "state",
                "exit",
                "exitLabel",
                "entry",
                "context",
                "decision",
                "actionLabel",
                "operation",
                "operationLabel",
            )
            for cell in _cells(root, kind)
        ]
        placed_labels: list[tuple[int, int, int, int]] = []
        for edge in (
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition")
            in {"on_step_tick", "on_last_step_tick"}
            and cell.get("value")
        ):
            geometry = edge.find("mxGeometry")
            points = [center(cells_by_id[edge.get("source")])]
            points.extend(
                (
                    float(point.get("x", "0")),
                    float(point.get("y", "0")),
                )
                for point in geometry.findall("./Array/mxPoint")
            )
            points.append(center(cells_by_id[edge.get("target")]))
            relative_position = float(geometry.get("x", "0"))
            anchor_x, anchor_y = point_on_path(
                points,
                (relative_position + 1) / 2,
            )
            offset = geometry.find("mxPoint[@as='offset']")
            width = int(geometry.get("width", "0"))
            height = int(geometry.get("height", "0"))
            label_rectangle = (
                round(anchor_x + int(offset.get("x", "0")) - width / 2),
                round(anchor_y + int(offset.get("y", "0")) - height / 2),
                width,
                height,
            )
            label_x, label_y, label_width, label_height = label_rectangle
            for node_x, node_y, node_width, node_height in obstacles:
                overlaps = not (
                    label_x + label_width <= node_x
                    or node_x + node_width <= label_x
                    or label_y + label_height <= node_y
                    or node_y + node_height <= label_y
                )
                self.assertFalse(
                    overlaps,
                    f"Подпись {edge.get('ciaoTransition')} {label_rectangle} "
                    f"пересекает узел {(node_x, node_y, node_width, node_height)}",
                )
            placed_labels.append(label_rectangle)

    def test_transition_routes_do_not_cross_unrelated_graph_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        cells_by_id = {
            cell.get("id"): cell for cell in root.findall(".//mxCell")
        }

        def rectangle(cell: ET.Element) -> tuple[float, float, float, float]:
            geometry = cell.find("mxGeometry")
            return tuple(
                float(geometry.get(attribute, "0"))
                for attribute in ("x", "y", "width", "height")
            )

        def center(cell: ET.Element) -> tuple[float, float]:
            x, y, width, height = rectangle(cell)
            return x + width / 2, y + height / 2

        graph_nodes = [
            cell
            for kind in ("state", "exit", "entry")
            for cell in _cells(root, kind)
        ]

        def segment_intersects(
            left: tuple[float, float],
            right: tuple[float, float],
            node: tuple[float, float, float, float],
        ) -> bool:
            x, y, width, height = node
            if left[0] == right[0]:
                low, high = sorted((left[1], right[1]))
                return x < left[0] < x + width and high > y and low < y + height
            if left[1] == right[1]:
                low, high = sorted((left[0], right[0]))
                return y < left[1] < y + height and high > x and low < x + width
            return False

        for edge in (
            cell
            for kind in ("transition", "transitionBranch", "decisionIncoming")
            for cell in _cells(root, kind)
            if cell.get("ciaoTransition")
            in {"on_step_tick", "on_last_step_tick"}
        ):
            geometry = edge.find("mxGeometry")
            points = [center(cells_by_id[edge.get("source")])]
            points.extend(
                (float(point.get("x", "0")), float(point.get("y", "0")))
                for point in geometry.findall("./Array/mxPoint")
            )
            points.append(center(cells_by_id[edge.get("target")]))
            for node in graph_nodes:
                if node.get("id") in (edge.get("source"), edge.get("target")):
                    continue
                self.assertFalse(
                    any(
                        segment_intersects(left, right, rectangle(node))
                        for left, right in zip(points, points[1:])
                    ),
                    f"Переход {edge.get('ciaoTransition')} пересекает "
                    f"узел {node.get('id')}",
                )

        decisions_and_exits = _cells(root, "decision") + _cells(root, "exit")
        for index, first in enumerate(decisions_and_exits):
            first_x, first_y, first_width, first_height = rectangle(first)
            for second in decisions_and_exits[index + 1 :]:
                second_x, second_y, second_width, second_height = rectangle(second)
                self.assertTrue(
                    first_x + first_width <= second_x
                    or second_x + second_width <= first_x
                    or first_y + first_height <= second_y
                    or second_y + second_height <= first_y
                )

    def test_context_fields_do_not_expose_values_or_class_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        labels = [cell.get("value", "") for cell in _cells(root, "context")]
        controller = next(label for label in labels if "tick_count" in label)
        self.assertIn("controller : SumController", controller)
        self.assertIn("values: list[int]", controller)
        self.assertIn("total: int", controller)
        self.assertNotIn("SumContext", controller)
        self.assertNotIn("default", controller)

        controller_block = next(
            cell for cell in _cells(root, "automaton") if cell.get("ciaoObject") == "controller"
        )
        controller_context = next(
            cell for cell in _cells(root, "context") if "SumController" in cell.get("value", "")
        )
        block_geometry = controller_block.find("mxGeometry")
        context_geometry = controller_context.find("mxGeometry")
        self.assertEqual("", controller_block.get("value", ""))
        self.assertEqual(block_geometry.get("x"), context_geometry.get("x"))
        self.assertEqual(block_geometry.get("y"), context_geometry.get("y"))
        self.assertIn("fillColor=#dae8fc", controller_context.get("style", ""))

    def test_external_labels_are_above_icons_and_do_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        labels = [
            cell
            for cell in _cells(root, "operationLabel")
            if cell.get("ciaoExternal") == "true"
        ]
        self.assertEqual(7, len(labels))
        rectangles = []
        for label in labels:
            operation = next(
                cell
                for cell in _cells(root, "operation")
                if cell.get("ciaoOperation") == label.get("ciaoOperation")
            )
            label_geometry = label.find("mxGeometry")
            operation_geometry = operation.find("mxGeometry")
            label_bottom = int(label_geometry.get("y", "0")) + int(
                label_geometry.get("height", "0")
            )
            if operation.get("ciaoDirection") == "provided":
                symbol_top = int(operation_geometry.get("y", "0"))
            else:
                interface = next(
                    cell
                    for cell in _cells(root, "externalRequiredInterface")
                    if cell.get("ciaoOperation") == label.get("ciaoOperation")
                )
                tip = next(
                    cell
                    for cell in _cells(root, "interfaceAnchor")
                    if cell.get("id") == interface.get("target")
                )
                symbol_top = int(tip.find("mxGeometry").get("y", "0"))
            self.assertLess(label_bottom, symbol_top)
            rectangles.append(
                (
                    int(label_geometry.get("x", "0")),
                    label_bottom,
                    int(label_geometry.get("width", "0")),
                )
            )
        horizontal = sorted((x, x + width) for x, _, width in rectangles)
        for previous, current in zip(horizontal, horizontal[1:]):
            self.assertGreaterEqual(current[0] - previous[1], 18)

    def test_plain_context_uses_mro_annotations_and_ignores_unannotated_values(self) -> None:
        object_ref = AutomatonObject("plain", PlainAutomaton, PlainContext())
        program = Program(objects=(object_ref,))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plain.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()

        label = _cells(root, "context")[0].get("value", "")
        self.assertLess(label.index("first: float"), label.index("second: str"))
        self.assertNotIn("transient", label)
        final_states = _cells(root, "exit")
        self.assertEqual(2, len(final_states))

    def test_query_signature_comes_from_compiled_metadata(self) -> None:
        provider = AutomatonObject("provider", QueryProvider, QueryContext())
        consumer = AutomatonObject("consumer", QueryConsumer, QueryContext())
        program = Program(
            objects=(consumer, provider),
            connections=(
                Connection(
                    required=(consumer, QueryConsumer.source),
                    provided=(provider, QueryProvider.read),
                ),
            ),
        )
        compiled = compile_program(program)
        signature = compiled.definitions[QueryConsumer].operation_signatures[
            QueryConsumer.source
        ]
        self.assertEqual("scale", signature.parameters[0].name)
        self.assertIs(int, signature.parameters[0].annotation)
        self.assertIs(int, signature.return_type)
        with self.assertRaises(TypeError):
            compiled.definitions[QueryConsumer].operation_signatures[
                QueryConsumer.source
            ] = signature

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "queries.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()
        query_labels = [
            cell.get("value", "")
            for cell in _cells(root, "connectionLabel")
        ]
        self.assertEqual(["source"], query_labels)
        query_connection = _cells(root, "connectionRequired")[0]
        self.assertIn("scale: int=1", query_connection.get("ciaoSignature", ""))
        self.assertIn("-> int", query_connection.get("ciaoSignature", ""))
        self.assertIn("strokeColor=#B85450", query_connection.get("style", ""))
        query_label = _cells(root, "connectionLabel")[0]
        self.assertIn("fontColor=#B85450", query_label.get("style", ""))

    def test_unconnected_query_has_red_endpoint_and_query_stereotype(self) -> None:
        provider = AutomatonObject("provider", QueryProvider, QueryContext())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "query_endpoint.drawio"
            export_program_drawio(Program(objects=(provider,)), output)
            root = ET.parse(output).getroot()

        endpoint = next(
            cell
            for cell in _cells(root, "operation")
            if cell.get("ciaoOperation") == "read"
        )
        label = next(
            cell
            for cell in _cells(root, "operationLabel")
            if cell.get("ciaoOperation") == "read"
        )
        self.assertIn("strokeColor=#B85450", endpoint.get("style", ""))
        self.assertEqual("«query»<br>read(scale=1)", label.get("value"))
        self.assertIn("scale: int=1", endpoint.get("ciaoSignature", ""))

    def test_actions_without_emit_are_compact_bottom_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        self.assertEqual([], _cells(root, "action"))
        actions = {
            cell.get("ciaoAction"): cell
            for cell in _cells(root, "actionLabel")
        }
        self.assertEqual(
            {
                "initialize",
                "add_current",
                "mark_running",
                "mark_completed",
                "reset_progress",
                "remember_start",
                "apply_snapshot",
            },
            set(actions),
        )
        self.assertNotIn("publish_snapshot", actions)
        self.assertIn("ctx", actions["initialize"].get("ciaoSignature", ""))
        self.assertEqual(
            "total += values[index]; index++; tick_count++",
            actions["add_current"].get("ciaoText"),
        )
        self.assertEqual(set(actions), {cell.get("value") for cell in actions.values()})

        blocks = _cells(root, "automaton")
        block_bottoms = {
            int(geometry.get("y", "0")) + int(geometry.get("height", "0"))
            for block in blocks
            if (geometry := block.find("mxGeometry")) is not None
        }
        for action in actions.values():
            geometry = action.find("mxGeometry")
            self.assertIn(
                int(geometry.get("y", "0"))
                + int(geometry.get("height", "0")),
                block_bottoms,
            )
            expected_width = max(32, len(action.get("value", "")) * 6)
            self.assertEqual(expected_width, int(geometry.get("width", "0")))

    def test_semantic_ids_survive_object_reordering(self) -> None:
        sample = build_sample()
        reordered = Program(
            objects=tuple(reversed(sample.program.objects)),
            connections=sample.program.connections,
        )

        def export_root(program: Program, directory: str, name: str) -> ET.Element:
            output = Path(directory) / name
            export_program_drawio(program, output)
            return ET.parse(output).getroot()

        def semantic_ids(root: ET.Element) -> set[str]:
            result: set[str] = set()
            for cell in root.findall(".//mxCell"):
                kind = cell.get("ciaoElement")
                if kind not in {
                    "automaton",
                    "state",
                    "exit",
                    "entry",
                    "action",
                    "connectionRequired",
                    "connectionProvided",
                }:
                    continue
                result.add(cell.get("id", ""))
            return result

        with tempfile.TemporaryDirectory() as directory:
            original_root = export_root(
                sample.program,
                directory,
                "original.drawio",
            )
            reordered_root = export_root(
                reordered,
                directory,
                "reordered.drawio",
            )

        self.assertEqual(
            semantic_ids(original_root),
            semantic_ids(reordered_root),
        )

    def test_block_sizes_are_content_driven_and_keep_program_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, root = self._export_sample(directory)

        blocks = _cells(root, "automaton")
        self.assertEqual(
            ["controller", "view"],
            [block.get("ciaoObject") for block in blocks],
        )
        geometries = [block.find("mxGeometry") for block in blocks]
        self.assertLess(
            int(geometries[0].get("x", "0")),
            int(geometries[1].get("x", "0")),
        )
        widths = [int(geometry.get("width", "0")) for geometry in geometries]
        self.assertTrue(all(width >= 650 for width in widths))
        # Длинная подпись перехода View учитывается до раскладки и расширяет
        # рамку сверх минимальной ширины, а не выступает за неё постфактум.
        self.assertGreater(widths[1], 650)

    def test_three_blocks_keep_order_and_connections_use_reserved_channels(self) -> None:
        program, _, _, _ = build_calculator_program()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calculator.drawio"
            export_program_drawio(program, output)
            root = ET.parse(output).getroot()

        blocks = _cells(root, "automaton")
        self.assertEqual(
            ["calculator", "operators", "view"],
            [block.get("ciaoObject") for block in blocks],
        )
        block_rectangles = []
        for block in blocks:
            geometry = block.find("mxGeometry")
            block_rectangles.append(
                (
                    int(geometry.get("x", "0")),
                    int(geometry.get("y", "0")),
                    int(geometry.get("width", "0")),
                    int(geometry.get("height", "0")),
                )
            )

        first_x, first_y, _, first_height = block_rectangles[0]
        second_x, second_y, _, _ = block_rectangles[1]
        third_x, third_y, _, _ = block_rectangles[2]
        self.assertLess(first_x, second_x)
        self.assertEqual(first_y, second_y)
        self.assertEqual(first_x, third_x)
        self.assertGreaterEqual(third_y, first_y + first_height)

        for half in _cells(root, "connectionRequired") + _cells(
            root,
            "connectionProvided",
        ):
            self.assertIn(
                "edgeStyle=orthogonalEdgeStyle",
                half.get("style", ""),
            )

        for label in _cells(root, "connectionLabel"):
            geometry = label.find("mxGeometry")
            label_rectangle = (
                int(geometry.get("x", "0")),
                int(geometry.get("y", "0")),
                int(geometry.get("width", "0")),
                int(geometry.get("height", "0")),
            )
            label_x, label_y, label_width, label_height = label_rectangle
            for block_x, block_y, block_width, block_height in block_rectangles:
                overlaps = not (
                    label_x + label_width <= block_x
                    or block_x + block_width <= label_x
                    or label_y + label_height <= block_y
                    or block_y + block_height <= label_y
                )
                self.assertFalse(
                    overlaps,
                    f"Подпись connection {label.get('value')} зашла на блок",
                )

    def test_initial_final_state_combines_entry_with_exit(self) -> None:
        object_ref = AutomatonObject("plain", PlainAutomaton, PlainContext())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "initial_final.drawio"
            export_program_drawio(Program(objects=(object_ref,)), output)
            root = ET.parse(output).getroot()

        initial_exit = next(
            cell
            for cell in _cells(root, "exit")
            if cell.get("ciaoInitial") == "true"
        )
        entry_edge = next(
            cell
            for cell in _cells(root, "entryTransition")
            if cell.get("ciaoState") == "only"
        )
        self.assertEqual(initial_exit.get("id"), entry_edge.get("target"))

    def test_outgoing_transition_from_final_state_is_preserved(self) -> None:
        class FinalOutgoingAutomaton(Automaton[QueryContext]):
            terminal = State(initial=True, final=True)
            resumed = State()

            @provided_command
            def resume(self) -> None:
                ...

            on_resume = transition(
                source=terminal,
                event=resume,
                target=resumed,
            )

        object_ref = AutomatonObject(
            "final_outgoing",
            FinalOutgoingAutomaton,
            QueryContext(),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "final_outgoing.drawio"
            export_program_drawio(Program(objects=(object_ref,)), output)
            root = ET.parse(output).getroot()

        terminal = next(
            cell
            for cell in _cells(root, "exit")
            if cell.get("ciaoState") == "terminal"
        )
        transition_cell = next(
            cell
            for cell in root.findall(".//mxCell")
            if cell.get("ciaoTransition") == "on_resume"
        )
        self.assertEqual(terminal.get("id"), transition_cell.get("source"))
        self.assertNotEqual(terminal.get("id"), transition_cell.get("target"))

    def test_export_is_deterministic_and_replaces_existing_file(self) -> None:
        sample = build_sample()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.drawio"
            second = Path(directory) / "second.drawio"
            first.write_text("старое содержимое", encoding="utf-8")
            export_program_drawio(sample.program, first)
            export_program_drawio(sample.program, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_export_accepts_explicit_layout_builder(self) -> None:
        sample = build_sample()
        descriptions = []

        def layout_builder(description):
            descriptions.append(description)
            return layout_diagram(description)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "custom-layout.drawio"
            export_program_drawio(
                sample.program,
                output,
                layout_builder=layout_builder,
            )

        self.assertEqual(1, len(descriptions))

    def test_serialization_error_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.drawio"
            output.write_text("исходный файл", encoding="utf-8")
            with patch(
                "ciao.visualization.drawio.serialize_drawio",
                side_effect=ValueError("ошибка сериализации"),
            ):
                with self.assertRaises(ValueError):
                    export_program_drawio(build_sample().program, output)
            self.assertEqual("исходный файл", output.read_text(encoding="utf-8"))

    def test_missing_parent_directory_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing" / "sample.drawio"
            with self.assertRaises(FileNotFoundError):
                export_program_drawio(build_sample().program, output)
            self.assertFalse(output.parent.exists())

    def test_roles_and_final_state_do_not_change_runtime_semantics(self) -> None:
        sample = build_sample()
        compiled = compile_program(sample.program)
        self.assertIs(AutomatonRole.CONTROLLER, compiled.definitions[SumController].role)
        self.assertIs(AutomatonRole.VIEW, compiled.definitions[SumView].role)
        self.assertIs(
            AutomatonRole.BASE,
            compile_program(
                Program(
                    objects=(
                        AutomatonObject("plain", PlainAutomaton, PlainContext()),
                    )
                )
            ).definitions[PlainAutomaton].role,
        )
        self.assertFalse(QueryProvider.read.external)
        self.assertTrue(SumView.init_clicked.external)
        self.assertTrue(SumView.render_data.external)
        external_required = required_command(external=True)
        self.assertTrue(callable(external_required))

        runtime = Runtime(sample.program)
        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((), CalculationMode.STEP_BY_STEP),
        )
        runtime.run()
        self.assertIs(
            SumController.completed,
            runtime.snapshot(sample.controller).state,
        )
        runtime.send(sample.view, SumView.reset_clicked)
        runtime.run()
        self.assertIs(SumController.idle, runtime.snapshot(sample.controller).state)

        runtime.send(
            sample.view,
            SumView.init_clicked,
            StartInput((), CalculationMode.RUN_TO_COMPLETION),
        )
        runtime.run()
        runtime.send(sample.view, SumView.finish_clicked)
        runtime.run()
        self.assertIs(SumController.done, runtime.snapshot(sample.controller).state)

    def test_role_cannot_be_reassigned_on_plain_automaton(self) -> None:
        class InvalidRole(Automaton[QueryContext]):
            role = AutomatonRole.VIEW
            ready = State(initial=True)

        object_ref = AutomatonObject("invalid", InvalidRole, QueryContext())
        with self.assertRaises(ModelValidationError):
            compile_program(Program(objects=(object_ref,)))


if __name__ == "__main__":
    unittest.main()
