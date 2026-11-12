"""Общие примитивы управления жизненным циклом инфраструктурных регистраций."""

from __future__ import annotations

from threading import Lock
from typing import Callable


class Subscription:
    """Идемпотентный потокобезопасный token одной долгоживущей регистрации."""

    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose_callback: Callable[[], None] | None = dispose
        self._lock = Lock()

    @property
    def active(self) -> bool:
        """Показывает, может ли регистрация всё ещё быть освобождена."""

        with self._lock:
            return self._dispose_callback is not None

    def dispose(self) -> None:
        """Атомарно деактивирует token и ровно один раз вызывает очистку."""

        with self._lock:
            callback = self._dispose_callback
            self._dispose_callback = None
        # Пользовательская очистка вызывается вне lock: она может обратиться
        # обратно к владельцу регистрации и не должна приводить к deadlock.
        if callback is not None:
            callback()

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.dispose()
        return False
