"""Декларации условий, действий и переходов."""

from __future__ import annotations

from typing import Any, Callable, overload

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

    def __init__(
        self,
        function: Callable[..., Any],
        *,
        emit: Operation | None = None,
        emits: tuple[Operation, ...] | None = None,
    ) -> None:
        super().__init__(function)
        self._emit = emit
        self._emits = emits

    @property
    def emit(self) -> Operation | None:
        """Единичная required-команда из формы ``emit=``."""

        return self._emit

    @property
    def emits(self) -> tuple[Operation, ...] | None:
        """Кортеж required-команд из формы ``emits=``."""

        return self._emits

    @property
    def outgoing_commands(self) -> tuple[Operation, ...]:
        """Возвращает потенциальные required-команды в порядке объявления."""

        if self.emit is not None:
            return (self.emit,)
        return self.emits or ()


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


_MISSING = object()
_ActionDecorator = Callable[[Callable[..., Any]], Action]


@overload
def action(function: Callable[..., Any], /) -> Action: ...


@overload
def action(*, emit: Operation) -> _ActionDecorator: ...


@overload
def action(*, emits: tuple[Operation, ...]) -> _ActionDecorator: ...


def action(
    function: Callable[..., Any] | object = _MISSING,
    /,
    *,
    emit: Operation | object = _MISSING,
    emits: tuple[Operation, ...] | object = _MISSING,
) -> Action | _ActionDecorator:
    """Объявляет действие и его потенциальные required-команды.

    Поддерживаются ровно три формы:

    - ``@action`` — без capability-параметра;
    - ``@action(emit=command)`` — ожидает в методе параметр ``Emit``;
    - ``@action(emits=(command, ...))`` — ожидает параметр ``Emits``.

    Точное соответствие аннотации и метаданных проверяет компилятор.
    """

    has_function = function is not _MISSING
    has_emit = emit is not _MISSING
    has_emits = emits is not _MISSING

    if has_function:
        if has_emit or has_emits:
            raise TypeError("Для emit/emits используйте параметризованный @action")
        if not callable(function):
            raise TypeError("@action может декорировать только callable")
        return Action(function)

    if not has_emit and not has_emits:
        raise TypeError("Форма @action() не поддерживается; используйте @action")
    if has_emit and has_emits:
        raise TypeError("Аргументы emit и emits взаимоисключаются")
    if has_emit:
        if emit is None:
            raise TypeError("emit должен ссылаться на required-команду")

        def decorate(actual: Callable[..., Any]) -> Action:
            return Action(actual, emit=emit)  # type: ignore[arg-type]

        return decorate

    if not isinstance(emits, tuple):
        raise TypeError("emits должен быть непустым кортежем required-команд")
    if not emits:
        raise TypeError("Пустой emits=() не поддерживается")

    def decorate(actual: Callable[..., Any]) -> Action:
        return Action(actual, emits=emits)

    return decorate


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
