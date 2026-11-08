"""Публичные сущности декларативной модели."""

from .connections import Connection, Endpoint
from .model import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    AutomatonSnapshot,
    Program,
    State,
)
from .operations import (
    Operation,
    OperationDirection,
    OperationKind,
    provided_command,
    provided_query,
    required_command,
    required_query,
)
from .transition import Action, Guard, Transition, action, guard, transition

__all__ = [
    "Action",
    "Automaton",
    "AutomatonContext",
    "AutomatonObject",
    "AutomatonSnapshot",
    "Connection",
    "Endpoint",
    "Guard",
    "Operation",
    "OperationDirection",
    "OperationKind",
    "Program",
    "State",
    "Transition",
    "action",
    "guard",
    "provided_command",
    "provided_query",
    "required_command",
    "required_query",
    "transition",
]
