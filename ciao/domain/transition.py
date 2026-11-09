"""Декларации условий, действий и переходов."""

from __future__ import annotations

from typing import Any, Callable, overload

from .model import State
from .operations import Operation


class Behavior:
    """Базовое декларативное описание пользовательского обработчика."""

    role = "behavior"

    def __init__(
        self,
        function: Callable[..., Any],
        *,
        text: str | None = None,
    ) -> None:
        if text is not None and not isinstance(text, str):
            raise TypeError("Behavior.text должен быть строкой или None")
        self.function = function
        self.name = function.__name__
        self.text = text
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
        text: str | None = None,
    ) -> None:
        super().__init__(function, text=text)
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
    """Декларативное правило перехода между управляющими состояниями.

    ``otherwise=True`` задаёт явную резервную ветвь группы ``(source, event)``.
    Совместимость с Guard и соседними переходами проверяет компилятор.
    """

    def __init__(
        self,
        *,
        source: State,
        event: Operation,
        target: State,
        guard: Guard | None = None,
        actions: tuple[Action, ...] = (),
        otherwise: bool = False,
    ) -> None:
        if type(otherwise) is not bool:
            raise TypeError("Transition.otherwise должен иметь точный тип bool")
        self.source = source
        self.event = event
        self.target = target
        self.guard = guard
        self.actions = tuple(actions)
        self.otherwise = otherwise
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


_MISSING = object()
_GuardDecorator = Callable[[Callable[..., Any]], Guard]
_ActionDecorator = Callable[[Callable[..., Any]], Action]


def _validated_text(value: object, decorator_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{decorator_name}: text должен быть строкой")
    return value


@overload
def guard(function: Callable[..., Any], /) -> Guard: ...


@overload
def guard(*, text: str) -> _GuardDecorator: ...


def guard(
    function: Callable[..., Any] | object = _MISSING,
    /,
    *,
    text: str | object = _MISSING,
) -> Guard | _GuardDecorator:
    """Объявляет условие и необязательный текст для диаграммы."""

    has_function = function is not _MISSING
    has_text = text is not _MISSING

    if has_function:
        if has_text:
            raise TypeError("Для text используйте параметризованный @guard")
        if not callable(function):
            raise TypeError("@guard может декорировать только callable")
        return Guard(function)

    if not has_text:
        raise TypeError("Форма @guard() не поддерживается; используйте @guard")
    validated_text = _validated_text(text, "@guard")

    def decorate(actual: Callable[..., Any]) -> Guard:
        return Guard(actual, text=validated_text)

    return decorate


@overload
def action(function: Callable[..., Any], /) -> Action: ...


@overload
def action(*, text: str) -> _ActionDecorator: ...


@overload
def action(*, emit: Operation, text: str = ...) -> _ActionDecorator: ...


@overload
def action(
    *,
    emits: tuple[Operation, ...],
    text: str = ...,
) -> _ActionDecorator: ...


def action(
    function: Callable[..., Any] | object = _MISSING,
    /,
    *,
    emit: Operation | object = _MISSING,
    emits: tuple[Operation, ...] | object = _MISSING,
    text: str | object = _MISSING,
) -> Action | _ActionDecorator:
    """Объявляет действие и его потенциальные required-команды.

    Поддерживаются bare-форма и параметризованные формы:

    - ``@action`` — без capability-параметра;
    - ``@action(text="...")`` — с пояснением для диаграммы;
    - ``@action(emit=command)`` — ожидает в методе параметр ``Emit``;
    - ``@action(emits=(command, ...))`` — ожидает параметр ``Emits``.

    ``text`` также можно передать вместе с ``emit`` или ``emits``.
    Точное соответствие аннотации и метаданных проверяет компилятор.
    """

    has_function = function is not _MISSING
    has_emit = emit is not _MISSING
    has_emits = emits is not _MISSING
    has_text = text is not _MISSING

    if has_function:
        if has_emit or has_emits or has_text:
            raise TypeError(
                "Для emit/emits/text используйте параметризованный @action"
            )
        if not callable(function):
            raise TypeError("@action может декорировать только callable")
        return Action(function)

    if not has_emit and not has_emits and not has_text:
        raise TypeError("Форма @action() не поддерживается; используйте @action")
    if has_emit and has_emits:
        raise TypeError("Аргументы emit и emits взаимоисключаются")
    validated_text = None if not has_text else _validated_text(text, "@action")
    if not has_emit and not has_emits:

        def decorate_with_text(actual: Callable[..., Any]) -> Action:
            return Action(actual, text=validated_text)

        return decorate_with_text
    if has_emit:
        if emit is None:
            raise TypeError("emit должен ссылаться на required-команду")

        def decorate(actual: Callable[..., Any]) -> Action:
            return Action(  # type: ignore[arg-type]
                actual,
                emit=emit,
                text=validated_text,
            )

        return decorate

    if not isinstance(emits, tuple):
        raise TypeError("emits должен быть непустым кортежем required-команд")
    if not emits:
        raise TypeError("Пустой emits=() не поддерживается")

    def decorate(actual: Callable[..., Any]) -> Action:
        return Action(actual, emits=emits, text=validated_text)

    return decorate


def transition(
    *,
    source: State,
    event: Operation,
    target: State,
    guard: Guard | None = None,
    actions: tuple[Action, ...] = (),
    otherwise: bool = False,
) -> Transition:
    """Создаёт обычный или резервный переход как class-атрибут автомата."""

    return Transition(
        source=source,
        event=event,
        target=target,
        guard=guard,
        actions=actions,
        otherwise=otherwise,
    )
