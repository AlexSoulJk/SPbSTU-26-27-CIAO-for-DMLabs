"""Детерминированная двухстадийная раскладка диаграммы CIAO."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from html import escape, unescape
from math import ceil, hypot

from ciao.domain import OperationDirection

from . import styles
from .builder import format_type
from .diagram_model import (
    AutomatonView,
    DiagramDescription,
    DiagramPage,
    EdgeCell,
    NodeCell,
    Point,
    Rectangle as Rect,
)


BLOCK_WIDTH = 780
BLOCK_GAP_X = 360
BLOCK_GAP_Y = 160
PAGE_MARGIN_X = 180
PAGE_MARGIN_Y = 100
BLOCKS_PER_ROW = 2
ENDPOINT_SIZE = 32
CONNECTION_LANE_GAP = 80
CONNECTION_EXIT_STEP = 0.16
LABEL_GAP = 10
LABEL_CHAR_WIDTH = 8
LABEL_LINE_HEIGHT = 18


def _center(rectangle: Rect) -> Point:
    return Point(
        rectangle.x + rectangle.width // 2,
        rectangle.y + rectangle.height // 2,
    )


def _action_labels(
    action: object,
    operation_labels: dict[object, str],
) -> tuple[str, ...]:
    outgoing_commands = getattr(action, "outgoing_commands")
    outgoing_queries = getattr(action, "outgoing_queries")
    labels: list[str] = []

    if not outgoing_commands:
        action_name = escape(getattr(action, "name"))
        action_text = getattr(action, "text")
        labels.append(
            f"<b>{action_name}:</b> {_user_text_html(action_text)}"
            if action_text is not None
            else action_name
        )

    if outgoing_queries:
        labels.extend(_query_labels(outgoing_queries, operation_labels))

    # При Emit собственная строка Action скрыта: видимыми действиями являются
    # required-команды, но Query-блок того же обработчика сохраняется.
    if outgoing_commands:
        labels.extend(
            operation_labels[command] for command in outgoing_commands
        )
    return tuple(labels)


def _query_labels(
    queries: tuple[object, ...],
    operation_labels: dict[object, str],
) -> tuple[str, ...]:
    """Формирует явный блок потенциальных синхронных запросов."""

    return (
        "&lt;&lt;Query&gt;&gt;:",
        *(operation_labels[query] for query in queries),
    )


def _operation_call_label(operation_view: object) -> str:
    """Связывает текст required-операции с её видимым вызовом."""

    operation = getattr(operation_view, "operation")
    signature_label = escape(getattr(operation_view, "signature_label"))
    if operation.text is None:
        return signature_label
    return f"<b>{signature_label}:</b> {_user_text_html(operation.text)}"


def _operation_text_metadata(operation: object) -> tuple[tuple[str, str], ...]:
    """Возвращает XML-метаданные только для явно заданного описания."""

    text = getattr(operation, "text")
    return (("ciaoText", text),) if text is not None else ()


def _user_text_html(text: str) -> str:
    """Экранирует текст, сохраняя только переносы, заданные пользователем."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return escape(normalized).replace("\n", "<br>")


def _plain_label_lines(label: str) -> tuple[str, ...]:
    with_breaks = re.sub(r"<br\s*/?>", "\n", label, flags=re.IGNORECASE)
    plain = unescape(re.sub(r"<[^>]+>", "", with_breaks))
    return tuple(plain.split("\n")) or ("",)


def _label_dimensions(label: str) -> tuple[int, int]:
    """Подбирает редактируемое поле под явные строки без автопереноса."""

    lines = _plain_label_lines(label)
    width = max(40, max(len(line) for line in lines) * LABEL_CHAR_WIDTH + 18)
    height = max(26, len(lines) * LABEL_LINE_HEIGHT + 8)
    return width, height


def _rectangles_intersect(first: Rect, second: Rect, *, margin: int = 5) -> bool:
    return not (
        first.x + first.width + margin <= second.x
        or second.x + second.width + margin <= first.x
        or first.y + first.height + margin <= second.y
        or second.y + second.height + margin <= first.y
    )


def _polyline_midpoint(points: tuple[Point, ...]) -> Point:
    lengths = [
        hypot(right.x - left.x, right.y - left.y)
        for left, right in zip(points, points[1:])
    ]
    total = sum(lengths)
    if total == 0:
        return points[0]
    remaining = total / 2
    for left, right, length in zip(points, points[1:], lengths):
        if remaining <= length:
            ratio = remaining / length if length else 0
            return Point(
                round(left.x + (right.x - left.x) * ratio),
                round(left.y + (right.y - left.y) * ratio),
            )
        remaining -= length
    return points[-1]


def _label_offset(
    side: str,
    width: int,
    height: int,
    *,
    extra_gap: int = 0,
) -> Point:
    gap = LABEL_GAP + extra_gap
    if side == "above":
        return Point(0, -(height // 2 + gap))
    if side == "below":
        return Point(0, height // 2 + gap)
    if side == "left":
        return Point(-(width // 2 + gap), 0)
    return Point(width // 2 + gap, 0)


def _label_rectangle(
    anchor: Point,
    offset: Point,
    width: int,
    height: int,
) -> Rect:
    return Rect(
        anchor.x + offset.x - width // 2,
        anchor.y + offset.y - height // 2,
        width,
        height,
    )


def _place_edge_label(
    *,
    source: Rect,
    target: Rect,
    points: tuple[Point, ...],
    label: str,
    preferred_sides: tuple[str, ...],
    obstacles: list[Rect],
    bounds: Rect,
) -> tuple[Point, int, int]:
    """Находит ближайшую свободную сторону и резервирует место подписи."""

    width, height = _label_dimensions(label)
    path = (_center(source), *points, _center(target))
    anchor = _polyline_midpoint(path)
    fallback: tuple[tuple[int, int, int, int], Point, Rect] | None = None

    for extra_gap in (0, 8, 16, 28, 44):
        for side_index, side in enumerate(preferred_sides):
            offset = _label_offset(
                side,
                width,
                height,
                extra_gap=extra_gap,
            )
            rectangle = _label_rectangle(anchor, offset, width, height)
            intersections = sum(
                _rectangles_intersect(rectangle, obstacle)
                for obstacle in obstacles
            )
            outside = (
                max(0, bounds.x + 6 - rectangle.x)
                + max(0, bounds.y + 6 - rectangle.y)
                + max(
                    0,
                    rectangle.x
                    + rectangle.width
                    - (bounds.x + bounds.width - 6),
                )
                + max(
                    0,
                    rectangle.y
                    + rectangle.height
                    - (bounds.y + bounds.height - 6),
                )
            )
            score = (intersections, outside, extra_gap, side_index)
            if fallback is None or score < fallback[0]:
                fallback = (score, offset, rectangle)
            inside = (
                rectangle.x >= bounds.x + 6
                and rectangle.y >= bounds.y + 6
                and rectangle.x + rectangle.width <= bounds.x + bounds.width - 6
                and rectangle.y + rectangle.height <= bounds.y + bounds.height - 6
            )
            if inside and intersections == 0:
                obstacles.append(rectangle)
                return offset, width, height

    assert fallback is not None
    _, offset, rectangle = fallback
    obstacles.append(rectangle)
    return offset, width, height


def _transition_details(
    transition: object,
    operation_labels: dict[object, str],
) -> str:
    guard = getattr(transition, "guard")
    actions = getattr(transition, "actions")
    parts: list[str] = []
    if getattr(transition, "otherwise"):
        parts.append("[else]")
    elif guard is not None:
        guard_label = escape(guard.name)
        if guard.text is not None:
            guard_label += f": {_user_text_html(guard.text)}"
        parts.append(f"[{guard_label}]")
        if guard.outgoing_queries:
            parts.extend(_query_labels(guard.outgoing_queries, operation_labels))
    if actions:
        action_labels = [
            label
            for action in actions
            for label in _action_labels(action, operation_labels)
        ]
        parts.append("/ " + "<br>".join(action_labels))
    return "<br>".join(parts)


def _transition_metadata(transition: object) -> tuple[tuple[str, str], ...]:
    metadata = [("ciaoTransition", getattr(transition, "name"))]
    if getattr(transition, "otherwise"):
        metadata.append(("ciaoOtherwise", "true"))
    guard = getattr(transition, "guard")
    actions = getattr(transition, "actions")
    queries = (
        (() if guard is None else guard.outgoing_queries)
        + tuple(
            query
            for action in actions
            for query in action.outgoing_queries
        )
    )
    if queries:
        metadata.append(
            (
                "ciaoQueries",
                ";".join(query.qualified_name for query in queries),
            )
        )
    return tuple(metadata)


def _transition_label(
    transition: object,
    operation_labels: dict[object, str],
) -> str:
    event = getattr(transition, "event")
    details = _transition_details(transition, operation_labels)
    event_label = escape(operation_labels[event])
    return f"{event_label}<br>{details}" if details else event_label


def _route_transition(
    source: Rect,
    target: Rect,
    *,
    source_index: int,
    target_index: int,
    lane: int,
) -> tuple[Point, ...]:
    """Разводит прямые, обратные и петлевые переходы по разным полосам."""

    source_center = _center(source)
    target_center = _center(target)
    if source == target:
        loop_x = source.x + source.width + 52 + lane * 24
        loop_y = source.y + source.height + 58 + lane * 24
        return (
            Point(loop_x, source_center.y),
            Point(loop_x, loop_y),
            Point(source_center.x, loop_y),
        )

    same_row = abs(source_center.y - target_center.y) < max(
        source.height, target.height
    )
    if same_row and source_index < target_index:
        return ()
    if same_row:
        route_y = min(source.y, target.y) - 48 - lane * 24
        # Вторая точка входит к целевому состоянию ближе к правому краю, чтобы
        # обратная стрелка не накладывалась на прямой переход под ней.
        return (
            Point(source_center.x, route_y),
            Point(target.x + target.width - 20, route_y),
        )

    middle_y = (source_center.y + target_center.y) // 2
    return (Point(source_center.x, middle_y), Point(target_center.x, middle_y))


def _block_height(block: AutomatonView) -> int:
    state_rows = max(1, ceil(len(block.states) / 3))
    context_height = max(70, 34 + 20 * len(block.context_fields))
    return max(520, context_height + 130, 230 + state_rows * 145)


def _visible_operation_label(operation_view: object) -> str:
    return getattr(operation_view, "signature_label")


def _operation_label_geometry(
    operation_geometry: Rect,
    side: str,
    label: str,
) -> Rect:
    if side == "external":
        width = max(32, min(220, len(label) * 8))
        return Rect(
            operation_geometry.x - width // 2 - 4,
            operation_geometry.y - 1,
            width,
            42,
        )
    if side == "bottom":
        width = max(25, min(220, len(label) * 8))
        return Rect(
            operation_geometry.x - width // 2 - 6,
            operation_geometry.y - 10,
            width,
            42,
        )
    return Rect(operation_geometry.x + 46, operation_geometry.y - 5, 190, 42)


def _layout_block(
    block: AutomatonView,
    block_geometry: Rect,
    connected_operation_ids: set[str],
) -> tuple[list[NodeCell], list[EdgeCell], dict[str, Rect]]:
    """Первая стадия: рассчитывает содержимое одного автомата."""

    nodes: list[NodeCell] = []
    edges: list[EdgeCell] = []
    geometries: dict[str, Rect] = {block.id: block_geometry}
    operation_labels = {
        operation_view.operation: _operation_call_label(operation_view)
        for operation_view in block.operations
    }
    nodes.append(
        NodeCell(
            id=block.id,
            label="",
            style=styles.BLOCK_STYLES[block.role],
            geometry=block_geometry,
            kind="automaton",
            metadata=(
                ("ciaoObject", block.object_ref.name),
                ("ciaoAutomaton", block.object_ref.automaton.__name__),
                ("ciaoRole", block.role.value),
            ),
        )
    )

    context_height = max(70, 34 + 20 * len(block.context_fields))
    title = f"{block.object_ref.name} : {block.object_ref.automaton.__name__}"
    context_label = (
        '<div><span style="font-family: Helvetica; font-weight: 700; '
        f'text-align: center;">{title}</span></div>Поля контекста'
    )
    if block.context_fields:
        context_label += "<br>" + "<br>".join(
            f"{item.name}: {format_type(item.annotation)}"
            for item in block.context_fields
        )
    else:
        context_label += "<br>(нет объявленных полей)"
    context_geometry = Rect(
        block_geometry.x,
        block_geometry.y,
        225,
        context_height,
    )
    nodes.append(
        NodeCell(
            id=f"{block.id}-context",
            label=context_label,
            style=styles.CONTEXT_STYLES[block.role],
            geometry=context_geometry,
            kind="context",
        )
    )

    state_geometries: dict[object, Rect] = {}
    state_ids: dict[object, str] = {}
    state_indexes: dict[object, int] = {}
    state_start_x = block_geometry.x + 290
    state_start_y = block_geometry.y + 112
    has_external_operation = any(
        operation_view.operation.external for operation_view in block.operations
    )
    for index, state_view in enumerate(block.states):
        column = index % 3
        row = index // 3
        state_x = state_start_x + column * 155
        if state_view.state.initial and has_external_operation:
            # Внешний lollipop входит сверху в начальное состояние, поэтому
            # оно немного сдвигается влево, не ломая сетку остальных состояний.
            state_x -= 40
        geometry = Rect(
            state_x,
            state_start_y + row * 145,
            120,
            54,
        )
        state_geometries[state_view.state] = geometry
        state_ids[state_view.state] = state_view.id
        state_indexes[state_view.state] = index
        geometries[state_view.id] = geometry
        style = (
            styles.FINAL_STATE_STYLES[block.role]
            if state_view.state.final
            else styles.STATE_STYLES[block.role]
        )
        nodes.append(
            NodeCell(
                id=state_view.id,
                label=state_view.state.name,
                style=style,
                geometry=geometry,
                kind="state",
                metadata=(
                    ("ciaoState", state_view.state.name),
                    ("ciaoInitial", str(state_view.state.initial).lower()),
                    ("ciaoFinal", str(state_view.state.final).lower()),
                ),
            )
        )

    bottom_operations = [
        operation_view
        for operation_view in block.operations
        if not operation_view.operation.external
        and operation_view.id not in connected_operation_ids
    ]
    external_operations = [
        operation_view
        for operation_view in block.operations
        if operation_view.operation.external
    ]
    operation_geometries: dict[str, tuple[Rect, str]] = {}

    for index, operation_view in enumerate(bottom_operations):
        count = len(bottom_operations)
        available = block_geometry.width - 148
        center_x = (
            block_geometry.x + 67 + available * (2 * index + 1) // (2 * count)
        )
        operation_geometries[operation_view.id] = (
            Rect(
                center_x - ENDPOINT_SIZE // 2,
                block_geometry.y + block_geometry.height - ENDPOINT_SIZE,
                ENDPOINT_SIZE,
                ENDPOINT_SIZE,
            ),
            "bottom",
        )

    initial_state = next(item.state for item in block.states if item.state.initial)
    initial_geometry = state_geometries[initial_state]
    for index, operation_view in enumerate(external_operations):
        center_x = initial_geometry.x + 40 + index * 235
        operation_geometries[operation_view.id] = (
            Rect(center_x - 20, block_geometry.y - 40, 40, 40),
            "external",
        )

    event_sources = {
        transition_view.transition.event: transition_view.transition.source
        for transition_view in block.transitions
    }
    visible_operations = [
        operation_view
        for operation_view in block.operations
        if operation_view.id in operation_geometries
    ]
    for operation_view in visible_operations:
        geometry, side = operation_geometries[operation_view.id]
        operation = operation_view.operation
        geometries[operation_view.id] = geometry
        nodes.append(
            NodeCell(
                id=operation_view.id,
                label="",
                style=styles.endpoint_style(
                    provided=operation.direction is OperationDirection.PROVIDED,
                    side=side,
                    stroke=styles.ROLE_STROKES[block.role],
                ),
                geometry=geometry,
                kind="operation",
                metadata=(
                    ("ciaoOperation", operation.name),
                    ("ciaoDirection", operation.direction.value),
                    ("ciaoKind", operation.kind.value),
                    ("ciaoExternal", str(operation.external).lower()),
                    *_operation_text_metadata(operation),
                ),
            )
        )
        display_label = _visible_operation_label(operation_view)
        nodes.append(
            NodeCell(
                id=f"{operation_view.id}-label",
                label=display_label,
                style=styles.ENDPOINT_LABEL,
                geometry=_operation_label_geometry(geometry, side, display_label),
                kind="operationLabel",
                metadata=(
                    ("ciaoOperation", operation.name),
                    ("ciaoDirection", operation.direction.value),
                    *_operation_text_metadata(operation),
                ),
            )
        )
        if operation.external:
            target_state = event_sources.get(operation, initial_state)
            edges.append(
                EdgeCell(
                    id=f"{operation_view.id}-external-link",
                    label="",
                    style=styles.external_interface_style(block.role),
                    source_id=operation_view.id,
                    target_id=state_ids[target_state],
                    points=(),
                    kind="externalInterface",
                    metadata=(("ciaoOperation", operation.name),),
                )
            )

    grouped: dict[tuple[object, object], list[object]] = defaultdict(list)
    for transition_view in block.transitions:
        transition = transition_view.transition
        grouped[(transition.source, transition.event)].append(transition_view)

    label_obstacles = [context_geometry, *state_geometries.values()]
    decision_index = 0
    reverse_lane = 0
    for (source, event), transition_views in grouped.items():
        # Else не имеет runtime-приоритета, но завершает развилку визуально.
        transition_views.sort(
            key=lambda item: getattr(item.transition, "otherwise")
        )
        source_id = state_ids[source]
        source_geometry = state_geometries[source]
        if len(transition_views) == 1:
            transition_view = transition_views[0]
            target = transition_view.transition.target
            points = _route_transition(
                source_geometry,
                state_geometries[target],
                source_index=state_indexes[source],
                target_index=state_indexes[target],
                lane=reverse_lane,
            )
            is_reverse = state_indexes[source] > state_indexes[target]
            is_loop = source is target
            crosses_rows = abs(
                _center(source_geometry).y - _center(state_geometries[target]).y
            ) >= max(source_geometry.height, state_geometries[target].height)
            if state_indexes[source] >= state_indexes[target]:
                reverse_lane += 1
            if is_loop:
                preferred_sides = ("right", "below", "above", "left")
            elif crosses_rows:
                preferred_sides = (
                    ("left", "right", "above", "below")
                    if is_reverse
                    else ("right", "left", "above", "below")
                )
            elif is_reverse:
                preferred_sides = ("above", "below", "left", "right")
            else:
                preferred_sides = ("above", "below", "right", "left")
            label = _transition_label(
                transition_view.transition,
                operation_labels,
            )
            label_offset, label_width, label_height = _place_edge_label(
                source=source_geometry,
                target=state_geometries[target],
                points=points,
                label=label,
                preferred_sides=preferred_sides,
                obstacles=label_obstacles,
                bounds=block_geometry,
            )
            edges.append(
                EdgeCell(
                    id=transition_view.id,
                    label=label,
                    style=styles.transition_style(block.role),
                    source_id=source_id,
                    target_id=state_ids[target],
                    points=points,
                    kind="transition",
                    metadata=_transition_metadata(transition_view.transition),
                    label_position=0,
                    label_offset=label_offset,
                    label_width=label_width,
                    label_height=label_height,
                )
            )
            continue

        decision_id = f"{block.id}-decision-{decision_index}"
        decision_geometry = Rect(
            _center(source_geometry).x - 20 + decision_index * 42,
            source_geometry.y + source_geometry.height + 78 + decision_index * 18,
            40,
            40,
        )
        decision_index += 1
        geometries[decision_id] = decision_geometry
        label_obstacles.append(decision_geometry)
        nodes.append(
            NodeCell(
                id=decision_id,
                label="",
                style=styles.DECISION,
                geometry=decision_geometry,
                kind="decision",
                metadata=(("ciaoSource", source.name), ("ciaoEvent", event.name)),
            )
        )
        event_label = escape(operation_labels[event])
        event_offset, event_width, event_height = _place_edge_label(
            source=source_geometry,
            target=decision_geometry,
            points=(),
            label=event_label,
            preferred_sides=("left", "right", "above", "below"),
            obstacles=label_obstacles,
            bounds=block_geometry,
        )
        edges.append(
            EdgeCell(
                id=f"{decision_id}-incoming",
                label=event_label,
                style=styles.transition_style(block.role),
                source_id=source_id,
                target_id=decision_id,
                points=(),
                kind="decisionIncoming",
                label_position=0,
                label_offset=event_offset,
                label_width=event_width,
                label_height=event_height,
            )
        )
        decision_center = _center(decision_geometry)
        for branch_index, transition_view in enumerate(transition_views):
            target = transition_view.transition.target
            target_geometry = state_geometries[target]
            target_center = _center(target_geometry)
            lane_y = (
                decision_geometry.y
                + decision_geometry.height
                + 34
                + branch_index * 28
            )
            if target is source:
                lane_x = source_geometry.x - 25 - branch_index * 24
                branch_points = (
                    Point(lane_x, decision_center.y),
                    Point(lane_x, target_center.y + 11),
                )
                preferred_sides = ("left", "right", "below", "above")
            else:
                target_lane_x = target_center.x + max(0, branch_index - 1) * 30
                branch_points = (
                    Point(decision_center.x, lane_y),
                    Point(target_lane_x, lane_y),
                )
                preferred_sides = (
                    ("above", "below", "right", "left")
                    if branch_index % 2 == 0
                    else ("below", "above", "right", "left")
                )
            label = _transition_details(
                transition_view.transition,
                operation_labels,
            )
            if label:
                label_offset, label_width, label_height = _place_edge_label(
                    source=decision_geometry,
                    target=target_geometry,
                    points=branch_points,
                    label=label,
                    preferred_sides=preferred_sides,
                    obstacles=label_obstacles,
                    bounds=block_geometry,
                )
            else:
                label_offset = None
                label_width = None
                label_height = None
            edges.append(
                EdgeCell(
                    id=transition_view.id,
                    label=label,
                    style=styles.transition_style(block.role),
                    source_id=decision_id,
                    target_id=state_ids[target],
                    points=branch_points,
                    kind="transitionBranch",
                    metadata=_transition_metadata(transition_view.transition),
                    label_position=0 if label else None,
                    label_offset=label_offset,
                    label_width=label_width,
                    label_height=label_height,
                )
            )

    return nodes, edges, geometries


def _side_towards(block: Rect, target: Point) -> str:
    block_center = _center(block)
    horizontal = abs(target.x - block_center.x)
    vertical = abs(target.y - block_center.y)
    if horizontal >= vertical:
        return "right" if target.x >= block_center.x else "left"
    return "bottom" if target.y >= block_center.y else "top"


def _junction_geometry(
    required: Rect,
    provided: Rect,
    lane_offset: float,
) -> Rect:
    required_center = _center(required)
    provided_center = _center(provided)
    if required == provided:
        center_x = required.x + required.width + 75
        center_y = required_center.y + round(lane_offset * CONNECTION_LANE_GAP)
    elif abs(provided_center.x - required_center.x) >= abs(
        provided_center.y - required_center.y
    ):
        left, right = sorted((required, provided), key=lambda item: item.x)
        center_x = (left.x + left.width + right.x) // 2 - 5
        center_y = (
            (required_center.y + provided_center.y) // 2
            + round(lane_offset * CONNECTION_LANE_GAP)
        )
    else:
        top, bottom = sorted((required, provided), key=lambda item: item.y)
        center_x = (
            (required_center.x + provided_center.x) // 2
            + round(lane_offset * CONNECTION_LANE_GAP)
        )
        center_y = (top.y + top.height + bottom.y) // 2
    return Rect(center_x - 5, center_y - 5, 10, 10)


def _connection_exit_offset(
    lane_offset: float,
    *,
    required: bool,
    self_connection: bool,
) -> float:
    """Разносит connection по границе блока, не прижимая их к углам."""

    if self_connection:
        base = 0.43 if required else 0.57
        value = base + lane_offset * 0.12
    else:
        value = 0.5 + lane_offset * CONNECTION_EXIT_STEP
    return round(min(0.84, max(0.16, value)), 2)


def layout_diagram(description: DiagramDescription) -> DiagramPage:
    """Вторая стадия: размещает блоки и собирает межблочные интерфейсы."""

    nodes: list[NodeCell] = []
    edges: list[EdgeCell] = []
    geometries: dict[str, Rect] = {}
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
    connected_operation_ids = {
        endpoint_id
        for connection in description.connections
        for endpoint_id in (
            connection.required_endpoint_id,
            connection.provided_endpoint_id,
        )
    }

    row_heights: dict[int, int] = {}
    for index, block in enumerate(description.blocks):
        row = index // BLOCKS_PER_ROW
        row_heights[row] = max(row_heights.get(row, 0), _block_height(block))

    row_origins: dict[int, int] = {}
    current_y = PAGE_MARGIN_Y
    for row in range(max(row_heights, default=-1) + 1):
        row_origins[row] = current_y
        current_y += row_heights[row] + BLOCK_GAP_Y

    block_geometries: dict[str, Rect] = {}
    for index, block in enumerate(description.blocks):
        row = index // BLOCKS_PER_ROW
        column = index % BLOCKS_PER_ROW
        block_geometry = Rect(
            PAGE_MARGIN_X + column * (BLOCK_WIDTH + BLOCK_GAP_X),
            row_origins[row],
            BLOCK_WIDTH,
            _block_height(block),
        )
        block_geometries[block.id] = block_geometry
        block_nodes, block_edges, inner_geometries = _layout_block(
            block,
            block_geometry,
            connected_operation_ids,
        )
        nodes.extend(block_nodes)
        edges.extend(block_edges)
        geometries.update(inner_geometries)

    connection_pairs = [
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
    pair_counts = Counter(connection_pairs)
    pair_lanes: dict[tuple[str, str], int] = defaultdict(int)
    for connection in description.connections:
        required_owner = operation_owners[connection.required_endpoint_id]
        provided_owner = operation_owners[connection.provided_endpoint_id]
        required_block = block_geometries[required_owner]
        provided_block = block_geometries[provided_owner]
        pair = tuple(sorted((required_owner, provided_owner)))
        lane = pair_lanes[pair]
        pair_lanes[pair] += 1
        lane_offset = lane - (pair_counts[pair] - 1) / 2

        junction_id = f"{connection.id}-junction"
        junction_geometry = _junction_geometry(
            required_block,
            provided_block,
            lane_offset,
        )
        junction_center = _center(junction_geometry)
        connection_label = escape(connection.label)
        label_width, label_height = _label_dimensions(connection_label)
        label_width = max(60, label_width)
        nodes.append(
            NodeCell(
                id=junction_id,
                label="",
                style=styles.CONNECTION_JUNCTION,
                geometry=junction_geometry,
                kind="connectionJunction",
                metadata=(("ciaoConnection", connection.id),),
            )
        )
        nodes.append(
            NodeCell(
                id=f"{connection.id}-label",
                label=connection_label,
                style=styles.CONNECTION_LABEL,
                geometry=Rect(
                    junction_center.x - label_width // 2,
                    junction_center.y - label_height - 10,
                    label_width,
                    label_height,
                ),
                kind="connectionLabel",
                metadata=(("ciaoConnection", connection.id),),
            )
        )

        required_operation = operation_views[connection.required_endpoint_id]
        provided_operation = operation_views[connection.provided_endpoint_id]
        is_self_connection = required_owner == provided_owner
        for suffix, owner_id, operation_view, required in (
            ("required", required_owner, required_operation, True),
            ("provided", provided_owner, provided_operation, False),
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

    columns = min(BLOCKS_PER_ROW, len(description.blocks))
    width = (
        PAGE_MARGIN_X * 2
        + columns * BLOCK_WIDTH
        + max(0, columns - 1) * BLOCK_GAP_X
    )
    height = (
        current_y - BLOCK_GAP_Y + PAGE_MARGIN_Y
        if description.blocks
        else 2 * PAGE_MARGIN_Y
    )
    return DiagramPage(tuple(nodes), tuple(edges), width, height)


__all__ = ["layout_diagram"]
