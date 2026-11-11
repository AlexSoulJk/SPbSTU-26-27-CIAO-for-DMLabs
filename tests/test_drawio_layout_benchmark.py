"""Проверки экспериментального layout и общей геометрической метрики."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from ciao.infrastructure import compile_program
from ciao.visualization.drawio.benchmark import (
    benchmark_layouts,
    benchmark_layouts_with_elk,
)
from ciao.visualization.drawio.builder import build_diagram
from ciao.visualization.drawio.diagram_model import (
    DiagramPage,
    EdgeCell,
    NodeCell,
    Point,
    Rectangle,
)
from ciao.visualization.drawio.layout_multiphase import (
    layout_diagram_multiphase,
)
from ciao.visualization.drawio.layout_elk import (
    ElkUnavailableError,
    layout_diagram_elk,
)
from ciao.visualization.drawio.metrics import evaluate_layout
from examples.array_sum.program import build_sample
from examples.calculator.program import build_calculator_program


_NODE_STYLE = "rounded=1;"
_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;"


def _node(identifier: str, x: int, y: int) -> NodeCell:
    return NodeCell(
        id=identifier,
        label=identifier,
        style=_NODE_STYLE,
        geometry=Rectangle(x, y, 20, 20),
        kind="state",
    )


def _assert_normalized_bottom_fence(
    testcase: unittest.TestCase,
    description: object,
    page: DiagramPage,
) -> None:
    """Проверяет порядок «значок — подпись» у нижней границы автоматов."""

    nodes = {node.id: node for node in page.nodes}
    edges = {edge.id: edge for edge in page.edges}
    for block in description.blocks:
        block_geometry = nodes[block.id].geometry
        for action_view in block.actions:
            label = nodes.get(f"{action_view.id}-label")
            interface_id = f"{action_view.id}-interface"
            interface = edges.get(interface_id)
            base = nodes.get(f"{interface_id}-base")
            tip = nodes.get(f"{interface_id}-tip")
            if (
                label is None
                or interface is None
                or base is None
                or tip is None
            ):
                continue
            base_center_x = base.geometry.x + base.geometry.width // 2
            tip_center_x = tip.geometry.x + tip.geometry.width // 2
            base_center_y = base.geometry.y + base.geometry.height // 2
            tip_center_y = tip.geometry.y + tip.geometry.height // 2
            testcase.assertEqual(base_center_x, tip_center_x)
            testcase.assertEqual(24, base_center_y - tip_center_y)
            testcase.assertEqual(
                14,
                label.geometry.x - base_center_x,
            )
            testcase.assertEqual(
                block_geometry.y + block_geometry.height,
                base_center_y,
            )
            testcase.assertIn("endArrow=halfCircle", interface.style)
            testcase.assertNotIn("rotation=", interface.style)

        for operation_view in block.operations:
            operation = nodes.get(operation_view.id)
            label = nodes.get(f"{operation_view.id}-label")
            if operation is None or label is None:
                continue
            if operation.geometry.y + operation.geometry.height != (
                block_geometry.y + block_geometry.height
            ):
                continue
            testcase.assertEqual(
                6,
                label.geometry.x
                - operation.geometry.x
                - operation.geometry.width,
            )


class DrawioLayoutBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.description = build_diagram(compile_program(build_sample().program))

    def test_multiphase_layout_is_deterministic(self) -> None:
        first = layout_diagram_multiphase(self.description)
        second = layout_diagram_multiphase(self.description)

        self.assertEqual(first, second)
        blocks = {node.id: node for node in first.nodes if node.kind == "automaton"}
        contexts = [node for node in first.nodes if node.kind == "context"]
        self.assertEqual(2, len(contexts))
        for context in contexts:
            owner_id = context.id.removesuffix("-context")
            self.assertEqual(blocks[owner_id].geometry.x, context.geometry.x)
            self.assertEqual(blocks[owner_id].geometry.y, context.geometry.y)
            self.assertIn("Поля контекста", context.label)
        self.assertFalse(any(node.kind == "automatonTitle" for node in first.nodes))
        interfaces = [
            edge for edge in first.edges if edge.kind == "actionInterface"
        ]
        self.assertEqual(5, len(interfaces))
        for interface in interfaces:
            self.assertIn("endArrow=halfCircle", interface.style)
            self.assertIn("strokeWidth=2.3", interface.style)
            self.assertNotIn("rotation=", interface.style)
        _assert_normalized_bottom_fence(self, self.description, first)

    def test_benchmark_uses_the_same_metric_for_both_strategies(self) -> None:
        result, baseline, multiphase = benchmark_layouts(self.description)

        self.assertEqual(evaluate_layout(baseline), result.baseline.metrics)
        self.assertEqual(evaluate_layout(multiphase), result.multiphase.metrics)
        self.assertLess(
            result.multiphase.metrics.edge_overlap_ratio,
            result.baseline.metrics.edge_overlap_ratio,
        )

    def test_elk_reports_missing_node_executable(self) -> None:
        with self.assertRaisesRegex(ElkUnavailableError, "Node.js"):
            layout_diagram_elk(
                self.description,
                node_executable="definitely-missing-node-executable",
            )

    @unittest.skipUnless(
        shutil.which("node") is not None and Path("node_modules/elkjs").exists(),
        "для интеграционной проверки требуется npm install",
    )
    def test_elk_strategy_removes_overlaps_on_array_sum(self) -> None:
        result, _, multiphase_page, elk_page = benchmark_layouts_with_elk(
            self.description
        )

        self.assertIsNotNone(result.elk)
        assert result.elk is not None
        self.assertEqual(0, result.elk.metrics.object_overlap_pairs)
        self.assertEqual(0, result.elk.metrics.edge_crossings)
        self.assertEqual(0, result.elk.metrics.label_edge_intersections)
        self.assertEqual(0.0, result.elk.metrics.edge_overlap_ratio)
        self.assertEqual(elk_page, layout_diagram_elk(self.description))
        blocks = {
            node.id: node for node in elk_page.nodes if node.kind == "automaton"
        }
        first, last = self.description.blocks[0], self.description.blocks[-1]
        self.assertLess(blocks[first.id].geometry.x, blocks[last.id].geometry.x)
        contexts = {
            node.id.removesuffix("-context"): node
            for node in elk_page.nodes
            if node.kind == "context"
        }
        for block_id, block_node in blocks.items():
            self.assertEqual(block_node.geometry.x, contexts[block_id].geometry.x)
            self.assertEqual(block_node.geometry.y, contexts[block_id].geometry.y)
        interfaces = [
            edge for edge in elk_page.edges if edge.kind == "actionInterface"
        ]
        self.assertEqual(5, len(interfaces))
        _assert_normalized_bottom_fence(self, self.description, elk_page)
        controller = blocks[self.description.blocks[0].id]
        self.assertLessEqual(controller.geometry.width, 1120)
        self.assertLessEqual(elk_page.height, 750)
        node_indices = {
            node.id: index for index, node in enumerate(elk_page.nodes)
        }
        for block in self.description.blocks:
            for action_view in block.actions:
                label_id = f"{action_view.id}-label"
                if label_id in node_indices:
                    self.assertLess(node_indices[block.id], node_indices[label_id])
        self.assertLess(elk_page.height, multiphase_page.height)

    @unittest.skipUnless(
        shutil.which("node") is not None and Path("node_modules/elkjs").exists(),
        "для интеграционной проверки требуется npm install",
    )
    def test_elk_compacts_dense_calculator_controller(self) -> None:
        program = build_calculator_program()[0]
        description = build_diagram(compile_program(program))
        result, baseline_page, _, elk_page = benchmark_layouts_with_elk(
            description
        )

        controller = next(
            node
            for node in elk_page.nodes
            if node.kind == "automaton"
            and dict(node.metadata).get("ciaoObject") == "calculator"
        )
        self.assertLessEqual(controller.geometry.width, 850)
        self.assertLess(elk_page.width, baseline_page.width)
        self.assertLess(elk_page.height, baseline_page.height)
        assert result.elk is not None
        self.assertEqual(0, result.elk.metrics.object_overlap_pairs)
        self.assertEqual(0, result.elk.metrics.edge_crossings)
        self.assertEqual(0, result.elk.metrics.label_edge_intersections)

        compact = next(
            edge
            for edge in elk_page.edges
            if dict(edge.metadata).get("ciaoTransition") == "on_convert_token"
        )
        metadata = dict(compact.metadata)
        self.assertIn("classify_token(&#8230;)", compact.label)
        self.assertNotIn("Есть необработанный", compact.label)
        self.assertIn("Есть необработанный", metadata["ciaoFullLabel"])

    def test_edge_overlap_is_normalized_by_total_arrow_length(self) -> None:
        nodes = (
            _node("a", 0, 0),
            _node("b", 100, 0),
            _node("c", 0, 40),
            _node("d", 100, 40),
        )
        edges = (
            EdgeCell("e1", "", _EDGE_STYLE, "a", "b", (), "transition"),
            EdgeCell(
                "e2",
                "",
                _EDGE_STYLE,
                "a",
                "b",
                (),
                "transition",
            ),
            EdgeCell("e3", "", _EDGE_STYLE, "c", "d", (), "transition"),
        )
        metrics = evaluate_layout(DiagramPage(nodes, edges, 140, 80))

        self.assertAlmostEqual(2 / 3, metrics.edge_overlap_ratio, places=6)

    def test_label_on_arrow_is_worse_than_nearby_label(self) -> None:
        nodes = (_node("a", 0, 0), _node("b", 100, 0))
        common = dict(
            id="edge",
            label="tick()",
            style=_EDGE_STYLE,
            source_id="a",
            target_id="b",
            points=(),
            kind="transition",
            label_position=0.0,
            label_width=40,
            label_height=20,
        )
        on_arrow = EdgeCell(**common, label_offset=Point(0, 0))
        nearby = EdgeCell(**common, label_offset=Point(0, 24))
        on_metrics = evaluate_layout(DiagramPage(nodes, (on_arrow,), 140, 80))
        nearby_metrics = evaluate_layout(DiagramPage(nodes, (nearby,), 140, 80))

        self.assertEqual(1, on_metrics.label_own_edge_intersections)
        self.assertEqual(0, nearby_metrics.label_own_edge_intersections)
        self.assertGreater(on_metrics.quality_penalty, nearby_metrics.quality_penalty)

    def test_edge_touching_object_border_is_not_an_overlap(self) -> None:
        nodes = (
            _node("a", 0, 0),
            _node("b", 100, 0),
            NodeCell(
                id="caption",
                label="caption",
                style=_NODE_STYLE,
                geometry=Rectangle(40, 20, 40, 20),
                kind="actionLabel",
            ),
        )
        edge = EdgeCell(
            "edge",
            "",
            _EDGE_STYLE,
            "a",
            "b",
            (Point(40, 0), Point(40, 40), Point(100, 40)),
            "transition",
        )

        metrics = evaluate_layout(DiagramPage(nodes, (edge,), 140, 80))

        self.assertEqual(0, metrics.edge_object_intersections)
        self.assertEqual(0.0, metrics.edge_object_overlap_ratio)


if __name__ == "__main__":
    unittest.main()
