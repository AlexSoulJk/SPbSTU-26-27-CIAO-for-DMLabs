"""Детерминированные метрики качества геометрии draw.io-диаграммы."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
import re

from .diagram_model import DiagramPage, EdgeCell, NodeCell, Point, Rectangle


_EPSILON = 1e-9


@dataclass(frozen=True)
class LayoutMetrics:
    """Набор сопоставимых штрафов; меньшие значения означают лучший layout."""

    object_overlap_pairs: int
    object_overlap_area_ratio: float
    edge_object_intersections: int
    edge_object_overlap_ratio: float
    edge_crossings: int
    edge_overlap_ratio: float
    label_count: int
    label_edge_intersections: int
    label_own_edge_intersections: int
    mean_label_distance: float
    max_label_distance: float
    label_distance_penalty: float
    quality_penalty: float

    def as_dict(self) -> dict[str, int | float]:
        """Возвращает JSON-совместимое представление результата."""

        return asdict(self)


def _center(rectangle: Rectangle) -> Point:
    return Point(
        rectangle.x + rectangle.width // 2,
        rectangle.y + rectangle.height // 2,
    )


def _intersection_area(first: Rectangle, second: Rectangle) -> float:
    width = min(first.x + first.width, second.x + second.width) - max(
        first.x, second.x
    )
    height = min(first.y + first.height, second.y + second.height) - max(
        first.y, second.y
    )
    return float(max(0, width) * max(0, height))


def _segment_length(first: Point, second: Point) -> float:
    return hypot(second.x - first.x, second.y - first.y)


def _edge_path(edge: EdgeCell, nodes: dict[str, NodeCell]) -> tuple[Point, ...]:
    def endpoint(rectangle: Rectangle, prefix: str) -> Point:
        x_match = re.search(rf"(?:^|;){prefix}X=([-0-9.]+)", edge.style)
        y_match = re.search(rf"(?:^|;){prefix}Y=([-0-9.]+)", edge.style)
        if x_match is None or y_match is None:
            return _center(rectangle)
        return Point(
            round(rectangle.x + float(x_match.group(1)) * rectangle.width),
            round(rectangle.y + float(y_match.group(1)) * rectangle.height),
        )

    return (
        endpoint(nodes[edge.source_id].geometry, "exit"),
        *edge.points,
        endpoint(nodes[edge.target_id].geometry, "entry"),
    )


def _clip_segment_to_rectangle(
    first: Point,
    second: Point,
    rectangle: Rectangle,
) -> tuple[float, float] | None:
    """Возвращает параметрический интервал сегмента внутри прямоугольника."""

    dx = second.x - first.x
    dy = second.y - first.y
    lower = 0.0
    upper = 1.0
    checks = (
        (-dx, first.x - rectangle.x),
        (dx, rectangle.x + rectangle.width - first.x),
        (-dy, first.y - rectangle.y),
        (dy, rectangle.y + rectangle.height - first.y),
    )
    for direction, distance in checks:
        if abs(direction) <= _EPSILON:
            if distance < 0:
                return None
            continue
        ratio = distance / direction
        if direction < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return None
    return lower, upper


def _segment_rectangle_overlap(
    first: Point,
    second: Point,
    rectangle: Rectangle,
) -> float:
    # Касание рамки не означает, что стрелка проходит через объект. Это важно
    # для UML endpoint, который намеренно ставится вплотную к своей подписи.
    if first.x == second.x and first.x in {
        rectangle.x,
        rectangle.x + rectangle.width,
    }:
        return 0.0
    if first.y == second.y and first.y in {
        rectangle.y,
        rectangle.y + rectangle.height,
    }:
        return 0.0
    clipped = _clip_segment_to_rectangle(first, second, rectangle)
    if clipped is None:
        return 0.0
    lower, upper = clipped
    return max(0.0, upper - lower) * _segment_length(first, second)


def _point_to_segment_distance(point: Point, first: Point, second: Point) -> float:
    dx = second.x - first.x
    dy = second.y - first.y
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return hypot(point.x - first.x, point.y - first.y)
    ratio = ((point.x - first.x) * dx + (point.y - first.y) * dy) / denominator
    ratio = min(1.0, max(0.0, ratio))
    nearest_x = first.x + ratio * dx
    nearest_y = first.y + ratio * dy
    return hypot(point.x - nearest_x, point.y - nearest_y)


def _point_to_rectangle_distance(point: Point, rectangle: Rectangle) -> float:
    dx = max(rectangle.x - point.x, 0, point.x - rectangle.x - rectangle.width)
    dy = max(rectangle.y - point.y, 0, point.y - rectangle.y - rectangle.height)
    return hypot(dx, dy)


def _segment_rectangle_distance(
    first: Point,
    second: Point,
    rectangle: Rectangle,
) -> float:
    if _clip_segment_to_rectangle(first, second, rectangle) is not None:
        return 0.0
    corners = (
        Point(rectangle.x, rectangle.y),
        Point(rectangle.x + rectangle.width, rectangle.y),
        Point(rectangle.x, rectangle.y + rectangle.height),
        Point(rectangle.x + rectangle.width, rectangle.y + rectangle.height),
    )
    return min(
        _point_to_rectangle_distance(first, rectangle),
        _point_to_rectangle_distance(second, rectangle),
        *(_point_to_segment_distance(corner, first, second) for corner in corners),
    )


def _path_rectangle_distance(
    path: tuple[Point, ...],
    rectangle: Rectangle,
) -> float:
    return min(
        _segment_rectangle_distance(first, second, rectangle)
        for first, second in zip(path, path[1:])
    )


def _point_at_path_position(path: tuple[Point, ...], position: float) -> Point:
    lengths = [
        _segment_length(first, second)
        for first, second in zip(path, path[1:])
    ]
    total = sum(lengths)
    if total <= _EPSILON:
        return path[0]
    target = min(1.0, max(0.0, (position + 1.0) / 2.0)) * total
    traversed = 0.0
    for length, first, second in zip(lengths, path, path[1:]):
        if traversed + length >= target and length > _EPSILON:
            ratio = (target - traversed) / length
            return Point(
                round(first.x + (second.x - first.x) * ratio),
                round(first.y + (second.y - first.y) * ratio),
            )
        traversed += length
    return path[-1]


def _edge_label_rectangle(
    edge: EdgeCell,
    path: tuple[Point, ...],
) -> Rectangle | None:
    if (
        not edge.label
        or edge.label_position is None
        or edge.label_offset is None
        or edge.label_width is None
        or edge.label_height is None
    ):
        return None
    anchor = _point_at_path_position(path, edge.label_position)
    return Rectangle(
        anchor.x + edge.label_offset.x - edge.label_width // 2,
        anchor.y + edge.label_offset.y - edge.label_height // 2,
        edge.label_width,
        edge.label_height,
    )


def _is_attached_pair(first: NodeCell, second: NodeCell) -> bool:
    """Исключает из коллизий пары, которые образуют один составной символ."""

    ids = ((first.id, second.id), (second.id, first.id))
    return any(
        label_id == f"{owner_id}-label"
        for owner_id, label_id in ids
    )


def _merge_intervals(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged = 0.0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end + _EPSILON:
            end = max(end, next_end)
        else:
            merged += end - start
            start, end = next_start, next_end
    return merged + end - start


def _collinear_overlap_interval(
    first: Point,
    second: Point,
    other_first: Point,
    other_second: Point,
) -> tuple[float, float] | None:
    length = _segment_length(first, second)
    if length <= _EPSILON:
        return None
    horizontal = first.y == second.y
    vertical = first.x == second.x
    if horizontal and other_first.y == other_second.y == first.y:
        low = max(min(first.x, second.x), min(other_first.x, other_second.x))
        high = min(max(first.x, second.x), max(other_first.x, other_second.x))
        if high <= low:
            return None
        origin = min(first.x, second.x)
        return (low - origin) / length, (high - origin) / length
    if vertical and other_first.x == other_second.x == first.x:
        low = max(min(first.y, second.y), min(other_first.y, other_second.y))
        high = min(max(first.y, second.y), max(other_first.y, other_second.y))
        if high <= low:
            return None
        origin = min(first.y, second.y)
        return (low - origin) / length, (high - origin) / length
    return None


def _proper_crossing(
    first: Point,
    second: Point,
    other_first: Point,
    other_second: Point,
) -> bool:
    def orientation(left: Point, middle: Point, right: Point) -> int:
        value = (middle.y - left.y) * (right.x - middle.x) - (
            middle.x - left.x
        ) * (right.y - middle.y)
        return 0 if value == 0 else (1 if value > 0 else -1)

    values = (
        orientation(first, second, other_first),
        orientation(first, second, other_second),
        orientation(other_first, other_second, first),
        orientation(other_first, other_second, second),
    )
    # Общий endpoint и T-стык не являются пересечением двух трасс. В частности,
    # две половины assembly-связи намеренно сходятся в одном junction.
    return (
        0 not in values
        and values[0] != values[1]
        and values[2] != values[3]
    )


def evaluate_layout(page: DiagramPage) -> LayoutMetrics:
    """Оценивает пересечения, перекрытие стрелок и положение edge-label."""

    nodes = {node.id: node for node in page.nodes}
    obstacles = [node for node in page.nodes if node.kind != "automaton"]
    total_object_area = sum(
        node.geometry.width * node.geometry.height for node in obstacles
    )
    object_overlap_pairs = 0
    object_overlap_area = 0.0
    for index, first in enumerate(obstacles):
        for second in obstacles[index + 1 :]:
            if _is_attached_pair(first, second):
                continue
            area = _intersection_area(first.geometry, second.geometry)
            if area > 0:
                object_overlap_pairs += 1
                object_overlap_area += area

    paths = {edge.id: _edge_path(edge, nodes) for edge in page.edges}
    edge_lengths = {
        edge.id: sum(
            _segment_length(first, second)
            for first, second in zip(paths[edge.id], paths[edge.id][1:])
        )
        for edge in page.edges
    }
    total_edge_length = sum(edge_lengths.values())

    edge_object_intersections = 0
    edge_object_overlap = 0.0
    for edge in page.edges:
        path = paths[edge.id]
        for node in obstacles:
            if node.id in {edge.source_id, edge.target_id}:
                continue
            overlap = sum(
                _segment_rectangle_overlap(first, second, node.geometry)
                for first, second in zip(path, path[1:])
            )
            if overlap > _EPSILON:
                edge_object_intersections += 1
                edge_object_overlap += overlap

    segment_overlaps: dict[tuple[str, int], list[tuple[float, float]]] = {}
    edge_crossings = 0
    for edge_index, edge in enumerate(page.edges):
        path = paths[edge.id]
        for other in page.edges[edge_index + 1 :]:
            other_path = paths[other.id]
            pair_crosses = False
            for segment_index, (first, second) in enumerate(zip(path, path[1:])):
                for other_index, (other_first, other_second) in enumerate(
                    zip(other_path, other_path[1:])
                ):
                    interval = _collinear_overlap_interval(
                        first, second, other_first, other_second
                    )
                    if interval is not None:
                        segment_overlaps.setdefault(
                            (edge.id, segment_index), []
                        ).append(interval)
                        reverse = _collinear_overlap_interval(
                            other_first, other_second, first, second
                        )
                        assert reverse is not None
                        segment_overlaps.setdefault(
                            (other.id, other_index), []
                        ).append(reverse)
                    elif _proper_crossing(first, second, other_first, other_second):
                        pair_crosses = True
            edge_crossings += int(pair_crosses)

    overlapped_edge_length = 0.0
    for edge in page.edges:
        path = paths[edge.id]
        for index, (first, second) in enumerate(zip(path, path[1:])):
            overlapped_edge_length += _merge_intervals(
                segment_overlaps.get((edge.id, index), [])
            ) * _segment_length(first, second)

    label_rectangles: list[tuple[EdgeCell, Rectangle]] = []
    for edge in page.edges:
        rectangle = _edge_label_rectangle(edge, paths[edge.id])
        if rectangle is not None:
            label_rectangles.append((edge, rectangle))

    label_edge_intersections = 0
    label_own_edge_intersections = 0
    label_distances: list[float] = []
    for owner, rectangle in label_rectangles:
        own_distance = _path_rectangle_distance(paths[owner.id], rectangle)
        label_distances.append(own_distance)
        label_own_edge_intersections += int(own_distance <= _EPSILON)
        intersects_any = any(
            _path_rectangle_distance(path, rectangle) <= _EPSILON
            for path in paths.values()
        )
        label_edge_intersections += int(intersects_any)

    mean_distance = (
        sum(label_distances) / len(label_distances) if label_distances else 0.0
    )
    max_distance = max(label_distances, default=0.0)
    # До 12 px считаются нормальным визуальным зазором. Дальнейшее расстояние
    # нормируется на 100 px, чтобы штраф не зависел от абсолютного размера листа.
    label_distance_penalty = (
        sum(max(0.0, distance - 12.0) / 100.0 for distance in label_distances)
        / len(label_distances)
        if label_distances
        else 0.0
    )
    object_overlap_ratio = (
        object_overlap_area / total_object_area if total_object_area else 0.0
    )
    edge_object_ratio = (
        edge_object_overlap / total_edge_length if total_edge_length else 0.0
    )
    edge_overlap_ratio = (
        overlapped_edge_length / total_edge_length if total_edge_length else 0.0
    )
    label_intersection_ratio = (
        label_edge_intersections / len(label_rectangles)
        if label_rectangles
        else 0.0
    )
    quality_penalty = (
        1000.0 * object_overlap_ratio
        + 1000.0 * edge_object_ratio
        + 500.0 * edge_overlap_ratio
        + 300.0 * label_intersection_ratio
        + 50.0 * label_distance_penalty
        + 2.0 * edge_crossings
    )
    return LayoutMetrics(
        object_overlap_pairs=object_overlap_pairs,
        object_overlap_area_ratio=round(object_overlap_ratio, 6),
        edge_object_intersections=edge_object_intersections,
        edge_object_overlap_ratio=round(edge_object_ratio, 6),
        edge_crossings=edge_crossings,
        edge_overlap_ratio=round(edge_overlap_ratio, 6),
        label_count=len(label_rectangles),
        label_edge_intersections=label_edge_intersections,
        label_own_edge_intersections=label_own_edge_intersections,
        mean_label_distance=round(mean_distance, 3),
        max_label_distance=round(max_distance, 3),
        label_distance_penalty=round(label_distance_penalty, 6),
        quality_penalty=round(quality_penalty, 3),
    )


__all__ = ["LayoutMetrics", "evaluate_layout"]
