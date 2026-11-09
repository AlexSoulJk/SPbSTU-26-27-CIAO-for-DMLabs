"""Временные capability-объекты для отправки required-команд из Action."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

from .operations import Operation


_SendCallback = Callable[[Operation, tuple[Any, ...], dict[str, Any]], None]
_ErrorFactory = Callable[[str], Exception]


class _EmissionScope:
    """Хранит общее время жизни capability одного вызова Action."""

    __slots__ = ("_action_name", "_active", "_error_factory", "_send")

    def __init__(
        self,
        action_name: str,
        send: _SendCallback,
        error_factory: _ErrorFactory,
    ) -> None:
        self._action_name = action_name
        self._send: _SendCallback | None = send
        self._error_factory = error_factory
        self._active = True

    def ensure_active(self) -> None:
        if not self._active:
            raise self._error_factory(
                f"Capability Action {self._action_name} уже недействительна"
            )

    def send(
        self,
        operation: Operation,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        self.ensure_active()
        send = self._send
        if send is None:  # Защитный инвариант на случай некорректной инвалидации.
            raise self._error_factory(
                f"Capability Action {self._action_name} уже недействительна"
            )
        send(operation, args, kwargs)

    def invalid_key(self, operation: object, allowed: tuple[Operation, ...]) -> Exception:
        requested = getattr(operation, "qualified_name", repr(operation))
        available = ", ".join(item.qualified_name for item in allowed)
        return self._error_factory(
            f"Action {self._action_name} не разрешает команду {requested}; "
            f"доступны: {available}"
        )

    def invalidate(self) -> None:
        self._active = False
        # Сохранённая ошибочно capability не должна удерживать Runtime
        # через callback после завершения действия.
        self._send = None


class Emit:
    """Временный вызываемый интерфейс одной required-команды.

    Экземпляр выдаёт Runtime только на время одного вызова ``Action``.
    Самостоятельное создание не входит в публичный контракт.
    """

    __slots__ = ("_operation", "_scope")

    def __init__(self) -> None:
        raise TypeError("Emit создаётся только Runtime")

    @classmethod
    def _ciao_create(cls, scope: _EmissionScope, operation: Operation) -> Emit:
        instance = object.__new__(cls)
        instance._scope = scope
        instance._operation = operation
        return instance

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        """Буферизует вызов привязанной required-команды."""

        self._scope.send(self._operation, args, kwargs)

    def _ciao_invalidate(self) -> None:
        self._scope.invalidate()


class Emits:
    """Неизменяемая временная коллекция разрешённых ``Emit``.

    Ключом является точный объект декларации ``@required_command``.
    """

    __slots__ = ("_allowed", "_emitters", "_scope")

    def __init__(self) -> None:
        raise TypeError("Emits создаётся только Runtime")

    @classmethod
    def _ciao_create(
        cls,
        scope: _EmissionScope,
        operations: tuple[Operation, ...],
    ) -> Emits:
        instance = object.__new__(cls)
        instance._scope = scope
        instance._allowed = operations
        emitters: Mapping[Operation, Emit] = MappingProxyType(
            {operation: Emit._ciao_create(scope, operation) for operation in operations}
        )
        instance._emitters = emitters
        return instance

    def __getitem__(self, operation: Operation) -> Emit:
        self._scope.ensure_active()
        try:
            return self._emitters[operation]
        except (KeyError, TypeError):
            raise self._scope.invalid_key(operation, self._allowed) from None

    def _ciao_invalidate(self) -> None:
        self._scope.invalidate()


def _create_emission_scope(
    action_name: str,
    send: _SendCallback,
    error_factory: _ErrorFactory,
) -> _EmissionScope:
    """Создаёт scope через закрытый мост domain→runtime."""

    return _EmissionScope(action_name, send, error_factory)
