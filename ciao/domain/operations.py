"""Декларации предоставляемых и требуемых операций автоматов."""

from __future__ import annotations

from enum import Enum
from inspect import Parameter, Signature, signature
from typing import Any, Callable, overload


class OperationKind(str, Enum):
    """Семантический вид операции."""

    COMMAND = "command"
    QUERY = "query"


class OperationDirection(str, Enum):
    """Направление операции относительно автоматного класса."""

    PROVIDED = "provided"
    REQUIRED = "required"


class Operation:
    """Неизменяемое описание операции, созданное публичным декоратором."""

    def __init__(
        self,
        function: Callable[..., Any],
        *,
        kind: OperationKind,
        direction: OperationDirection,
        external: bool = False,
        text: str | None = None,
    ) -> None:
        if text is not None and not isinstance(text, str):
            raise TypeError("Operation.text должен быть строкой или None")
        self.function = function
        self.kind = kind
        self.direction = direction
        self.external = external
        self._text = text
        self.name = function.__name__
        self.owner: type[Any] | None = None
        self.__doc__ = function.__doc__

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Operation:
        # Операция остаётся декларативным endpoint и не превращается в bound method.
        return self

    @property
    def qualified_name(self) -> str:
        owner_name = self.owner.__name__ if self.owner is not None else "<unbound>"
        return f"{owner_name}.{self.name}"

    @property
    def text(self) -> str | None:
        """Необязательное описание required-операции для диаграммы."""

        return self._text

    @property
    def declared_signature(self) -> Signature:
        return signature(self.function)

    @property
    def payload_signature(self) -> Signature:
        """Возвращает сигнатуру данных сообщения без ``self`` и injected ``ctx``."""

        parameters = list(self.declared_signature.parameters.values())
        if parameters and parameters[0].name == "self":
            parameters.pop(0)
        if parameters and parameters[0].name == "ctx":
            parameters.pop(0)
        return self.declared_signature.replace(parameters=parameters)

    @property
    def return_annotation(self) -> Any:
        return self.declared_signature.return_annotation

    def bind_payload(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Проверяет вызов и нормализует параметры сообщения по именам."""

        bound = self.payload_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)

    def __repr__(self) -> str:
        return (
            f"Operation({self.qualified_name}, "
            f"{self.direction.value} {self.kind.value}, external={self.external})"
        )


def _operation(
    function: Callable[..., Any],
    *,
    kind: OperationKind,
    direction: OperationDirection,
    external: bool = False,
    text: str | None = None,
) -> Operation:
    return Operation(
        function,
        kind=kind,
        direction=direction,
        external=external,
        text=text,
    )


_MISSING = object()
_OperationDecorator = Callable[[Callable[..., Any]], Operation]


def _validated_text(value: object, decorator_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{decorator_name}: text должен быть строкой")
    return value


@overload
def provided_command(
    function: Callable[..., Any],
    *,
    external: bool = False,
) -> Operation: ...


@overload
def provided_command(
    function: None = None,
    *,
    external: bool = False,
) -> Callable[[Callable[..., Any]], Operation]: ...


def provided_command(
    function: Callable[..., Any] | None = None,
    *,
    external: bool = False,
) -> Operation | Callable[[Callable[..., Any]], Operation]:
    """Объявляет команду, предоставляемую автоматным классом."""

    def decorate(actual: Callable[..., Any]) -> Operation:
        return _operation(
            actual,
            kind=OperationKind.COMMAND,
            direction=OperationDirection.PROVIDED,
            external=external,
        )

    return decorate(function) if function is not None else decorate


@overload
def required_command(function: Callable[..., Any], /) -> Operation: ...


@overload
def required_command(*, text: str) -> _OperationDecorator: ...


def required_command(
    function: Callable[..., Any] | object = _MISSING,
    /,
    *,
    text: str | object = _MISSING,
) -> Operation | _OperationDecorator:
    """Объявляет required-команду и необязательный текст для диаграммы."""

    has_function = function is not _MISSING
    has_text = text is not _MISSING
    if has_function:
        if has_text:
            raise TypeError("Для text используйте параметризованный @required_command")
        if not callable(function):
            raise TypeError("@required_command может декорировать только callable")
        return _operation(
            function,
            kind=OperationKind.COMMAND,
            direction=OperationDirection.REQUIRED,
        )
    if not has_text:
        raise TypeError(
            "Форма @required_command() не поддерживается; "
            "используйте @required_command"
        )
    validated_text = _validated_text(text, "@required_command")

    def decorate(actual: Callable[..., Any]) -> Operation:
        return _operation(
            actual,
            kind=OperationKind.COMMAND,
            direction=OperationDirection.REQUIRED,
            text=validated_text,
        )

    return decorate


@overload
def provided_query(
    function: Callable[..., Any],
    *,
    external: bool = False,
) -> Operation: ...


@overload
def provided_query(
    function: None = None,
    *,
    external: bool = False,
) -> Callable[[Callable[..., Any]], Operation]: ...


def provided_query(
    function: Callable[..., Any] | None = None,
    *,
    external: bool = False,
) -> Operation | Callable[[Callable[..., Any]], Operation]:
    """Объявляет синхронный запрос, предоставляемый автоматным классом."""

    def decorate(actual: Callable[..., Any]) -> Operation:
        return _operation(
            actual,
            kind=OperationKind.QUERY,
            direction=OperationDirection.PROVIDED,
            external=external,
        )

    return decorate(function) if function is not None else decorate


@overload
def required_query(function: Callable[..., Any], /) -> Operation: ...


@overload
def required_query(*, text: str) -> _OperationDecorator: ...


def required_query(
    function: Callable[..., Any] | object = _MISSING,
    /,
    *,
    text: str | object = _MISSING,
) -> Operation | _OperationDecorator:
    """Объявляет required-query и необязательный текст для диаграммы."""

    has_function = function is not _MISSING
    has_text = text is not _MISSING
    if has_function:
        if has_text:
            raise TypeError("Для text используйте параметризованный @required_query")
        if not callable(function):
            raise TypeError("@required_query может декорировать только callable")
        return _operation(
            function,
            kind=OperationKind.QUERY,
            direction=OperationDirection.REQUIRED,
        )
    if not has_text:
        raise TypeError(
            "Форма @required_query() не поддерживается; используйте @required_query"
        )
    validated_text = _validated_text(text, "@required_query")

    def decorate(actual: Callable[..., Any]) -> Operation:
        return _operation(
            actual,
            kind=OperationKind.QUERY,
            direction=OperationDirection.REQUIRED,
            text=validated_text,
        )

    return decorate


def operation_parameters(operation: Operation) -> tuple[Parameter, ...]:
    """Возвращает параметры полезной нагрузки в объявленном порядке."""

    return tuple(operation.payload_signature.parameters.values())
