"""Основные сущности декларативной модели CIAO."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, get_args, get_origin


class State:
    """Именованное управляющее состояние автоматного класса."""

    def __init__(self, *, initial: bool = False, final: bool = False) -> None:
        self.initial = initial
        self.final = final
        self.name = "<unnamed>"
        self.owner: type[Any] | None = None

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> State:
        return self

    @property
    def qualified_name(self) -> str:
        owner_name = self.owner.__name__ if self.owner is not None else "<unbound>"
        return f"{owner_name}.{self.name}"

    def __repr__(self) -> str:
        return (
            f"State({self.qualified_name}, initial={self.initial}, "
            f"final={self.final})"
        )


class AutomatonContext:
    """Базовый тип пользовательского контекста одного автоматного объекта."""


ContextT = TypeVar("ContextT", bound=AutomatonContext)


class AutomatonRole(str, Enum):
    """Явная роль автоматного класса для внешних представлений."""

    BASE = "base"
    CONTROLLER = "controller"
    VIEW = "view"


class Automaton(Generic[ContextT]):
    """Базовый класс декларативного автомата с типизированным контекстом."""

    _context_type: type[AutomatonContext] | None = None
    role = AutomatonRole.BASE

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if not isinstance(origin, type) or not issubclass(origin, Automaton):
                continue
            context_type = get_args(base)[0]
            if isinstance(context_type, type) and issubclass(
                context_type, AutomatonContext
            ):
                cls._context_type = context_type
                break

class ControllerAutomaton(Automaton[ContextT], Generic[ContextT]):
    """Автомат роли Controller; роль не меняет семантику исполнения."""

    role = AutomatonRole.CONTROLLER


class ViewAutomaton(Automaton[ContextT], Generic[ContextT]):
    """Автомат роли View; роль не меняет семантику исполнения."""

    role = AutomatonRole.VIEW


@dataclass(frozen=True, eq=False)
class AutomatonObject:
    """Декларация именованного экземпляра автомата в программе."""

    name: str
    automaton: type[Automaton[Any]]
    initial_context: AutomatonContext


@dataclass(frozen=True)
class Program:
    """Декларативная система объектов и их соединений."""

    objects: tuple[AutomatonObject, ...]
    connections: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "objects", tuple(self.objects))
        object.__setattr__(self, "connections", tuple(self.connections))


@dataclass(frozen=True)
class AutomatonSnapshot(Generic[ContextT]):
    """Неизменяемая внешняя оболочка снимка состояния объекта."""

    object_name: str
    state: State
    context: ContextT

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)
