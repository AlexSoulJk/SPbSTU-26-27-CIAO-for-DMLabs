"""Временные capability-объекты для синхронных required-запросов."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

from .operations import Operation


_QueryCallback = Callable[[Operation, tuple[Any, ...], dict[str, Any]], Any]
_ErrorFactory = Callable[[str], Exception]


class _QueryScope:
    """Хранит общее время жизни Query одного вызова Guard или Action."""

    __slots__ = ("_active", "_behavior_name", "_error_factory", "_invoke")

    def __init__(
        self,
        behavior_name: str,
        invoke: _QueryCallback,
        error_factory: _ErrorFactory,
    ) -> None:
        self._behavior_name = behavior_name
        self._invoke: _QueryCallback | None = invoke
        self._error_factory = error_factory
        self._active = True

    def ensure_active(self) -> None:
        if not self._active:
            raise self._error_factory(
                f"Capability обработчика {self._behavior_name} уже недействительна"
            )

    def call(
        self,
        operation: Operation,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        self.ensure_active()
        invoke = self._invoke
        if invoke is None:  # Защитный инвариант на случай повторной инвалидации.
            raise self._error_factory(
                f"Capability обработчика {self._behavior_name} уже недействительна"
            )
        return invoke(operation, args, kwargs)

    def invalid_key(self, operation: object, allowed: tuple[Operation, ...]) -> Exception:
        requested = getattr(operation, "qualified_name", repr(operation))
        available = ", ".join(item.qualified_name for item in allowed)
        return self._error_factory(
            f"Обработчик {self._behavior_name} не разрешает запрос {requested}; "
            f"доступны: {available}"
        )

    def invalidate(self) -> None:
        self._active = False
        # Сохранённая пользователем capability не должна удерживать Runtime.
        self._invoke = None


class Query:
    """Временный вызываемый интерфейс одной required-query.

    Экземпляр выдаёт Runtime только на время одного Guard или Action.
    Самостоятельное создание не входит в публичный контракт.
    """

    __slots__ = ("_operation", "_scope")

    def __init__(self) -> None:
        raise TypeError("Query создаётся только Runtime")

    @classmethod
    def _ciao_create(cls, scope: _QueryScope, operation: Operation) -> Query:
        instance = object.__new__(cls)
        instance._scope = scope
        instance._operation = operation
        return instance

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Синхронно выполняет привязанную required-query."""

        return self._scope.call(self._operation, args, kwargs)

    def _ciao_invalidate(self) -> None:
        self._scope.invalidate()


class Queries:
    """Неизменяемая временная коллекция разрешённых ``Query``."""

    __slots__ = ("_allowed", "_queries", "_scope")

    def __init__(self) -> None:
        raise TypeError("Queries создаётся только Runtime")

    @classmethod
    def _ciao_create(
        cls,
        scope: _QueryScope,
        operations: tuple[Operation, ...],
    ) -> Queries:
        instance = object.__new__(cls)
        instance._scope = scope
        instance._allowed = operations
        queries: Mapping[Operation, Query] = MappingProxyType(
            {operation: Query._ciao_create(scope, operation) for operation in operations}
        )
        instance._queries = queries
        return instance

    def __getitem__(self, operation: Operation) -> Query:
        self._scope.ensure_active()
        try:
            return self._queries[operation]
        except (KeyError, TypeError):
            raise self._scope.invalid_key(operation, self._allowed) from None

    def _ciao_invalidate(self) -> None:
        self._scope.invalidate()


def _create_query_scope(
    behavior_name: str,
    invoke: _QueryCallback,
    error_factory: _ErrorFactory,
) -> _QueryScope:
    """Создаёт scope через закрытый мост domain→runtime."""

    return _QueryScope(behavior_name, invoke, error_factory)
