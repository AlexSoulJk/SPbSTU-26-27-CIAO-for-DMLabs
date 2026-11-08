"""Основные сущности декларативной модели CIAO."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, get_args, get_origin


class State:
    """Именованное управляющее состояние автоматного класса."""

    def __init__(self, *, initial: bool = False) -> None:
        self.initial = initial
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
        return f"State({self.qualified_name}, initial={self.initial})"


class RuntimeServices(Protocol):
    """Закрытый мост от декларативного автомата к runtime."""

    def emit(
        self,
        ctx: AutomatonContext,
        operation: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None: ...

    def query(
        self,
        ctx: AutomatonContext,
        operation: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


class AutomatonContext:
    """Базовый тип пользовательского контекста одного автоматного объекта."""

    def _ciao_bind(self, services: RuntimeServices, object_ref: AutomatonObject) -> None:
        object.__setattr__(self, "_ciao_services", services)
        object.__setattr__(self, "_ciao_object_ref", object_ref)

    def _ciao_runtime_services(self) -> RuntimeServices:
        services = getattr(self, "_ciao_services", None)
        if services is None:
            raise RuntimeError("Контекст не привязан к Runtime")
        return services

    def __deepcopy__(self, memo: dict[int, Any]) -> AutomatonContext:
        # Runtime-ссылки намеренно не копируются в снимки и новые запуски.
        copied = self.__class__.__new__(self.__class__)
        memo[id(self)] = copied
        for name, value in vars(self).items():
            if not name.startswith("_ciao_"):
                object.__setattr__(copied, name, deepcopy(value, memo))
        return copied


ContextT = TypeVar("ContextT", bound=AutomatonContext)
ResultT = TypeVar("ResultT")


class Automaton(Generic[ContextT]):
    """Базовый класс декларативного автомата с типизированным контекстом."""

    _context_type: type[AutomatonContext] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, "__orig_bases__", ()):
            if get_origin(base) is Automaton:
                context_type = get_args(base)[0]
                if isinstance(context_type, type) and issubclass(
                    context_type, AutomatonContext
                ):
                    cls._context_type = context_type
                break

    def emit(
        self,
        ctx: ContextT,
        operation: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Публикует требуемую команду через runtime текущего контекста."""

        ctx._ciao_runtime_services().emit(ctx, operation, *args, **kwargs)

    def query(
        self,
        ctx: ContextT,
        operation: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Синхронно выполняет требуемый запрос через Connection."""

        return ctx._ciao_runtime_services().query(ctx, operation, *args, **kwargs)


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
