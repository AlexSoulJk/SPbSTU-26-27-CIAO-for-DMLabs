"""Декларации условий, действий и переходов."""

from __future__ import annotations

from typing import Any, Callable

from .model import State
from .operations import Operation


class Behavior:
    """Базовое декларативное описание пользовательского обработчика."""

    role = "behavior"

    def __init__(self, function: Callable[..., Any]) -> None:
        self.function = function
        self.name = function.__name__
        self.owner: type[Any] | None = None
        self.__doc__ = function.__doc__

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Behavior:
        return self

    @property
    def qualified_name(self) -> str:
        owner_name = self.owner.__name__ if self.owner is not None else "<unbound>"
        return f"{owner_name}.{self.name}"


class Guard(Behavior):
    """Условие применимости перехода."""

    role = "guard"


class Action(Behavior):
    """Действие перехода."""

    role = "action"


class Transition:
    """Декларативное правило перехода между управляющими состояниями."""

    def __init__(
        self,
        *,
        source: State,
        event: Operation,
        target: State,
        guard: Guard | None = None,
        actions: tuple[Action, ...] = (),
    ) -> None:
        self.source = source
        self.event = event
        self.target = target
        self.guard = guard
        self.actions = tuple(actions)
        self.name = "<unnamed>"
        self.owner: type[Any] | None = None

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Transition:
        return self

    @property
    def qualified_name(self) -> str:
        owner_name = self.owner.__name__ if self.owner is not None else "<unbound>"
        return f"{owner_name}.{self.name}"


def guard(function: Callable[..., Any]) -> Guard:
    """Помечает метод как условие перехода."""

    return Guard(function)


def action(function: Callable[..., Any]) -> Action:
    """Помечает метод как действие перехода."""

    return Action(function)


def transition(
    *,
    source: State,
    event: Operation,
    target: State,
    guard: Guard | None = None,
    actions: tuple[Action, ...] = (),
) -> Transition:
    """Создаёт декларативный переход как class-атрибут автомата."""

    return Transition(
        source=source,
        event=event,
        target=target,
        guard=guard,
        actions=actions,
    )
