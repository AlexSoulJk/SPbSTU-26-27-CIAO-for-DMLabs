"""Публичные сущности декларативной модели."""

from .connections import Connection, Endpoint
from .emission import Emit, Emits
from .model import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    AutomatonRole,
    AutomatonSnapshot,
    ControllerAutomaton,
    Program,
    State,
    ViewAutomaton,
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
    "AutomatonRole",
    "AutomatonSnapshot",
    "Connection",
    "ControllerAutomaton",
    "Endpoint",
    "Emit",
    "Emits",
    "Guard",
    "Operation",
    "OperationDirection",
    "OperationKind",
    "Program",
    "State",
    "Transition",
    "ViewAutomaton",
    "action",
    "guard",
    "provided_command",
    "provided_query",
    "required_command",
    "required_query",
    "transition",
]
