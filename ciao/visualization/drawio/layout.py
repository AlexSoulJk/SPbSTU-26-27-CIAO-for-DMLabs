"""Детерминированная двухстадийная раскладка диаграммы CIAO."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape, unescape
from math import ceil, hypot, sqrt

from ciao.domain import OperationDirection, OperationKind

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


BLOCK_GAP_X = 360
BLOCK_GAP_Y = 160
PAGE_MARGIN_X = 180
PAGE_MARGIN_Y = 100
ENDPOINT_SIZE = 32
CONNECTION_LANE_GAP = 80
CONNECTION_EXIT_STEP = 0.16
LABEL_GAP = 10
LABEL_CHAR_WIDTH = 8
LABEL_LINE_HEIGHT = 18
STATE_WIDTH = 120
STATE_HEIGHT = 54
STATE_GAP_X = 35
STATE_ROW_STEP = 145
MAX_STATE_COLUMNS = 4
CONTEXT_WIDTH = 225
CONTEXT_MAX_WIDTH = 360
GRAPH_LEFT_GAP = 50
GRAPH_RIGHT_MARGIN = 20
STATE_AREA_OFFSET_X = 15
BOTTOM_MARGIN_X = 20
BOTTOM_ITEM_GAP = 18
BOTTOM_ICON_LABEL_GAP = 6
ACTION_INTERFACE_WIDTH = 16
ACTION_INTERFACE_HEIGHT = 24
ACTION_INTERFACE_ANCHOR_SIZE = 2
BOTTOM_LABEL_HEIGHT = 24
EXTERNAL_ITEM_GAP = 18
EXTERNAL_LABEL_GAP = 6
EXTERNAL_MARGIN_X = 20
EXTERNAL_PROVIDED_HEIGHT = 40
COMPACT_CHAR_WIDTH = 6
DECISION_SIZE = 40
DECISION_CLEARANCE = 60


@dataclass(frozen=True)
class _BlockMeasurements:
    """Результат первой фазы layout: весь текст измерен до координат."""

    width: int
    height: int
    context_label: str
    context_width: int
    context_height: int
    state_columns: int
    nonfinal_rows: int
    final_rows: int
    transition_labels: dict[str, str]
    transition_details: dict[str, str]
    transition_sizes: dict[str, tuple[int, int]]
    action_sizes: dict[str, tuple[int, int]]
    operation_sizes: dict[str, tuple[int, int]]


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

    color = styles.QUERY_STROKE
    return (
        f'<span style="font-size: 10px; color: {color};">'
        "&lt;&lt;Query&gt;&gt;:</span>",
        *(
            f'<span style="color: {color};">{operation_labels[query]}</span>'
            for query in queries
        ),
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


def _compact_label_dimensions(label: str) -> tuple[int, int]:
    """Измеряет короткую подпись порта без запаса для edge-label."""

    lines = _plain_label_lines(label)
    width = max(32, max(len(line) for line in lines) * COMPACT_CHAR_WIDTH)
    return width, max(BOTTOM_LABEL_HEIGHT, len(lines) * 18 + 6)


def _rectangles_intersect(first: Rect, second: Rect, *, margin: int = 5) -> bool:
    return not (
        first.x + first.width + margin <= second.x
        or second.x + second.width + margin <= first.x
        or first.y + first.height + margin <= second.y
        or second.y + second.height + margin <= first.y
    )


def _label_anchors(points: tuple[Point, ...]) -> tuple[tuple[Point, float], ...]:
    """Даёт кандидаты сначала на самых длинных участках стрелки."""

    raw_segments: list[tuple[float, float, Point, Point]] = []
    distance = 0.0
    for left, right in zip(points, points[1:]):
        length = hypot(right.x - left.x, right.y - left.y)
        raw_segments.append((length, distance, left, right))
        distance += length
    total = distance
    segments = sorted(
        raw_segments,
        key=lambda item: item[0],
        reverse=True,
    )
    anchors: list[tuple[Point, float]] = []
    for length, start_distance, left, right in segments:
        for ratio in (0.5, 0.35, 0.65, 0.2, 0.8):
            candidate = Point(
                round(left.x + (right.x - left.x) * ratio),
                round(left.y + (right.y - left.y) * ratio),
            )
            position = (
                round(2 * ((start_distance + length * ratio) / total) - 1, 4)
                if total
                else 0.0
            )
            if not any(item[0] == candidate for item in anchors):
                anchors.append((candidate, position))
    return tuple(anchors) or ((points[0], 0.0),)


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
) -> tuple[float, Point, int, int]:
    """Находит ближайшую свободную сторону и резервирует место подписи."""

    width, height = _label_dimensions(label)
    path = (_center(source), *points, _center(target))
    anchors = _label_anchors(path)
    fallback: (
        tuple[tuple[int, int, int, int, int], float, Point, Rect] | None
    ) = None

    for extra_gap in (0, 8, 16, 28, 44):
        for anchor_index, (anchor, position) in enumerate(anchors):
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
                score = (
                    intersections,
                    outside,
                    extra_gap,
                    anchor_index,
                    side_index,
                )
                if fallback is None or score < fallback[0]:
                    fallback = (score, position, offset, rectangle)
                inside = (
                    rectangle.x >= bounds.x + 6
                    and rectangle.y >= bounds.y + 6
                    and rectangle.x + rectangle.width
                    <= bounds.x + bounds.width - 6
                    and rectangle.y + rectangle.height
                    <= bounds.y + bounds.height - 6
                )
                if inside and intersections == 0:
                    obstacles.append(rectangle)
                    return position, offset, width, height

    assert fallback is not None
    _, position, offset, rectangle = fallback
    obstacles.append(rectangle)
    return position, offset, width, height


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
        if target.width <= 40:
            # Короткий вход в Exit разводим снизу: над ним находится строка
            # предыдущих State, а нижняя полоса остаётся свободной до Action.
            route_y = max(
                source.y + source.height,
                target.y + target.height,
            ) + 62 + lane * 24
            return (
                Point(source_center.x, route_y),
                Point(target_center.x, route_y),
            )
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


def _segment_intersects_rectangle(
    left: Point,
    right: Point,
    rectangle: Rect,
    *,
    margin: int = 8,
) -> bool:
    expanded = Rect(
        rectangle.x - margin,
        rectangle.y - margin,
        rectangle.width + 2 * margin,
        rectangle.height + 2 * margin,
    )
    if left.x == right.x:
        low, high = sorted((left.y, right.y))
        return (
            expanded.x <= left.x <= expanded.x + expanded.width
            and high >= expanded.y
            and low <= expanded.y + expanded.height
        )
    if left.y == right.y:
        low, high = sorted((left.x, right.x))
        return (
            expanded.y <= left.y <= expanded.y + expanded.height
            and high >= expanded.x
            and low <= expanded.x + expanded.width
        )
    return False


def _collinear_overlap(
    first_left: Point,
    first_right: Point,
    second_left: Point,
    second_right: Point,
) -> int:
    if (
        first_left.y == first_right.y == second_left.y == second_right.y
    ):
        first_min, first_max = sorted((first_left.x, first_right.x))
        second_min, second_max = sorted((second_left.x, second_right.x))
    elif (
        first_left.x == first_right.x == second_left.x == second_right.x
    ):
        first_min, first_max = sorted((first_left.y, first_right.y))
        second_min, second_max = sorted((second_left.y, second_right.y))
    else:
        return 0
    return max(0, min(first_max, second_max) - max(first_min, second_min))


def _safe_transition_route(
    source: Rect,
    target: Rect,
    *,
    source_index: int,
    target_index: int,
    lane: int,
    label_width: int,
    obstacles: list[Rect],
    reserved_paths: list[tuple[Point, ...]],
) -> tuple[Point, ...]:
    """Выбирает ортогональный маршрут по узлам, длине подписи и занятым полосам."""

    source_center = _center(source)
    target_center = _center(target)
    base = _route_transition(
        source,
        target,
        source_index=source_index,
        target_index=target_index,
        lane=lane,
    )
    top_y = min(source.y, target.y) - 48 - lane * 24
    bottom_y = max(
        source.y + source.height,
        target.y + target.height,
    ) + 48 + lane * 24
    left_x = min(source.x, target.x) - 48 - lane * 24
    right_x = max(
        source.x + source.width,
        target.x + target.width,
    ) + 48 + lane * 24
    candidates = (
        base,
        (Point(source_center.x, top_y), Point(target_center.x, top_y)),
        (Point(source_center.x, bottom_y), Point(target_center.x, bottom_y)),
        (Point(left_x, source_center.y), Point(left_x, target_center.y)),
        (Point(right_x, source_center.y), Point(right_x, target_center.y)),
    )
    unique_candidates = tuple(dict.fromkeys(candidates))
    relevant_obstacles = [
        obstacle for obstacle in obstacles if obstacle not in (source, target)
    ]
    desired_segment = min(180, max(90, round(label_width * 0.55)))

    def score(points: tuple[Point, ...]) -> tuple[int, int, int, float]:
        path = (source_center, *points, target_center)
        segments = tuple(zip(path, path[1:]))
        intersections = sum(
            _segment_intersects_rectangle(left, right, obstacle)
            for left, right in segments
            for obstacle in relevant_obstacles
        )
        overlap = sum(
            _collinear_overlap(left, right, used_left, used_right)
            for left, right in segments
            for used_path in reserved_paths
            for used_left, used_right in zip(used_path, used_path[1:])
        )
        longest = max(
            (hypot(right.x - left.x, right.y - left.y) for left, right in segments),
            default=0,
        )
        shortfall = max(0, desired_segment - round(longest))
        total = sum(
            hypot(right.x - left.x, right.y - left.y)
            for left, right in segments
        )
        return intersections, overlap, shortfall, total

    selected = min(unique_candidates, key=score)
    reserved_paths.append((source_center, *selected, target_center))
    return selected


def _state_columns(block: AutomatonView) -> int:
    return min(MAX_STATE_COLUMNS, max(1, ceil(sqrt(len(block.states)))))


def _visible_actions(block: AutomatonView) -> tuple[object, ...]:
    return tuple(
        action_view
        for action_view in block.actions
        if not action_view.action.outgoing_commands
    )


def _round_up(value: int, step: int) -> int:
    return ceil(value / step) * step


def _context_card(block: AutomatonView) -> tuple[str, int, int]:
    """Измеряет единую карточку имени объекта и полей контекста."""

    plain_title = f"{block.object_ref.name} : {block.object_ref.automaton.__name__}"
    title = escape(plain_title)
    label = (
        '<div><span style="font-family: Helvetica; font-weight: 700; '
        f'text-align: center;">{title}</span></div>Поля контекста'
    )
    if block.context_fields:
        label += "<br>" + "<br>".join(
            f"{escape(item.name)}: {escape(format_type(item.annotation))}"
            for item in block.context_fields
        )
    else:
        label += "<br>(нет объявленных полей)"
    plain_lines = [
        plain_title,
        "Поля контекста",
        *(
            f"{item.name}: {format_type(item.annotation)}"
            for item in block.context_fields
        ),
    ]
    if not block.context_fields:
        plain_lines.append("(нет объявленных полей)")
    measured_width = max(len(line) for line in plain_lines) * LABEL_CHAR_WIDTH + 18
    width = _round_up(
        min(CONTEXT_MAX_WIDTH, max(CONTEXT_WIDTH, measured_width)),
        5,
    )
    characters_per_line = max(1, (width - 18) // LABEL_CHAR_WIDTH)
    visual_rows = sum(
        max(1, ceil(len(line) / characters_per_line)) for line in plain_lines
    )
    height = max(70, visual_rows * 20 - 6)
    return label, width, height


def _measure_block(
    block: AutomatonView,
    connected_operation_ids: set[str],
) -> _BlockMeasurements:
    """Измеряет подписи и только после этого определяет размер блока."""

    operation_labels = {
        operation_view.operation: _operation_call_label(operation_view)
        for operation_view in block.operations
    }
    transition_labels = {
        item.id: _transition_label(item.transition, operation_labels)
        for item in block.transitions
    }
    transition_details = {
        item.id: _transition_details(item.transition, operation_labels)
        for item in block.transitions
    }
    transition_sizes = {
        item_id: _label_dimensions(label)
        for item_id, label in transition_labels.items()
    }
    action_sizes = {
        action_view.id: _compact_label_dimensions(action_view.action.name)
        for action_view in _visible_actions(block)
    }
    operation_sizes = {
        operation_view.id: (
            (
                max(
                    32,
                    max(
                        len(line)
                        for line in _plain_label_lines(
                            _visible_operation_label(operation_view)
                        )
                    )
                    * LABEL_CHAR_WIDTH,
                ),
                42,
            )
            if operation_view.operation.external
            else _compact_label_dimensions(
                _visible_operation_label(operation_view)
            )
        )
        for operation_view in block.operations
    }

    context_label, context_width, context_height = _context_card(block)
    state_columns = _state_columns(block)
    nonfinal_count = sum(not item.state.final for item in block.states)
    final_count = len(block.states) - nonfinal_count
    nonfinal_rows = ceil(nonfinal_count / state_columns) if nonfinal_count else 0
    final_rows = ceil(final_count / state_columns) if final_count else 0
    state_rows = max(1, nonfinal_rows + final_rows)
    state_area_width = (
        state_columns * STATE_WIDTH
        + max(0, state_columns - 1) * STATE_GAP_X
    )
    largest_transition_width = max(
        (size[0] for size in transition_sizes.values()),
        default=0,
    )
    graph_width = max(
        state_area_width,
        largest_transition_width + 2 * STATE_WIDTH,
    )

    bottom_operations = [
        item
        for item in block.operations
        if not item.operation.external
        and item.id not in connected_operation_ids
    ]
    # Нижняя граница строится как детерминированный «забор»: сначала UML-
    # символ, затем его подпись. ELK эту полосу не компонует, поэтому тот же
    # порядок и те же зазоры сохраняются во всех стратегиях раскладки.
    fence_widths = [
        ACTION_INTERFACE_WIDTH + BOTTOM_ICON_LABEL_GAP + size[0]
        for size in action_sizes.values()
    ]
    fence_widths.extend(
        ENDPOINT_SIZE
        + BOTTOM_ICON_LABEL_GAP
        + operation_sizes[operation_view.id][0]
        for operation_view in bottom_operations
    )
    bottom_width = sum(fence_widths)
    bottom_width += max(0, len(fence_widths) - 1) * BOTTOM_ITEM_GAP

    external_operations = [
        item for item in block.operations if item.operation.external
    ]
    external_widths = [
        max(
            operation_sizes[item.id][0],
            (
                ENDPOINT_SIZE
                if item.operation.direction is OperationDirection.PROVIDED
                else ACTION_INTERFACE_WIDTH
            ),
        )
        for item in external_operations
    ]
    external_width = sum(external_widths)
    external_width += max(0, len(external_widths) - 1) * EXTERNAL_ITEM_GAP

    width = _round_up(
        max(
            650,
            context_width
            + GRAPH_LEFT_GAP
            + graph_width
            + GRAPH_RIGHT_MARGIN,
            2 * BOTTOM_MARGIN_X + bottom_width,
            2 * EXTERNAL_MARGIN_X + external_width,
        ),
        5,
    )
    graph_bottom = 112 + (state_rows - 1) * STATE_ROW_STEP + STATE_HEIGHT
    height = _round_up(
        max(
            520,
            context_height + 130,
            graph_bottom + 154,
        ),
        20,
    )
    return _BlockMeasurements(
        width=width,
        height=height,
        context_label=context_label,
        context_width=context_width,
        context_height=context_height,
        state_columns=state_columns,
        nonfinal_rows=nonfinal_rows,
        final_rows=final_rows,
        transition_labels=transition_labels,
        transition_details=transition_details,
        transition_sizes=transition_sizes,
        action_sizes=action_sizes,
        operation_sizes=operation_sizes,
    )


def _visible_operation_label(operation_view: object) -> str:
    label = getattr(operation_view, "signature_label")
    operation = getattr(operation_view, "operation")
    if operation.kind is OperationKind.QUERY:
        return f"«query»<br>{label}"
    return label


def _operation_label_geometry(
    operation_geometry: Rect,
    side: str,
    size: tuple[int, int],
) -> Rect:
    width, height = size
    if side == "external":
        return Rect(
            operation_geometry.x - width // 2 - 4,
            operation_geometry.y - 1,
            width,
            height,
        )
    if side == "bottom":
        return Rect(
            operation_geometry.x - width + 4,
            operation_geometry.y + ENDPOINT_SIZE - height,
            width,
            height,
        )
    return Rect(operation_geometry.x + 46, operation_geometry.y - 5, width, height)


def _layout_block(
    block: AutomatonView,
    block_geometry: Rect,
    connected_operation_ids: set[str],
    measurements: _BlockMeasurements,
) -> tuple[list[NodeCell], list[EdgeCell], dict[str, Rect]]:
    """Размещает измеренный блок: граф, нижнюю рамку и внешние порты."""

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

    context_geometry = Rect(
        block_geometry.x,
        block_geometry.y,
        measurements.context_width,
        measurements.context_height,
    )
    nodes.append(
        NodeCell(
            id=f"{block.id}-context",
            label=measurements.context_label,
            style=styles.CONTEXT_STYLES[block.role],
            geometry=context_geometry,
            kind="context",
        )
    )

    grouped: dict[tuple[object, object], list[object]] = defaultdict(list)
    for transition_view in block.transitions:
        transition = transition_view.transition
        grouped[(transition.source, transition.event)].append(transition_view)

    state_geometries: dict[object, Rect] = {}
    state_ids = {item.state: item.id for item in block.states}
    state_indexes = {
        item.state: index for index, item in enumerate(block.states)
    }
    state_obstacles: list[Rect] = []
    state_start_x = (
        block_geometry.x
        + measurements.context_width
        + GRAPH_LEFT_GAP
        + STATE_AREA_OFFSET_X
    )
    state_start_y = block_geometry.y + 112
    state_columns = measurements.state_columns
    state_area_width = (
        state_columns * STATE_WIDTH
        + max(0, state_columns - 1) * STATE_GAP_X
    )
    has_external_operation = any(
        operation_view.operation.external for operation_view in block.operations
    )
    nonfinal_states = [item for item in block.states if not item.state.final]
    final_states = [item for item in block.states if item.state.final]

    for index, state_view in enumerate(nonfinal_states):
        column = index % state_columns
        row = index // state_columns
        state_x = state_start_x + column * (STATE_WIDTH + STATE_GAP_X)
        if state_view.state.initial and has_external_operation:
            # Entry и внешний provided-интерфейс образуют отдельную входную
            # колонку, поэтому initial State слегка смещается к ним.
            state_x -= STATE_AREA_OFFSET_X
        slot_geometry = Rect(
            state_x,
            state_start_y + row * STATE_ROW_STEP,
            STATE_WIDTH,
            STATE_HEIGHT,
        )
        geometry = slot_geometry
        state_geometries[state_view.state] = geometry
        geometries[state_view.id] = geometry
        nodes.append(
            NodeCell(
                id=state_view.id,
                label=state_view.state.name,
                style=styles.STATE_STYLES[block.role],
                geometry=geometry,
                kind="state",
                metadata=(
                    ("ciaoState", state_view.state.name),
                    ("ciaoInitial", str(state_view.state.initial).lower()),
                    ("ciaoFinal", str(state_view.state.final).lower()),
                ),
            )
        )
        state_obstacles.append(geometry)

    decision_geometries: dict[tuple[object, object], Rect] = {}
    decision_index = 0
    for (source, event), transition_views in grouped.items():
        if len(transition_views) <= 1 or source not in state_geometries:
            continue
        source_geometry = state_geometries[source]
        geometry = Rect(
            _center(source_geometry).x - DECISION_SIZE // 2
            + decision_index * 42,
            source_geometry.y + source_geometry.height + 78
            + decision_index * 18,
            DECISION_SIZE,
            DECISION_SIZE,
        )
        while any(
            _rectangles_intersect(geometry, obstacle, margin=12)
            for obstacle in state_obstacles
        ):
            geometry = Rect(
                geometry.x,
                geometry.y + DECISION_SIZE + 24,
                geometry.width,
                geometry.height,
            )
        decision_geometries[(source, event)] = geometry
        decision_index += 1

    final_row_start = measurements.nonfinal_rows
    graph_center_x = state_start_x + state_area_width // 2
    decision_clear_x = max(
        (
            geometry.x + geometry.width + DECISION_CLEARANCE
            for geometry in decision_geometries.values()
        ),
        default=graph_center_x,
    )
    final_base_center_x = max(graph_center_x, decision_clear_x)
    for index, state_view in enumerate(final_states):
        row = final_row_start + index // state_columns
        position_in_row = index % state_columns
        count_in_row = min(
            state_columns,
            len(final_states) - (index // state_columns) * state_columns,
        )
        center_x = (
            final_base_center_x
            + round(
                (position_in_row - (count_in_row - 1) / 2)
                * (STATE_WIDTH + STATE_GAP_X)
            )
        )
        slot_y = state_start_y + row * STATE_ROW_STEP
        geometry = Rect(center_x - 15, slot_y - 2, 30, 30)
        label_geometry = Rect(center_x - 60, slot_y - 26, 120, 24)
        if state_view.state.initial:
            # Для initial+final подпись уходит вниз, освобождая место Entry.
            label_geometry = Rect(center_x - 60, slot_y + 30, 120, 24)
        state_geometries[state_view.state] = geometry
        geometries[state_view.id] = geometry
        nodes.append(
            NodeCell(
                id=state_view.id,
                label="",
                style=styles.EXIT,
                geometry=geometry,
                kind="exit",
                metadata=(
                    ("ciaoState", state_view.state.name),
                    ("ciaoInitial", str(state_view.state.initial).lower()),
                    ("ciaoFinal", "true"),
                ),
            )
        )
        nodes.append(
            NodeCell(
                id=f"{state_view.id}-label",
                label=state_view.state.name,
                style=styles.STATE_LABEL,
                geometry=label_geometry,
                kind="exitLabel",
                metadata=(("ciaoState", state_view.state.name),),
            )
        )
        state_obstacles.extend((geometry, label_geometry))

    # Редкий случай Decision с final-source рассчитывается после Exit.
    for (source, event), transition_views in grouped.items():
        if len(transition_views) <= 1 or (source, event) in decision_geometries:
            continue
        source_geometry = state_geometries[source]
        geometry = Rect(
            _center(source_geometry).x - DECISION_SIZE // 2,
            source_geometry.y + source_geometry.height + 78,
            DECISION_SIZE,
            DECISION_SIZE,
        )
        decision_geometries[(source, event)] = geometry

    for (source, event), geometry in decision_geometries.items():
        decision_id = (
            f"{block.id}-decision-{source.qualified_name}-{event.qualified_name}"
        )
        geometries[decision_id] = geometry
        state_obstacles.append(geometry)
        nodes.append(
            NodeCell(
                id=decision_id,
                label="",
                style=styles.DECISION,
                geometry=geometry,
                kind="decision",
                metadata=(("ciaoSource", source.name), ("ciaoEvent", event.name)),
            )
        )

    for state_view in block.states:
        geometry = state_geometries[state_view.state]
        if state_view.state.initial:
            entry_geometry = Rect(
                geometry.x + geometry.width // 2 - 8,
                geometry.y - 48,
                16,
                16,
            )
            entry_id = f"{state_view.id}-entry"
            nodes.append(
                NodeCell(
                    id=entry_id,
                    label="",
                    style=styles.ENTRY,
                    geometry=entry_geometry,
                    kind="entry",
                    metadata=(("ciaoState", state_view.state.name),),
                )
            )
            edges.append(
                EdgeCell(
                    id=f"{state_view.id}-entry-transition",
                    label="",
                    style=styles.ENTRY_TRANSITION,
                    source_id=entry_id,
                    target_id=state_view.id,
                    points=(),
                    kind="entryTransition",
                    metadata=(("ciaoState", state_view.state.name),),
                )
            )
            state_obstacles.append(entry_geometry)

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
    operation_geometries: dict[str, tuple[Rect, str, Rect]] = {}
    bottom_obstacles: list[Rect] = []
    bottom_y = block_geometry.y + block_geometry.height
    cursor_x = block_geometry.x + BOTTOM_MARGIN_X

    for action_view in _visible_actions(block):
        width, height = measurements.action_sizes[action_view.id]
        interface_id = f"{action_view.id}-interface"
        interface_x = cursor_x + ACTION_INTERFACE_WIDTH // 2
        base_geometry = Rect(
            interface_x - ACTION_INTERFACE_ANCHOR_SIZE // 2,
            bottom_y - ACTION_INTERFACE_ANCHOR_SIZE // 2,
            ACTION_INTERFACE_ANCHOR_SIZE,
            ACTION_INTERFACE_ANCHOR_SIZE,
        )
        tip_geometry = Rect(
            interface_x - ACTION_INTERFACE_ANCHOR_SIZE // 2,
            bottom_y
            - ACTION_INTERFACE_HEIGHT
            - ACTION_INTERFACE_ANCHOR_SIZE // 2,
            ACTION_INTERFACE_ANCHOR_SIZE,
            ACTION_INTERFACE_ANCHOR_SIZE,
        )
        label_geometry = Rect(
            cursor_x + ACTION_INTERFACE_WIDTH + BOTTOM_ICON_LABEL_GAP,
            bottom_y - height,
            width,
            height,
        )
        metadata = [
            ("ciaoAction", action_view.action.name),
            ("ciaoQualifiedName", action_view.action.qualified_name),
            ("ciaoSignature", action_view.signature),
        ]
        if action_view.action.text is not None:
            metadata.append(("ciaoText", action_view.action.text))
        geometries[action_view.id] = label_geometry
        geometries[f"{interface_id}-base"] = base_geometry
        geometries[f"{interface_id}-tip"] = tip_geometry
        nodes.extend(
            (
                NodeCell(
                    id=f"{interface_id}-base",
                    label="",
                    style=styles.INTERFACE_ANCHOR,
                    geometry=base_geometry,
                    kind="interfaceAnchor",
                ),
                NodeCell(
                    id=f"{interface_id}-tip",
                    label="",
                    style=styles.INTERFACE_ANCHOR,
                    geometry=tip_geometry,
                    kind="interfaceAnchor",
                ),
            )
        )
        edges.append(
            EdgeCell(
                id=interface_id,
                label="",
                style=styles.action_interface_style(block.role),
                source_id=f"{interface_id}-base",
                target_id=f"{interface_id}-tip",
                points=(),
                kind="actionInterface",
                metadata=(
                    ("ciaoAction", action_view.action.name),
                    ("ciaoInterface", "required"),
                ),
            )
        )
        nodes.append(
            NodeCell(
                id=f"{action_view.id}-label",
                label=action_view.action.name,
                style=styles.ACTION_LABEL,
                geometry=label_geometry,
                kind="actionLabel",
                metadata=tuple(metadata),
            )
        )
        bottom_obstacles.append(label_geometry)
        cursor_x = label_geometry.x + label_geometry.width + BOTTOM_ITEM_GAP

    for operation_view in bottom_operations:
        label_width, label_height = measurements.operation_sizes[
            operation_view.id
        ]
        label_geometry = Rect(
            cursor_x + ENDPOINT_SIZE + BOTTOM_ICON_LABEL_GAP,
            bottom_y - label_height,
            label_width,
            label_height,
        )
        operation_geometry = Rect(
            cursor_x,
            bottom_y - ENDPOINT_SIZE,
            ENDPOINT_SIZE,
            ENDPOINT_SIZE,
        )
        operation_geometries[operation_view.id] = (
            operation_geometry,
            "bottom",
            label_geometry,
        )
        bottom_obstacles.extend((label_geometry, operation_geometry))
        cursor_x = label_geometry.x + label_geometry.width + BOTTOM_ITEM_GAP

    external_item_widths = [
        max(
            measurements.operation_sizes[item.id][0],
            (
                ENDPOINT_SIZE
                if item.operation.direction is OperationDirection.PROVIDED
                else ACTION_INTERFACE_WIDTH
            ),
        )
        for item in external_operations
    ]
    external_group_width = sum(external_item_widths)
    external_group_width += max(
        0,
        len(external_item_widths) - 1,
    ) * EXTERNAL_ITEM_GAP
    initial_geometries = [
        state_geometries[item.state]
        for item in block.states
        if item.state.initial
    ]
    preferred_center_x = (
        _center(initial_geometries[0]).x + 47
        if initial_geometries
        else block_geometry.x + block_geometry.width // 2
    )
    minimum_x = block_geometry.x + EXTERNAL_MARGIN_X
    maximum_x = (
        block_geometry.x
        + block_geometry.width
        - EXTERNAL_MARGIN_X
        - external_group_width
    )
    external_cursor_x = min(
        maximum_x,
        max(minimum_x, preferred_center_x - external_group_width // 2),
    )
    for operation_view, item_width in zip(
        external_operations,
        external_item_widths,
    ):
        label_width, label_height = measurements.operation_sizes[
            operation_view.id
        ]
        center_x = external_cursor_x + item_width // 2
        symbol_height = (
            EXTERNAL_PROVIDED_HEIGHT
            if operation_view.operation.direction is OperationDirection.PROVIDED
            else ACTION_INTERFACE_HEIGHT
        )
        label_geometry = Rect(
            center_x - label_width // 2,
            block_geometry.y
            - symbol_height
            - EXTERNAL_LABEL_GAP
            - label_height,
            label_width,
            label_height,
        )
        operation_geometries[operation_view.id] = (
            Rect(center_x - 20, block_geometry.y - 40, 40, 40),
            "external",
            label_geometry,
        )
        external_cursor_x += item_width + EXTERNAL_ITEM_GAP

    visible_operations = [
        operation_view
        for operation_view in block.operations
        if operation_view.id in operation_geometries
    ]
    for operation_view in visible_operations:
        symbol_geometry, side, prepared_label_geometry = operation_geometries[
            operation_view.id
        ]
        operation = operation_view.operation
        operation_metadata = (
            ("ciaoOperation", operation.name),
            ("ciaoDirection", operation.direction.value),
            ("ciaoKind", operation.kind.value),
            ("ciaoSignature", operation_view.label),
            ("ciaoExternal", str(operation.external).lower()),
            *_operation_text_metadata(operation),
        )
        is_external_required = (
            operation.external
            and operation.direction is OperationDirection.REQUIRED
        )
        if is_external_required:
            center_x = symbol_geometry.x + symbol_geometry.width // 2
            boundary_y = symbol_geometry.y + symbol_geometry.height
            base_geometry = Rect(
                center_x - ACTION_INTERFACE_ANCHOR_SIZE // 2,
                boundary_y - ACTION_INTERFACE_ANCHOR_SIZE // 2,
                ACTION_INTERFACE_ANCHOR_SIZE,
                ACTION_INTERFACE_ANCHOR_SIZE,
            )
            tip_geometry = Rect(
                center_x - ACTION_INTERFACE_ANCHOR_SIZE // 2,
                boundary_y
                - ACTION_INTERFACE_HEIGHT
                - ACTION_INTERFACE_ANCHOR_SIZE // 2,
                ACTION_INTERFACE_ANCHOR_SIZE,
                ACTION_INTERFACE_ANCHOR_SIZE,
            )
            tip_id = f"{operation_view.id}-interface-tip"
            geometries[operation_view.id] = base_geometry
            geometries[tip_id] = tip_geometry
            nodes.extend(
                (
                    NodeCell(
                        id=operation_view.id,
                        label="",
                        style=styles.INTERFACE_ANCHOR,
                        geometry=base_geometry,
                        kind="operation",
                        metadata=operation_metadata,
                    ),
                    NodeCell(
                        id=tip_id,
                        label="",
                        style=styles.INTERFACE_ANCHOR,
                        geometry=tip_geometry,
                        kind="interfaceAnchor",
                        metadata=operation_metadata,
                    ),
                )
            )
            edges.append(
                EdgeCell(
                    id=f"{operation_view.id}-interface",
                    label="",
                    style=styles.required_interface_style(block.role),
                    source_id=operation_view.id,
                    target_id=tip_id,
                    points=(),
                    kind="externalRequiredInterface",
                    metadata=operation_metadata,
                )
            )
        else:
            geometries[operation_view.id] = symbol_geometry
            nodes.append(
                NodeCell(
                    id=operation_view.id,
                    label="",
                    style=styles.endpoint_style(
                        provided=(
                            operation.direction is OperationDirection.PROVIDED
                        ),
                        side=side,
                        stroke=(
                            styles.QUERY_STROKE
                            if operation.kind is OperationKind.QUERY
                            else styles.ROLE_STROKES[block.role]
                        ),
                    ),
                    geometry=symbol_geometry,
                    kind="operation",
                    metadata=operation_metadata,
                )
            )
        display_label = _visible_operation_label(operation_view)
        label_geometry = prepared_label_geometry
        nodes.append(
            NodeCell(
                id=f"{operation_view.id}-label",
                label=display_label,
                style=(
                    styles.QUERY_ENDPOINT_LABEL
                    if operation.kind is OperationKind.QUERY
                    else styles.ENDPOINT_LABEL
                ),
                geometry=label_geometry,
                kind="operationLabel",
                metadata=(
                    ("ciaoOperation", operation.name),
                    ("ciaoDirection", operation.direction.value),
                    ("ciaoExternal", str(operation.external).lower()),
                    *_operation_text_metadata(operation),
                ),
            )
        )
    label_obstacles = [
        context_geometry,
        *state_obstacles,
        *bottom_obstacles,
    ]
    reserved_paths: list[tuple[Point, ...]] = []
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
            label = measurements.transition_labels[transition_view.id]
            label_width, _ = measurements.transition_sizes[transition_view.id]
            points = _safe_transition_route(
                source_geometry,
                state_geometries[target],
                source_index=state_indexes[source],
                target_index=state_indexes[target],
                lane=reverse_lane,
                label_width=label_width,
                obstacles=label_obstacles,
                reserved_paths=reserved_paths,
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
            (
                label_position,
                label_offset,
                label_width,
                label_height,
            ) = _place_edge_label(
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
                    label_position=label_position,
                    label_offset=label_offset,
                    label_width=label_width,
                    label_height=label_height,
                )
            )
            continue

        decision_id = (
            f"{block.id}-decision-{source.qualified_name}-{event.qualified_name}"
        )
        decision_geometry = decision_geometries[(source, event)]
        event_label = escape(operation_labels[event])
        (
            event_position,
            event_offset,
            event_width,
            event_height,
        ) = _place_edge_label(
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
                label_position=event_position,
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
            label = measurements.transition_details[transition_view.id]
            if label:
                (
                    label_position,
                    label_offset,
                    label_width,
                    label_height,
                ) = _place_edge_label(
                    source=decision_geometry,
                    target=target_geometry,
                    points=branch_points,
                    label=label,
                    preferred_sides=preferred_sides,
                    obstacles=label_obstacles,
                    bounds=block_geometry,
                )
            else:
                label_position = None
                label_offset = None
                label_width = None
                label_height = None
            reserved_paths.append(
                (decision_center, *branch_points, target_center)
            )
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
                    label_position=label_position,
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

    block_count = len(description.blocks)
    grid_columns = max(1, ceil(sqrt(block_count)))
    grid_rows = ceil(block_count / grid_columns) if block_count else 0
    block_measurements = {
        block.id: _measure_block(block, connected_operation_ids)
        for block in description.blocks
    }
    block_sizes = {
        block_id: (measurement.width, measurement.height)
        for block_id, measurement in block_measurements.items()
    }
    column_widths = [0] * grid_columns
    row_heights = [0] * grid_rows
    for index, block in enumerate(description.blocks):
        row = index // grid_columns
        column = index % grid_columns
        width, height = block_sizes[block.id]
        column_widths[column] = max(column_widths[column], width)
        row_heights[row] = max(row_heights[row], height)

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

    block_geometries: dict[str, Rect] = {}
    for index, block in enumerate(description.blocks):
        row = index // grid_columns
        column = index % grid_columns
        block_width, block_height = block_sizes[block.id]
        block_geometry = Rect(
            column_origins[column],
            row_origins[row],
            block_width,
            block_height,
        )
        block_geometries[block.id] = block_geometry
        block_nodes, block_edges, inner_geometries = _layout_block(
            block,
            block_geometry,
            connected_operation_ids,
            block_measurements[block.id],
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


__all__ = ["layout_diagram"]
