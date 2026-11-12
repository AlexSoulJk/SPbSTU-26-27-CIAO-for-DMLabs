"""Экспериментальная многофазная компоновка draw.io-диаграммы.

Модуль намеренно не подключён к публичному ``export_program_drawio``: текущая
двухстадийная стратегия остаётся baseline, а этот layout вызывается benchmark-ом
на том же ``DiagramDescription``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from html import escape
from math import ceil, sqrt

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
    BLOCK_GAP_X,
    BLOCK_GAP_Y,
    CONNECTION_LANE_GAP,
    GRAPH_LEFT_GAP,
    GRAPH_RIGHT_MARGIN,
    MAX_STATE_COLUMNS,
    PAGE_MARGIN_X,
    PAGE_MARGIN_Y,
    STATE_AREA_OFFSET_X,
    STATE_GAP_X,
    STATE_HEIGHT,
    STATE_ROW_STEP,
    STATE_WIDTH,
    _BlockMeasurements,
    _center,
    _connection_exit_offset,
    _junction_geometry,
    _label_dimensions,
    _layout_block,
    _measure_block,
    _operation_text_metadata,
    _side_towards,
)


TITLE_PADDING_X = 24
TRACK_LANE_STEP = 22
MAX_RESERVED_LANES = 6


@dataclass(frozen=True)
class _GridCandidate:
    columns: int
    rows: int
    column_gap: int
    row_step: int
    width: int
    height: int
    score: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class _BlockPlan:
    measurements: _BlockMeasurements
    title: str
    title_height: int
    graph_origin_x: int
    graph_origin_y: int
    x_scale: float
    y_scale: float


def _state_grid_index(block: AutomatonView) -> dict[object, int]:
    ordered = [item.state for item in block.states if not item.state.final]
    ordered.extend(item.state for item in block.states if item.state.final)
    return {state: index for index, state in enumerate(ordered)}


def _lane_demands(
    block: AutomatonView,
    columns: int,
) -> tuple[int, int, int, int]:
    """Оценивает загрузку вертикальных/горизонтальных каналов логической сетки."""

    indexes = _state_grid_index(block)
    vertical: Counter[int] = Counter()
    horizontal: Counter[int] = Counter()
    total_span = 0
    reverse_edges = 0
    for item in block.transitions:
        source = indexes[item.transition.source]
        target = indexes[item.transition.target]
        source_row, source_column = divmod(source, columns)
        target_row, target_column = divmod(target, columns)
        total_span += abs(source_row - target_row) + abs(source_column - target_column)
        reverse_edges += int(target <= source)
        for boundary in range(min(source_column, target_column), max(source_column, target_column)):
            vertical[boundary] += 1
        for boundary in range(min(source_row, target_row), max(source_row, target_row)):
            horizontal[boundary] += 1
        if source == target:
            vertical[source_column] += 1
            horizontal[source_row] += 1
    return (
        max(vertical.values(), default=0),
        max(horizontal.values(), default=0),
        total_span,
        reverse_edges,
    )


def _candidate_for_columns(
    block: AutomatonView,
    base: _BlockMeasurements,
    columns: int,
    title_width: int,
    title_height: int,
) -> _GridCandidate:
    state_count = max(1, len(block.states))
    rows = ceil(state_count / columns)
    vertical_lanes, horizontal_lanes, total_span, reverse_edges = _lane_demands(
        block, columns
    )
    reserved_vertical = min(MAX_RESERVED_LANES, vertical_lanes)
    reserved_horizontal = min(MAX_RESERVED_LANES, horizontal_lanes)
    column_gap = STATE_GAP_X + reserved_vertical * TRACK_LANE_STEP
    row_step = STATE_ROW_STEP + reserved_horizontal * TRACK_LANE_STEP
    graph_width = columns * STATE_WIDTH + max(0, columns - 1) * column_gap
    graph_height = STATE_HEIGHT + max(0, rows - 1) * row_step
    width = max(
        base.width,
        title_width + 2 * TITLE_PADDING_X,
        base.context_width
        + GRAPH_LEFT_GAP
        + STATE_AREA_OFFSET_X
        + graph_width
        + GRAPH_RIGHT_MARGIN
        + 80,
    )
    height = max(
        base.height + title_height,
        title_height + 112 + graph_height + 180,
    )
    empty_slots = columns * rows - state_count
    aspect_error = abs(width - round(height * 1.45))
    # Лексикографический score делает выбор полностью воспроизводимым.
    score = (
        aspect_error,
        total_span,
        empty_slots,
        reverse_edges + vertical_lanes + horizontal_lanes,
        width * height,
    )
    return _GridCandidate(
        columns=columns,
        rows=rows,
        column_gap=column_gap,
        row_step=row_step,
        width=width,
        height=height,
        score=score,
    )


def _plan_block(
    block: AutomatonView,
    connected_operation_ids: set[str],
) -> _BlockPlan:
    """Фазы измерения, перебора сетки и расчёта размеров треков."""

    base = _measure_block(block, connected_operation_ids)
    title = f"{block.object_ref.name} : {block.object_ref.automaton.__name__}"
    title_width, _ = _label_dimensions(escape(title))
    title_height = 0
    candidates = [
        _candidate_for_columns(
            block,
            base,
            columns,
            title_width,
            title_height,
        )
        for columns in range(1, min(MAX_STATE_COLUMNS, max(1, len(block.states))) + 1)
    ]
    selected = min(candidates, key=lambda item: (*item.score, item.columns))
    nonfinal_count = sum(not item.state.final for item in block.states)
    final_count = len(block.states) - nonfinal_count
    measurements = replace(
        base,
        width=selected.width,
        height=selected.height,
        state_columns=selected.columns,
        nonfinal_rows=(
            ceil(nonfinal_count / selected.columns) if nonfinal_count else 0
        ),
        final_rows=(ceil(final_count / selected.columns) if final_count else 0),
    )
    return _BlockPlan(
        measurements=measurements,
        title=title,
        title_height=title_height,
        graph_origin_x=(
            base.context_width + GRAPH_LEFT_GAP + STATE_AREA_OFFSET_X
        ),
        graph_origin_y=112,
        x_scale=(STATE_WIDTH + selected.column_gap) / (STATE_WIDTH + STATE_GAP_X),
        y_scale=selected.row_step / STATE_ROW_STEP,
    )


def _map_point(point: Point, origin: Point, x_scale: float, y_scale: float) -> Point:
    return Point(
        origin.x + round((point.x - origin.x) * x_scale),
        origin.y + round((point.y - origin.y) * y_scale),
    )


def _map_rectangle(
    rectangle: Rect,
    origin: Point,
    x_scale: float,
    y_scale: float,
) -> Rect:
    mapped = _map_point(Point(rectangle.x, rectangle.y), origin, x_scale, y_scale)
    return replace(rectangle, x=mapped.x, y=mapped.y)


def _compose_block(
    block: AutomatonView,
    geometry: Rect,
    connected_operation_ids: set[str],
    plan: _BlockPlan,
) -> tuple[list[NodeCell], list[EdgeCell], dict[str, Rect]]:
    """Компонует отдельную title-строку и масштабированную графовую область."""

    content = geometry
    raw_nodes, raw_edges, raw_geometries = _layout_block(
        block,
        content,
        connected_operation_ids,
        plan.measurements,
    )
    graph_origin = Point(
        content.x + plan.graph_origin_x,
        content.y + plan.graph_origin_y,
    )
    graph_kinds = {"state", "exit", "exitLabel", "entry", "decision"}
    nodes: list[NodeCell] = []
    geometries: dict[str, Rect] = {}
    for node in raw_nodes:
        node_geometry = node.geometry
        label = node.label
        if node.kind == "automaton":
            node_geometry = geometry
        elif node.kind in graph_kinds:
            node_geometry = _map_rectangle(
                node_geometry,
                graph_origin,
                plan.x_scale,
                plan.y_scale,
            )
        # External-операции уже уложены _layout_block в измеренную полосу над
        # рамкой. x_scale относится только к сетке состояний: повторное
        # масштабирование раздвигало ярлыки и выносило крайние за автомат.
        mapped_node = replace(node, label=label, geometry=node_geometry)
        nodes.append(mapped_node)
        geometries[node.id] = node_geometry

    transition_kinds = {
        "transition",
        "transitionBranch",
        "decisionIncoming",
        "entryTransition",
    }
    edges: list[EdgeCell] = []
    for edge in raw_edges:
        points = edge.points
        if edge.kind in transition_kinds:
            points = tuple(
                _map_point(point, graph_origin, plan.x_scale, plan.y_scale)
                for point in points
            )
        edges.append(replace(edge, points=points))
    # Внешние связи используют только геометрию operation и automaton; словарь
    # обновляется после трансформации, чтобы не протащить координаты baseline.
    for node in nodes:
        geometries[node.id] = node.geometry
    return nodes, edges, geometries


def _page_grid_columns(
    description: DiagramDescription,
    plans: dict[str, _BlockPlan],
) -> int:
    block_count = len(description.blocks)
    if block_count <= 1:
        return 1
    owners = {
        operation.id: index
        for index, block in enumerate(description.blocks)
        for operation in block.operations
    }
    candidates: list[tuple[tuple[int, int, int, int], int]] = []
    for columns in range(1, min(4, block_count) + 1):
        rows = ceil(block_count / columns)
        column_widths = [0] * columns
        row_heights = [0] * rows
        for index, block in enumerate(description.blocks):
            column_widths[index % columns] = max(
                column_widths[index % columns], plans[block.id].measurements.width
            )
            row_heights[index // columns] = max(
                row_heights[index // columns], plans[block.id].measurements.height
            )
        width = sum(column_widths) + max(0, columns - 1) * BLOCK_GAP_X
        height = sum(row_heights) + max(0, rows - 1) * BLOCK_GAP_Y
        connection_span = 0
        for connection in description.connections:
            source = owners[connection.required_endpoint_id]
            target = owners[connection.provided_endpoint_id]
            source_row, source_column = divmod(source, columns)
            target_row, target_column = divmod(target, columns)
            connection_span += abs(source_row - target_row) + abs(
                source_column - target_column
            )
        candidates.append(
            (
                (
                    connection_span,
                    abs(width - round(height * 1.6)),
                    width * height,
                    abs(columns - ceil(sqrt(block_count))),
                ),
                columns,
            )
        )
    return min(candidates)[1]


def _append_connections(
    description: DiagramDescription,
    block_geometries: dict[str, Rect],
    nodes: list[NodeCell],
    edges: list[EdgeCell],
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
    pairs = [
        tuple(
            sorted(
                (
                    operation_owners[connection.required_endpoint_id],
                    operation_owners[connection.provided_endpoint_id],
                )
            )
        )
        for connection in description.connections
    ]
    pair_counts = Counter(pairs)
    pair_lanes: dict[tuple[str, str], int] = defaultdict(int)
    for connection in description.connections:
        required_owner = operation_owners[connection.required_endpoint_id]
        provided_owner = operation_owners[connection.provided_endpoint_id]
        pair = tuple(sorted((required_owner, provided_owner)))
        lane = pair_lanes[pair]
        pair_lanes[pair] += 1
        lane_offset = lane - (pair_counts[pair] - 1) / 2
        junction_id = f"{connection.id}-junction"
        junction_geometry = _junction_geometry(
            block_geometries[required_owner],
            block_geometries[provided_owner],
            lane_offset,
        )
        junction_center = _center(junction_geometry)
        label_width, label_height = _label_dimensions(escape(connection.label))
        label_width = max(60, label_width)
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
                    geometry=Rect(
                        junction_center.x - label_width // 2,
                        junction_center.y - label_height - 10,
                        label_width,
                        label_height,
                    ),
                    kind="connectionLabel",
                    metadata=(("ciaoConnection", connection.id),),
                ),
            )
        )
        is_self_connection = required_owner == provided_owner
        for suffix, owner_id, operation_view, required in (
            ("required", required_owner, operation_views[connection.required_endpoint_id], True),
            ("provided", provided_owner, operation_views[connection.provided_endpoint_id], False),
        ):
            operation = operation_view.operation
            edges.append(
                EdgeCell(
                    id=f"{connection.id}-{suffix}",
                    label="",
                    style=styles.connection_half_style(
                        required=required,
                        exit_side=_side_towards(
                            block_geometries[owner_id], junction_center
                        ),
                        exit_offset=_connection_exit_offset(
                            lane_offset,
                            required=required,
                            self_connection=is_self_connection,
                        ),
                        stroke=(
                            styles.QUERY_STROKE
                            if connection.kind is OperationKind.QUERY
                            else "#000000"
                        ),
                    ),
                    source_id=owner_id,
                    target_id=junction_id,
                    points=(),
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


def layout_diagram_multiphase(description: DiagramDescription) -> DiagramPage:
    """Строит страницу через измерение, grid-search, tracks и композицию."""

    connected_operation_ids = {
        endpoint_id
        for connection in description.connections
        for endpoint_id in (
            connection.required_endpoint_id,
            connection.provided_endpoint_id,
        )
    }
    plans = {
        block.id: _plan_block(block, connected_operation_ids)
        for block in description.blocks
    }
    grid_columns = _page_grid_columns(description, plans)
    grid_rows = (
        ceil(len(description.blocks) / grid_columns)
        if description.blocks
        else 0
    )
    column_widths = [0] * grid_columns
    row_heights = [0] * grid_rows
    for index, block in enumerate(description.blocks):
        measurement = plans[block.id].measurements
        column_widths[index % grid_columns] = max(
            column_widths[index % grid_columns], measurement.width
        )
        row_heights[index // grid_columns] = max(
            row_heights[index // grid_columns], measurement.height
        )
    column_origins: list[int] = []
    current_x = PAGE_MARGIN_X
    for width in column_widths:
        column_origins.append(current_x)
        current_x += width + BLOCK_GAP_X
    row_origins: list[int] = []
    current_y = PAGE_MARGIN_Y
    for height in row_heights:
        row_origins.append(current_y)
        current_y += height + BLOCK_GAP_Y

    nodes: list[NodeCell] = []
    edges: list[EdgeCell] = []
    block_geometries: dict[str, Rect] = {}
    for index, block in enumerate(description.blocks):
        row, column = divmod(index, grid_columns)
        measurement = plans[block.id].measurements
        geometry = Rect(
            column_origins[column],
            row_origins[row],
            measurement.width,
            measurement.height,
        )
        block_geometries[block.id] = geometry
        block_nodes, block_edges, _ = _compose_block(
            block,
            geometry,
            connected_operation_ids,
            plans[block.id],
        )
        nodes.extend(block_nodes)
        edges.extend(block_edges)
    _append_connections(description, block_geometries, nodes, edges)
    width = (
        PAGE_MARGIN_X * 2
        + sum(column_widths)
        + max(0, len(column_widths) - 1) * BLOCK_GAP_X
    )
    height = (
        current_y - BLOCK_GAP_Y + PAGE_MARGIN_Y
        if description.blocks
        else 2 * PAGE_MARGIN_Y
    )
    return DiagramPage(tuple(nodes), tuple(edges), width, height)


__all__ = ["layout_diagram_multiphase"]
