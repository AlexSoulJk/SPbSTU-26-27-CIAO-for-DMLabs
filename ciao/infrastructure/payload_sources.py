"""UI-независимые источники типизированной нагрузки внешних событий."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Generic, TypeVar


PayloadT = TypeVar("PayloadT")


class PayloadSource(ABC, Generic[PayloadT]):
    """Отложенно получает один payload и проверяет его заявленный тип."""

    def __init__(self, payload_type: type[PayloadT]) -> None:
        if not isinstance(payload_type, type):
            raise TypeError("payload_type должен быть типом")
        self._payload_type = payload_type

    @property
    def payload_type(self) -> type[PayloadT]:
        return self._payload_type

    def read(self) -> PayloadT:
        """Получает значение и отклоняет нарушение объявленного типа."""

        payload = self._read()
        if type(payload) is not self._payload_type:
            raise TypeError(
                f"PayloadSource ожидал {self._payload_type.__name__}, "
                f"получен {type(payload).__name__}"
            )
        return payload

    @abstractmethod
    def _read(self) -> PayloadT:
        """Реализует получение значения без дублирования общей проверки типа."""


class FactoryPayloadSource(PayloadSource[PayloadT]):
    """Получает актуальный payload вызовом фабрики без аргументов."""

    def __init__(
        self,
        payload_type: type[PayloadT],
        factory: Callable[[], PayloadT],
    ) -> None:
        if not callable(factory):
            raise TypeError("factory должен быть callable")
        super().__init__(payload_type)
        self._factory = factory

    def _read(self) -> PayloadT:
        return self._factory()


class ConstantPayloadSource(PayloadSource[PayloadT]):
    """Возвращает один заранее подготовленный payload."""

    def __init__(self, payload: PayloadT) -> None:
        super().__init__(type(payload))
        self._payload = payload

    def _read(self) -> PayloadT:
        return self._payload
