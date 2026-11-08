"""Соединения требуемых и предоставляемых операций объектов."""

from __future__ import annotations

from dataclasses import dataclass

from .model import AutomatonObject
from .operations import Operation


@dataclass(frozen=True)
class Endpoint:
    """Неизменяемая ссылка на операцию конкретного объекта."""

    object: AutomatonObject
    operation: Operation


EndpointLike = Endpoint | tuple[AutomatonObject, Operation]


@dataclass(frozen=True)
class Connection:
    """Направленная связь required endpoint с provided endpoint."""

    required: EndpointLike
    provided: EndpointLike

    def __post_init__(self) -> None:
        object.__setattr__(self, "required", self._normalize(self.required))
        object.__setattr__(self, "provided", self._normalize(self.provided))

    @staticmethod
    def _normalize(endpoint: EndpointLike) -> Endpoint:
        if isinstance(endpoint, Endpoint):
            return endpoint
        object_ref, operation = endpoint
        return Endpoint(object_ref, operation)
