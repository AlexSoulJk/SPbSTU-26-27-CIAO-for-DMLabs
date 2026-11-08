"""Внутренние DTO одностороннего экспортера CIAO в draw.io."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ciao.domain import AutomatonObject, AutomatonRole, Operation, State, Transition
from ciao.infrastructure import OperationSignature


@dataclass(frozen=True)
class ContextField:
    """Поле пользовательского контекста без значения конкретного экземпляра."""

    name: str
    annotation: Any


@dataclass(frozen=True)
class StateView:
    id: str
    state: State


@dataclass(frozen=True)
class OperationView:
    id: str
    operation: Operation
    signature: OperationSignature
    label: str


@dataclass(frozen=True)
class TransitionView:
    id: str
    transition: Transition


@dataclass(frozen=True)
class AutomatonView:
    id: str
    object_ref: AutomatonObject
    role: AutomatonRole
    context_fields: tuple[ContextField, ...]
    states: tuple[StateView, ...]
    operations: tuple[OperationView, ...]
    transitions: tuple[TransitionView, ...]


@dataclass(frozen=True)
class ConnectionView:
    id: str
    required_endpoint_id: str
    provided_endpoint_id: str
    label: str


@dataclass(frozen=True)
class DiagramDescription:
    blocks: tuple[AutomatonView, ...]
    connections: tuple[ConnectionView, ...]


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rectangle:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class NodeCell:
    id: str
    label: str
    style: str
    geometry: Rectangle
    kind: str
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EdgeCell:
    id: str
    label: str
    style: str
    source_id: str
    target_id: str
    points: tuple[Point, ...]
    kind: str
    metadata: tuple[tuple[str, str], ...] = ()
    label_x: float | None = None
    label_y: float | None = None


@dataclass(frozen=True)
class DiagramPage:
    nodes: tuple[NodeCell, ...]
    edges: tuple[EdgeCell, ...]
    width: int
    height: int
