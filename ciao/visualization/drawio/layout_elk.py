"""Экспериментальная компоновка графов состояний через Eclipse ELK.

Стратегия использует ``elkjs`` только как геометрический движок. Семантические
DTO, стили и сериализация остаются Python-компонентами draw.io-адаптера.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from html import escape
from math import ceil, hypot
from pathlib import Path
from typing import Any

from ciao.domain import OperationKind

from . import styles
from .diagram_model import (
    AutomatonView,
    DiagramDescription,
    DiagramPage,
    EdgeCell,
    NodeCell,
    Point,
    Rectangle as Rect,
)
from .layout import (
    PAGE_MARGIN_X,
    PAGE_MARGIN_Y,
    _label_dimensions,
    _operation_text_metadata,
    _side_towards,
)
from .layout_multiphase import layout_diagram_multiphase


ELK_GRAPH_LEFT_GAP = 24
ELK_GRAPH_TOP = 48
ELK_GRAPH_RIGHT = 20
ELK_GRAPH_BOTTOM = 50
ELK_FIXED_RIGHT_MARGIN = 30
ELK_DENSE_STATE_THRESHOLD = 4
ELK_DENSE_LABEL_WIDTH_THRESHOLD = 320
ELK_DENSE_GRAPH_LEFT = 8
ELK_DENSE_CONTEXT_GAP = 12
ELK_TIMEOUT_SECONDS = 30


class ElkLayoutError(RuntimeError):
    """Ошибка запуска или ответа экспериментального ELK layout."""


class ElkUnavailableError(ElkLayoutError):
    """Node.js или закреплённый пакет elkjs недоступен."""


@dataclass(frozen=True)
class _ElkBlockResult:
    graph: dict[str, Any]
    width: int
    height: int


def _runner_path() -> Path:
    return Path(__file__).with_name("elk_runner.cjs")


def _run_elk_graphs(
    graphs: list[dict[str, Any]],
    *,
    node_executable: str,
) -> list[dict[str, Any]]:
    executable = shutil.which(node_executable)
    if executable is None:
        raise ElkUnavailableError(
            f"Не найден исполняемый файл Node.js: {node_executable!r}."
        )
    try:
        completed = subprocess.run(
            [executable, str(_runner_path())],
            input=json.dumps({"graphs": graphs}, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=ELK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ElkLayoutError(
            f"ELK не завершил компоновку за {ELK_TIMEOUT_SECONDS} секунд."
        ) from error
    if completed.returncode != 0:
        details = completed.stderr.strip() or "неизвестная ошибка elkjs"
        if "Cannot find module" in details and "elkjs" in details:
            raise ElkUnavailableError(
                "Не найден пакет elkjs. Выполните `npm install` в корне проекта."
            )
        raise ElkLayoutError(f"elkjs завершился с ошибкой: {details}")
    try:
        payload = json.loads(completed.stdout)
        results = payload["graphs"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ElkLayoutError("elkjs вернул некорректный JSON-ответ.") from error
    if not isinstance(results, list) or len(results) != len(graphs):
        raise ElkLayoutError("elkjs вернул неожиданное число результатов.")
    return results


def _block_node_ids(block: AutomatonView, template: DiagramPage) -> set[str]:
    identifiers = {block.id, f"{block.id}-context", f"{block.id}-title"}
    for state in block.states:
        identifiers.update(
            (state.id, f"{state.id}-entry", f"{state.id}-label")
        )
    for action in block.actions:
        identifiers.update(
            (
                f"{action.id}-label",
                f"{action.id}-interface-base",
                f"{action.id}-interface-tip",
            )
        )
    for operation in block.operations:
        identifiers.update((operation.id, f"{operation.id}-label"))
    identifiers.update(
        node.id
        for node in template.nodes
        if node.id.startswith(f"{block.id}-decision-")
    )
    return identifiers


def _internal_node_ids(block: AutomatonView, template: DiagramPage) -> set[str]:
    identifiers = {state.id for state in block.states}
    identifiers.update(
        f"{state.id}-entry" for state in block.states if state.state.initial
    )
    identifiers.update(
        node.id
        for node in template.nodes
        if node.id.startswith(f"{block.id}-decision-")
    )
    return identifiers


def _elk_options() -> dict[str, str]:
    return {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.padding": "[top=12,left=12,bottom=12,right=12]",
        "elk.spacing.nodeNode": "16",
        "elk.layered.spacing.nodeNodeBetweenLayers": "36",
        "elk.spacing.edgeNode": "8",
        "elk.spacing.edgeEdge": "4",
        "elk.spacing.edgeLabel": "4",
        "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
        "elk.layered.nodePlacement.favorStraightEdges": "true",
        "elk.layered.mergeEdges": "false",
        "elk.layered.mergeHierarchyEdges": "false",
        "elk.layered.edgeLabels.inline": "false",
        "elk.aspectRatio": "1.6",
    }


def _compact_transition_label(label: str) -> str:
    """Сохраняет структуру перехода, убирая длинные пояснения из рисунка."""

    compact = re.sub(r"\[([^:\]<]+):[^\]]+\]", r"[\1]", label)
    compact = re.sub(
        r"<b>([^:<]+):</b>[^<]*(?=<br>|$)",
        r"<b>\1</b>",
        compact,
    )
    compact = re.sub(
        r"(<span[^>]*>)([A-Za-z_]\w*)\([^)]*\)(</span>)",
        r"\1\2(&#8230;)\3",
        compact,
    )
    return re.sub(
        r"\b([A-Za-z_]\w*)\(([^)]{20,})\)",
        r"\1(&#8230;)",
        compact,
    )


def _uses_stacked_dense_graph(
    block: AutomatonView,
    template: DiagramPage,
) -> bool:
    transition_ids = {transition.id for transition in block.transitions}
    max_label_width = max(
        (
            edge.label_width or 0
            for edge in template.edges
            if edge.id in transition_ids
        ),
        default=0,
    )
    return (
        len(block.states) >= ELK_DENSE_STATE_THRESHOLD
        and max_label_width >= ELK_DENSE_LABEL_WIDTH_THRESHOLD
    )


def _build_elk_graph(
    block: AutomatonView,
    template: DiagramPage,
) -> dict[str, Any]:
    nodes = {node.id: node for node in template.nodes}
    internal_ids = _internal_node_ids(block, template)
    compact_labels = _uses_stacked_dense_graph(block, template)
    children: list[dict[str, Any]] = []
    for identifier in sorted(internal_ids):
        node = nodes[identifier]
        if node.kind == "exit":
            width, height = 120, 58
        else:
            width, height = node.geometry.width, node.geometry.height
        child: dict[str, Any] = {
            "id": identifier,
            "width": width,
            "height": height,
        }
        if node.kind == "entry":
            child["layoutOptions"] = {
                "elk.layered.layering.layerConstraint": "FIRST"
            }
        children.append(child)

    edges: list[dict[str, Any]] = []
    for edge in template.edges:
        if edge.source_id not in internal_ids or edge.target_id not in internal_ids:
            continue
        elk_edge: dict[str, Any] = {
            "id": edge.id,
            "sources": [edge.source_id],
            "targets": [edge.target_id],
        }
        if (
            edge.label
            and edge.label_width is not None
            and edge.label_height is not None
        ):
            display_label = (
                _compact_transition_label(edge.label)
                if compact_labels
                else edge.label
            )
            label_width, label_height = _label_dimensions(display_label)
            elk_edge["labels"] = [
                {
                    "id": f"{edge.id}-label",
                    "text": display_label,
                    "width": label_width,
                    "height": label_height,
                }
            ]
        edges.append(elk_edge)
    return {
        "id": block.id,
        "layoutOptions": _elk_options(),
        "children": children,
        "edges": edges,
    }


def _edge_points(edge: dict[str, Any], origin: Point) -> tuple[Point, ...]:
    points: list[Point] = []
    for section in edge.get("sections", ()):
        section_points = (
            section.get("startPoint"),
            *section.get("bendPoints", ()),
            section.get("endPoint"),
        )
        for item in section_points:
            if item is None:
                continue
            point = Point(origin.x + round(item["x"]), origin.y + round(item["y"]))
            if not points or points[-1] != point:
                points.append(point)
    return tuple(points)


def _nearest_path_anchor(
    path: tuple[Point, ...],
    target: Point,
) -> tuple[Point, float]:
    segments: list[tuple[float, Point, Point]] = []
    total = 0.0
    for first, second in zip(path, path[1:]):
        length = hypot(second.x - first.x, second.y - first.y)
        segments.append((length, first, second))
        total += length
    best_distance = float("inf")
    best_point = path[0]
    best_progress = 0.0
    traversed = 0.0
    for length, first, second in segments:
        if length == 0:
            continue
        dx = second.x - first.x
        dy = second.y - first.y
        ratio = (
            (target.x - first.x) * dx + (target.y - first.y) * dy
        ) / (length * length)
        ratio = min(1.0, max(0.0, ratio))
        candidate = Point(
            round(first.x + ratio * dx),
            round(first.y + ratio * dy),
        )
        distance = hypot(target.x - candidate.x, target.y - candidate.y)
        if distance < best_distance:
            best_distance = distance
            best_point = candidate
            best_progress = traversed + ratio * length
        traversed += length
    position = round(2 * best_progress / total - 1, 4) if total else 0.0
    return best_point, position


def _label_placement(
    elk_edge: dict[str, Any],
    path: tuple[Point, ...],
    origin: Point,
) -> tuple[float | None, Point | None, int | None, int | None]:
    labels = elk_edge.get("labels", ())
    if not labels or len(path) < 2:
        return None, None, None, None
    label = labels[0]
    width = round(label["width"])
    height = round(label["height"])
    center = Point(
        origin.x + round(label["x"] + label["width"] / 2),
        origin.y + round(label["y"] + label["height"] / 2),
    )
    anchor, position = _nearest_path_anchor(path, center)
    return (
        position,
        Point(center.x - anchor.x, center.y - anchor.y),
        width,
        height,
    )


def _build_elk_program_graph(
    description: DiagramDescription,
    block_results: dict[str, _ElkBlockResult],
) -> dict[str, Any]:
    owners = {
        operation.id: block.id
        for block in description.blocks
        for operation in block.operations
    }
    edges: list[dict[str, Any]] = []
    for connection in description.connections:
        label_width, label_height = _label_dimensions(escape(connection.label))
        edges.append(
            {
                "id": connection.id,
                "sources": [owners[connection.required_endpoint_id]],
                "targets": [owners[connection.provided_endpoint_id]],
                "labels": [
                    {
                        "id": f"{connection.id}-label",
                        "text": connection.label,
                        "width": max(60, label_width),
                        "height": label_height,
                    }
                ],
            }
        )
    options = _elk_options()
    options.update(
        {
            "elk.spacing.nodeNode": "40",
            "elk.layered.spacing.nodeNodeBetweenLayers": "64",
            "elk.spacing.edgeNode": "20",
            "elk.spacing.edgeEdge": "8",
            "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
            "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
        }
    )
    children = [
        {
            "id": block.id,
            "width": block_results[block.id].width,
            "height": block_results[block.id].height,
        }
        for block in description.blocks
    ]
    if children:
        # На циклической схеме ELK вправе развернуть граф целиком. Крайние
        # ограничения сохраняют читаемый порядок Program.objects, не задавая
        # вручную координаты промежуточных автоматов.
        children[0]["layoutOptions"] = {
            "elk.layered.layering.layerConstraint": "FIRST"
        }
        if len(children) > 1:
            children[-1]["layoutOptions"] = {
                "elk.layered.layering.layerConstraint": "LAST"
            }
    return {
        "id": "ciao-program",
        "layoutOptions": options,
        "children": children,
        "edges": edges,
    }


def _point_at_fraction(path: tuple[Point, ...], fraction: float) -> Point:
    lengths = [
        hypot(second.x - first.x, second.y - first.y)
        for first, second in zip(path, path[1:])
    ]
    target = sum(lengths) * fraction
    traversed = 0.0
    for length, first, second in zip(lengths, path, path[1:]):
        if traversed + length >= target and length:
            ratio = (target - traversed) / length
            return Point(
                round(first.x + ratio * (second.x - first.x)),
                round(first.y + ratio * (second.y - first.y)),
            )
        traversed += length
    return path[-1]


def _split_path(
    path: tuple[Point, ...],
    junction: Point,
) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    lengths = [
        hypot(second.x - first.x, second.y - first.y)
        for first, second in zip(path, path[1:])
    ]
    target = sum(lengths) / 2
    traversed = 0.0
    split_index = 1
    for index, length in enumerate(lengths):
        if traversed + length >= target:
            split_index = index + 1
            break
        traversed += length
    required = (*path[:split_index], junction)
    provided = tuple(reversed((junction, *path[split_index:])))
    return required, provided


def _side_and_offset(block: Rect, point: Point) -> tuple[str, float]:
    distances = {
        "left": abs(point.x - block.x),
        "right": abs(point.x - (block.x + block.width)),
        "top": abs(point.y - block.y),
        "bottom": abs(point.y - (block.y + block.height)),
    }
    side = min(distances, key=distances.get)
    if side in {"left", "right"}:
        value = (point.y - block.y) / block.height if block.height else 0.5
    else:
        value = (point.x - block.x) / block.width if block.width else 0.5
    return side, round(min(0.92, max(0.08, value)), 3)


def _append_elk_connections(
    description: DiagramDescription,
    program_layout: dict[str, Any],
    block_geometries: dict[str, Rect],
    nodes: list[NodeCell],
    edges: list[EdgeCell],
    origin: Point,
) -> None:
    operation_owners = {
        operation.id: block.id
        for block in description.blocks
        for operation in block.operations
    }
    operation_views = {
        operation.id: operation
        for block in description.blocks
        for operation in block.operations
    }
    layouts = {item["id"]: item for item in program_layout.get("edges", ())}
    for connection in description.connections:
        layout = layouts[connection.id]
        path = _edge_points(layout, origin)
        if len(path) < 2:
            required_owner = operation_owners[connection.required_endpoint_id]
            provided_owner = operation_owners[connection.provided_endpoint_id]
            path = (
                Point(
                    block_geometries[required_owner].x
                    + block_geometries[required_owner].width // 2,
                    block_geometries[required_owner].y
                    + block_geometries[required_owner].height // 2,
                ),
                Point(
                    block_geometries[provided_owner].x
                    + block_geometries[provided_owner].width // 2,
                    block_geometries[provided_owner].y
                    + block_geometries[provided_owner].height // 2,
                ),
            )
        junction = _point_at_fraction(path, 0.5)
        required_path, provided_path = _split_path(path, junction)
        junction_id = f"{connection.id}-junction"
        junction_geometry = Rect(junction.x - 5, junction.y - 5, 10, 10)
        label_layouts = layout.get("labels", ())
        if label_layouts:
            label_layout = label_layouts[0]
            label_geometry = Rect(
                origin.x + round(label_layout["x"]),
                origin.y + round(label_layout["y"]),
                round(label_layout["width"]),
                round(label_layout["height"]),
            )
        else:
            label_width, label_height = _label_dimensions(escape(connection.label))
            label_geometry = Rect(
                junction.x - label_width // 2,
                junction.y - label_height - 10,
                label_width,
                label_height,
            )
        nodes.extend(
            (
                NodeCell(
                    id=junction_id,
                    label="",
                    style=styles.CONNECTION_JUNCTION,
                    geometry=junction_geometry,
                    kind="connectionJunction",
                    metadata=(("ciaoConnection", connection.id),),
                ),
                NodeCell(
                    id=f"{connection.id}-label",
                    label=escape(connection.label),
                    style=styles.connection_label_style(
                        styles.QUERY_STROKE
                        if connection.kind is OperationKind.QUERY
                        else "#000000"
                    ),
                    geometry=label_geometry,
                    kind="connectionLabel",
                    metadata=(("ciaoConnection", connection.id),),
                ),
            )
        )
        required_owner = operation_owners[connection.required_endpoint_id]
        provided_owner = operation_owners[connection.provided_endpoint_id]
        for suffix, owner_id, operation_view, required, half_path in (
            (
                "required",
                required_owner,
                operation_views[connection.required_endpoint_id],
                True,
                required_path,
            ),
            (
                "provided",
                provided_owner,
                operation_views[connection.provided_endpoint_id],
                False,
                provided_path,
            ),
        ):
            side, exit_offset = _side_and_offset(
                block_geometries[owner_id], half_path[0]
            )
            operation = operation_view.operation
            edges.append(
                EdgeCell(
                    id=f"{connection.id}-{suffix}",
                    label="",
                    style=styles.connection_half_style(
                        required=required,
                        exit_side=side,
                        exit_offset=exit_offset,
                        stroke=(
                            styles.QUERY_STROKE
                            if connection.kind is OperationKind.QUERY
                            else "#000000"
                        ),
                    ),
                    source_id=owner_id,
                    target_id=junction_id,
                    points=half_path,
                    kind=f"connection{suffix.capitalize()}",
                    metadata=(
                        ("ciaoConnection", connection.id),
                        ("ciaoOperation", operation.name),
                        ("ciaoDirection", operation.direction.value),
                        ("ciaoKind", operation.kind.value),
                        ("ciaoSignature", operation_view.label),
                        *_operation_text_metadata(operation),
                    ),
                )
            )


def _translate_template_node(
    node: NodeCell,
    old_block: Rect,
    new_block: Rect,
) -> NodeCell:
    dx = new_block.x - old_block.x
    dy = new_block.y - old_block.y
    width_growth = new_block.width - old_block.width
    height_growth = new_block.height - old_block.height
    geometry = node.geometry
    if node.kind == "automaton":
        geometry = new_block
    elif node.kind == "automatonTitle":
        geometry = replace(
            geometry,
            x=geometry.x + dx,
            y=geometry.y + dy,
            width=geometry.width + width_growth,
        )
    else:
        bottom_anchored = geometry.y >= old_block.y + old_block.height - 90
        geometry = replace(
            geometry,
            x=geometry.x + dx,
            y=geometry.y + dy + (height_growth if bottom_anchored else 0),
        )
        if geometry.y < new_block.y and node.kind in {
            "operation",
            "operationLabel",
        }:
            # Внешний endpoint обязан лишь касаться верхней рамки. Округление
            # высоты подписи не должно заводить её внутрь context-card на 1 px.
            geometry = replace(
                geometry,
                y=min(geometry.y, new_block.y - geometry.height),
            )
    return replace(node, geometry=geometry)


def _layout_block_nodes(
    *,
    block: AutomatonView,
    template: DiagramPage,
    old_block: Rect,
    new_block: Rect,
    elk_result: dict[str, Any],
) -> tuple[list[NodeCell], list[EdgeCell]]:
    template_nodes = {node.id: node for node in template.nodes}
    template_edges = {edge.id: edge for edge in template.edges}
    owned_ids = _block_node_ids(block, template)
    internal_ids = _internal_node_ids(block, template)
    context_geometry = template_nodes[f"{block.id}-context"].geometry
    if _uses_stacked_dense_graph(block, template):
        graph_origin = Point(
            new_block.x + ELK_DENSE_GRAPH_LEFT,
            new_block.y
            + context_geometry.height
            + ELK_DENSE_CONTEXT_GAP,
        )
    else:
        graph_origin = Point(
            new_block.x + context_geometry.width + ELK_GRAPH_LEFT_GAP,
            new_block.y + ELK_GRAPH_TOP,
        )
    elk_nodes = {item["id"]: item for item in elk_result.get("children", ())}
    result_nodes: list[NodeCell] = []
    mapped_geometries: dict[str, Rect] = {}
    # Порядок mxCell является порядком слоёв draw.io. Сортировка по id ставила
    # actionLabel раньше рамки object-* и рамка визуально закрывала подписи,
    # хотя они продолжали присутствовать в XML.
    for node in template.nodes:
        identifier = node.id
        if identifier not in owned_ids:
            continue
        if identifier.endswith("-label") and node.kind == "exitLabel":
            continue
        if identifier in internal_ids:
            item = elk_nodes[identifier]
            if node.kind == "exit":
                box_width = round(item["width"])
                box_height = round(item["height"])
                geometry = Rect(
                    graph_origin.x + round(item["x"]) + box_width // 2 - 15,
                    graph_origin.y + round(item["y"]) + box_height - 32,
                    30,
                    30,
                )
            else:
                geometry = Rect(
                    graph_origin.x + round(item["x"]),
                    graph_origin.y + round(item["y"]),
                    node.geometry.width,
                    node.geometry.height,
                )
            mapped = replace(node, geometry=geometry)
        else:
            mapped = _translate_template_node(node, old_block, new_block)
        result_nodes.append(mapped)
        mapped_geometries[identifier] = mapped.geometry

    for state in block.states:
        if not state.state.final:
            continue
        label_id = f"{state.id}-label"
        label = template_nodes.get(label_id)
        state_geometry = mapped_geometries[state.id]
        if label is None:
            continue
        label_geometry = Rect(
            state_geometry.x + state_geometry.width // 2 - label.geometry.width // 2,
            state_geometry.y - label.geometry.height,
            label.geometry.width,
            label.geometry.height,
        )
        result_nodes.append(replace(label, geometry=label_geometry))
        mapped_geometries[label_id] = label_geometry

    elk_edges = {item["id"]: item for item in elk_result.get("edges", ())}
    result_edges: list[EdgeCell] = []
    for identifier, elk_edge in elk_edges.items():
        template_edge = template_edges[identifier]
        points = _edge_points(elk_edge, graph_origin)
        full_path = (
            Point(
                mapped_geometries[template_edge.source_id].x
                + mapped_geometries[template_edge.source_id].width // 2,
                mapped_geometries[template_edge.source_id].y
                + mapped_geometries[template_edge.source_id].height // 2,
            ),
            *points,
            Point(
                mapped_geometries[template_edge.target_id].x
                + mapped_geometries[template_edge.target_id].width // 2,
                mapped_geometries[template_edge.target_id].y
                + mapped_geometries[template_edge.target_id].height // 2,
            ),
        )
        position, offset, width, height = _label_placement(
            elk_edge, full_path, graph_origin
        )
        display_label = (
            elk_edge["labels"][0]["text"]
            if elk_edge.get("labels")
            else template_edge.label
        )
        metadata = template_edge.metadata
        if display_label != template_edge.label:
            metadata = (*metadata, ("ciaoFullLabel", template_edge.label))
        result_edges.append(
            replace(
                template_edge,
                label=display_label,
                points=points,
                label_position=position,
                label_offset=offset,
                label_width=width,
                label_height=height,
                metadata=metadata,
            )
        )
    result_edges.extend(
        edge
        for edge in template.edges
        if edge.kind == "actionInterface"
        and edge.source_id in owned_ids
        and edge.target_id in owned_ids
    )
    return result_nodes, result_edges


def layout_diagram_elk(
    description: DiagramDescription,
    *,
    node_executable: str = "node",
) -> DiagramPage:
    """Строит DiagramPage, поручая внутренние графы ELK Layered."""

    if not description.blocks:
        return DiagramPage((), (), 2 * PAGE_MARGIN_X, 2 * PAGE_MARGIN_Y)
    template = layout_diagram_multiphase(description)
    template_nodes = {node.id: node for node in template.nodes}
    old_blocks = {
        block.id: template_nodes[block.id].geometry for block in description.blocks
    }
    elk_graphs = [_build_elk_graph(block, template) for block in description.blocks]
    elk_results = _run_elk_graphs(elk_graphs, node_executable=node_executable)
    block_results: dict[str, _ElkBlockResult] = {}
    for block, elk_result in zip(description.blocks, elk_results):
        old = old_blocks[block.id]
        context_width = template_nodes[f"{block.id}-context"].geometry.width
        internal_ids = _internal_node_ids(block, template)
        owned_ids = _block_node_ids(block, template)
        fixed_right = max(
            (
                node.geometry.x + node.geometry.width - old.x
                for node in template.nodes
                if node.id in owned_ids
                and node.id not in internal_ids
                and node.kind not in {"automaton", "exitLabel"}
            ),
            default=0,
        )
        # Multiphase здесь служит семантическим шаблоном, но не нижней границей
        # размера: иначе простые автоматы наследуют его пустые строки и каналы.
        # Реальный минимум задают ELK-граф и неподвижная нижняя полоса подписей.
        elk_width = ceil(float(elk_result.get("width", 0)))
        elk_height = ceil(float(elk_result.get("height", 0)))
        if _uses_stacked_dense_graph(block, template):
            context_height = template_nodes[
                f"{block.id}-context"
            ].geometry.height
            width = max(
                fixed_right + ELK_FIXED_RIGHT_MARGIN,
                context_width + ELK_FIXED_RIGHT_MARGIN,
                ELK_DENSE_GRAPH_LEFT + elk_width + ELK_GRAPH_RIGHT,
            )
            height = (
                context_height
                + ELK_DENSE_CONTEXT_GAP
                + elk_height
                + ELK_GRAPH_BOTTOM
            )
        else:
            width = max(
                fixed_right + ELK_FIXED_RIGHT_MARGIN,
                context_width
                + ELK_GRAPH_LEFT_GAP
                + elk_width
                + ELK_GRAPH_RIGHT,
            )
            height = ELK_GRAPH_TOP + elk_height + ELK_GRAPH_BOTTOM
        block_results[block.id] = _ElkBlockResult(elk_result, width, height)
    program_layout = _run_elk_graphs(
        [_build_elk_program_graph(description, block_results)],
        node_executable=node_executable,
    )[0]
    program_origin = Point(PAGE_MARGIN_X, PAGE_MARGIN_Y)
    program_nodes = {
        item["id"]: item for item in program_layout.get("children", ())
    }

    nodes: list[NodeCell] = []
    edges: list[EdgeCell] = []
    new_blocks: dict[str, Rect] = {}
    for block in description.blocks:
        result = block_results[block.id]
        placement = program_nodes[block.id]
        new_block = Rect(
            program_origin.x + round(placement["x"]),
            program_origin.y + round(placement["y"]),
            result.width,
            result.height,
        )
        new_blocks[block.id] = new_block
        block_nodes, block_edges = _layout_block_nodes(
            block=block,
            template=template,
            old_block=old_blocks[block.id],
            new_block=new_block,
            elk_result=result.graph,
        )
        nodes.extend(block_nodes)
        edges.extend(block_edges)
    _append_elk_connections(
        description,
        program_layout,
        new_blocks,
        nodes,
        edges,
        program_origin,
    )
    width = PAGE_MARGIN_X * 2 + ceil(float(program_layout.get("width", 0)))
    height = PAGE_MARGIN_Y * 2 + ceil(float(program_layout.get("height", 0)))
    return DiagramPage(tuple(nodes), tuple(edges), width, height)


__all__ = ["ElkLayoutError", "ElkUnavailableError", "layout_diagram_elk"]
