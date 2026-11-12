"""Общая, не зависящая от GUI toolkit часть подключения интерфейса к CIAO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from inspect import Parameter, _empty
from threading import RLock
from typing import Callable

from ciao.domain.connections import Endpoint, EndpointLike
from ciao.domain.operations import Operation, OperationDirection, OperationKind
from ciao.infrastructure.errors import InvalidRuntimeCallError
from ciao.infrastructure.lifecycle import Subscription
from ciao.infrastructure.payload_sources import PayloadSource
from ciao.infrastructure.runtime import Runtime


class UIErrorPhase(str, Enum):
    """Фаза, на которой UI-адаптер получил диагностируемую ошибку."""

    PAYLOAD_SOURCE = "payload_source"
    RUNTIME = "runtime"
    EXTERNAL_HANDLER = "external_handler"


@dataclass(frozen=True, slots=True)
class UIErrorInfo:
    """Безопасное для долгого хранения представление ошибки UI-границы."""

    title: str
    message: str
    exception_type: str
    endpoint: str
    phase: UIErrorPhase
    step_number: int | None = None


class UIBindingConflictError(RuntimeError):
    """Источник UI-события уже занят несовместимой живой привязкой."""


class DisposedConnectionError(RuntimeError):
    """Операция требует уже освобождённое UI-подключение."""


class BaseWindow(ABC):
    """Минимальный интерфейс Window для показа структурированной ошибки."""

    @abstractmethod
    def show_error(self, error: UIErrorInfo) -> None:
        """Отображает ошибку способом, выбранным конкретным Window."""


class UIConnection(ABC):
    """Template-method адаптер между UI-событиями и одним Runtime."""

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._lock = RLock()
        self._disposed = False
        self._subscriptions: list[Subscription] = []

    @property
    def disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def bind_event(
        self,
        source: object,
        endpoint: EndpointLike,
        *,
        payload_source: PayloadSource[object] | None = None,
    ) -> Subscription:
        """Связывает одно UI-событие с одной provided-командой Runtime."""

        self._ensure_active()
        normalized = self._validated_endpoint(
            endpoint,
            direction=OperationDirection.PROVIDED,
        )
        signature = self._runtime._compiled.definitions[
            normalized.object.automaton
        ].operation_signatures[normalized.operation]
        parameters = signature.parameters
        if len(parameters) > 1:
            raise TypeError(
                "bind_event поддерживает provided-команду без payload "
                "либо с одним DTO"
            )
        if not parameters:
            if payload_source is not None:
                raise TypeError("Для команды без payload источник запрещён")
        else:
            parameter = parameters[0]
            if parameter.annotation is _empty:
                raise TypeError("Единственный payload-параметр должен иметь аннотацию")
            if payload_source is None:
                raise TypeError("Для команды с payload требуется PayloadSource")
            if not isinstance(payload_source, PayloadSource):
                raise TypeError("payload_source должен быть PayloadSource")
            if payload_source.payload_type != parameter.annotation:
                raise TypeError(
                    f"Источник {payload_source.payload_type.__name__} несовместим "
                    f"с payload {parameter.annotation!r}"
                )

        registration_active = True

        def callback() -> None:
            nonlocal registration_active
            with self._lock:
                if self._disposed or not registration_active:
                    return
            if not parameters:
                payload = None
            else:
                assert payload_source is not None
                try:
                    payload = payload_source.read()
                except Exception as error:
                    self._present_error(
                        self._error_info(
                            error,
                            normalized,
                            UIErrorPhase.PAYLOAD_SOURCE,
                        )
                    )
                    return
            try:
                if not parameters:
                    self._runtime.send(normalized.object, normalized.operation)
                else:
                    parameter = parameters[0]
                    if parameter.kind is Parameter.KEYWORD_ONLY:
                        self._runtime.send(
                            normalized.object,
                            normalized.operation,
                            **{parameter.name: payload},
                        )
                    else:
                        self._runtime.send(
                            normalized.object,
                            normalized.operation,
                            payload,
                        )
                self._request_processing()
            except Exception as error:
                self._present_error(
                    self._error_info(error, normalized, UIErrorPhase.RUNTIME)
                )

        platform_subscription = self._install_event_callback(source, callback)

        def dispose_registration() -> None:
            nonlocal registration_active
            with self._lock:
                registration_active = False
            platform_subscription.dispose()

        subscription = Subscription(dispose_registration)
        return self._track(subscription)

    def bind_command(
        self,
        endpoint: EndpointLike,
        handler: Callable[..., object],
    ) -> Subscription:
        """Связывает external required-команду с одним внешним handler."""

        self._ensure_active()
        normalized = self._validated_endpoint(
            endpoint,
            direction=OperationDirection.REQUIRED,
        )
        subscription = self._runtime.bind_external(normalized, handler)
        return self._track(subscription)

    def dispose(self) -> None:
        """Идемпотентно запрещает callback и освобождает все регистрации."""

        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            subscriptions = tuple(self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.dispose()
        self._dispose_platform()

    def __enter__(self) -> UIConnection:
        self._ensure_active()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.dispose()
        return False

    def _validated_endpoint(
        self,
        endpoint: EndpointLike,
        *,
        direction: OperationDirection,
    ) -> Endpoint:
        try:
            if isinstance(endpoint, Endpoint):
                normalized = endpoint
            else:
                object_ref, operation = endpoint
                normalized = Endpoint(object_ref, operation)
        except (TypeError, ValueError) as error:
            raise InvalidRuntimeCallError("Некорректный EndpointLike") from error
        # snapshot — публичная проверка принадлежности объекта конкретному Runtime.
        self._runtime.snapshot(normalized.object)
        operation = normalized.operation
        if not isinstance(operation, Operation):
            raise InvalidRuntimeCallError("Endpoint должен содержать Operation")
        owner = operation.owner
        if owner is None or not issubclass(normalized.object.automaton, owner):
            raise InvalidRuntimeCallError(
                f"Операция {operation.qualified_name} не принадлежит "
                f"{normalized.object.name}"
            )
        if operation.kind is not OperationKind.COMMAND or operation.direction is not direction:
            expected = "provided" if direction is OperationDirection.PROVIDED else "required"
            raise InvalidRuntimeCallError(
                f"Ожидается {expected}-команда, получена {operation.qualified_name}"
            )
        return normalized

    def _track(self, subscription: Subscription) -> Subscription:
        with self._lock:
            if self._disposed:
                subscription.dispose()
                raise DisposedConnectionError("UIConnection уже освобождён")
            self._subscriptions.append(subscription)
        return subscription

    def _ensure_active(self) -> None:
        with self._lock:
            if self._disposed:
                raise DisposedConnectionError("UIConnection уже освобождён")

    @staticmethod
    def _error_info(
        error: Exception,
        endpoint: Endpoint,
        phase: UIErrorPhase,
    ) -> UIErrorInfo:
        return UIErrorInfo(
            title="Ошибка взаимодействия с CIAO",
            message=str(error),
            exception_type=type(error).__name__,
            endpoint=f"{endpoint.object.name}.{endpoint.operation.name}",
            phase=phase,
        )

    @abstractmethod
    def _install_event_callback(
        self,
        source: object,
        callback: Callable[[], None],
    ) -> Subscription:
        """Устанавливает callback в одном платформенном источнике события."""

    @abstractmethod
    def _request_processing(self) -> None:
        """Просит платформу начать или продолжить обработку FIFO Runtime."""

    @abstractmethod
    def _present_error(self, error: UIErrorInfo) -> None:
        """Передаёт безопасную диагностику конкретному представлению."""

    def _dispose_platform(self) -> None:
        """Освобождает платформенные ресурсы, отсутствующие в общей части."""

