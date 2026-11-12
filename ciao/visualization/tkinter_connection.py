"""Tkinter-адаптер UIConnection с пошаговым ``after``-pump Runtime."""

from __future__ import annotations

import logging
import tkinter as tk
import weakref
from collections.abc import Callable
from threading import Lock, get_ident
from tkinter import ttk
from weakref import WeakKeyDictionary

from ciao.infrastructure.errors import (
    ExternalHandlerExecutionError,
    RuntimeExecutionError,
    RuntimeThreadAffinityError,
    StepLimitExceeded,
)
from ciao.infrastructure.lifecycle import Subscription
from ciao.infrastructure.runtime import Runtime

from .ui import (
    BaseWindow,
    UIBindingConflictError,
    UIConnection,
    UIErrorInfo,
    UIErrorPhase,
)


logger = logging.getLogger(__name__)


class TkConnection(UIConnection):
    """Связывает Button, FIFO Runtime и Window в потоке Tk ``mainloop``."""

    _button_owners: WeakKeyDictionary[object, object] = WeakKeyDictionary()
    _button_owners_lock = Lock()

    def __init__(
        self,
        master: tk.Misc,
        runtime: Runtime,
        window: BaseWindow,
        *,
        watcher_interval_ms: int = 25,
        max_steps: int = Runtime.DEFAULT_MAX_STEPS,
    ) -> None:
        if type(watcher_interval_ms) is not int or watcher_interval_ms <= 0:
            raise ValueError("watcher_interval_ms должен быть положительным int")
        if type(max_steps) is not int or max_steps < 0:
            raise ValueError("max_steps должен быть неотрицательным int")
        super().__init__(runtime)
        self._master: tk.Misc | None = master
        self._window: BaseWindow | None = window
        self._owner_thread = get_ident()
        self._watcher_interval_ms = watcher_interval_ms
        self._max_steps = max_steps
        self._pump_after_id: str | None = None
        self._watcher_after_id: str | None = None
        self._pump_active = False
        self._pump_blocked = False
        self._pump_steps = 0
        self._pending_tk_cleanup: list[Callable[[], None]] = []
        self._master_destroy_binding: str | None = None
        self.last_error: UIErrorInfo | None = None
        self._affinity = runtime._acquire_thread_affinity()
        try:
            self._master_destroy_binding = master.bind(
                "<Destroy>",
                self._on_master_destroy,
                add="+",
            )
            self._schedule_watcher()
        except Exception:
            self._affinity.dispose()
            raise

    def _install_event_callback(
        self,
        source: object,
        callback: Callable[[], None],
    ) -> Subscription:
        self._ensure_owner_thread()
        if not isinstance(source, (tk.Button, ttk.Button)):
            raise TypeError("TkConnection поддерживает только tk/ttk Button")
        if source.cget("command"):
            raise UIBindingConflictError("У Button уже задан command")

        marker = object()
        with self._button_owners_lock:
            if source in self._button_owners:
                raise UIBindingConflictError("Button уже принадлежит CIAO binding")
            self._button_owners[source] = marker

        try:
            source.configure(command=callback)
            installed_command = source.cget("command")
        except Exception:
            with self._button_owners_lock:
                if self._button_owners.get(source) is marker:
                    del self._button_owners[source]
            raise

        source_ref = weakref.ref(source)
        holder: dict[str, Subscription] = {}

        def on_destroy(event: object) -> None:
            widget = source_ref()
            if widget is not None and getattr(event, "widget", None) is widget:
                subscription = holder.get("subscription")
                if subscription is not None:
                    subscription.dispose()

        destroy_binding = source.bind("<Destroy>", on_destroy, add="+")

        def cleanup_widget() -> None:
            widget = source_ref()
            if widget is None:
                return
            with self._button_owners_lock:
                owned = self._button_owners.get(widget) is marker
                if owned:
                    del self._button_owners[widget]
            if not owned:
                return
            try:
                widget.unbind("<Destroy>", destroy_binding)
                if widget.winfo_exists() and widget.cget("command") == installed_command:
                    widget.configure(command="")
            except tk.TclError:
                # Уничтоженный Tcl-widget уже не требует явной очистки.
                pass

        def dispose() -> None:
            if get_ident() == self._owner_thread:
                cleanup_widget()
            else:
                with self._lock:
                    self._pending_tk_cleanup.append(cleanup_widget)

        subscription = Subscription(dispose)
        holder["subscription"] = subscription
        return subscription

    def _request_processing(self) -> None:
        # UI callback вызывается в owner thread. Фоновый send подхватит watcher.
        if get_ident() != self._owner_thread:
            return
        with self._lock:
            self._pump_blocked = False
        self._schedule_pump(reset_steps=True)

    def _schedule_pump(self, *, reset_steps: bool) -> None:
        master = self._master
        if master is None:
            return
        with self._lock:
            if (
                self._disposed
                or self._pump_blocked
                or self._pump_active
                or self._pump_after_id is not None
                or self._runtime.pending_messages == 0
            ):
                return
            if reset_steps:
                self._pump_steps = 0
            self._pump_after_id = master.after(0, self._pump_once)

    def _pump_once(self) -> None:
        with self._lock:
            self._pump_after_id = None
            if self._disposed or self._pump_active or self._pump_blocked:
                return
            self._pump_active = True

        error: RuntimeExecutionError | None = None
        try:
            if self._runtime.pending_messages == 0:
                return
            if self._pump_steps >= self._max_steps:
                error = StepLimitExceeded(
                    f"TkConnection достиг предела pump: {self._max_steps} шагов"
                )
            else:
                self._runtime.step()
                self._pump_steps += 1
        except RuntimeExecutionError as caught:
            error = caught
            logger.exception("Ошибка шага Runtime в TkConnection pump")
        finally:
            with self._lock:
                self._pump_active = False

        if error is not None:
            with self._lock:
                self._pump_blocked = True
            self._handle_runtime_error(error)
            return
        self._schedule_pump(reset_steps=False)

    def _schedule_watcher(self) -> None:
        master = self._master
        if master is None:
            return
        with self._lock:
            if self._disposed or self._watcher_after_id is not None:
                return
            self._watcher_after_id = master.after(
                self._watcher_interval_ms,
                self._watch_fifo,
            )

    def _watch_fifo(self) -> None:
        with self._lock:
            self._watcher_after_id = None
        self._run_pending_tk_cleanup()
        if self.disposed:
            return
        self._schedule_pump(reset_steps=True)
        self._schedule_watcher()

    def _handle_runtime_error(self, error: RuntimeExecutionError) -> None:
        phase = (
            UIErrorPhase.EXTERNAL_HANDLER
            if isinstance(error, ExternalHandlerExecutionError)
            else UIErrorPhase.RUNTIME
        )
        trace = self._runtime.trace
        last_event = trace[-1] if trace else None
        info = UIErrorInfo(
            title="Ошибка исполнения CIAO",
            message=str(error),
            exception_type=type(error).__name__,
            endpoint=(
                f"{last_event.object_name}.{last_event.operation}"
                if last_event is not None
                else "Runtime"
            ),
            phase=phase,
            step_number=(last_event.step_number if last_event is not None else None),
        )
        self.last_error = info
        self._present_error(info)

    def _present_error(self, error: UIErrorInfo) -> None:
        window = self._window
        master = self._master
        if window is None or master is None:
            return
        try:
            window.show_error(error)
        except Exception as presenter_error:
            logger.exception("Ошибка BaseWindow.show_error")
            master.report_callback_exception(
                type(presenter_error),
                presenter_error,
                presenter_error.__traceback__,
            )

    def _dispose_platform(self) -> None:
        self._affinity.dispose()
        if get_ident() == self._owner_thread:
            self._finish_tk_dispose()
        else:
            with self._lock:
                self._pending_tk_cleanup.append(self._finish_tk_dispose)

    def _finish_tk_dispose(self) -> None:
        master = self._master
        if master is None:
            return
        self._run_pending_tk_cleanup()
        for after_id in (self._pump_after_id, self._watcher_after_id):
            if after_id is None:
                continue
            try:
                master.after_cancel(after_id)
            except tk.TclError:
                pass
        self._pump_after_id = None
        self._watcher_after_id = None
        if self._master_destroy_binding is not None:
            try:
                master.unbind("<Destroy>", self._master_destroy_binding)
            except tk.TclError:
                pass
        self._master_destroy_binding = None
        self._window = None
        self._master = None

    def _run_pending_tk_cleanup(self) -> None:
        with self._lock:
            cleanups = tuple(self._pending_tk_cleanup)
            self._pending_tk_cleanup.clear()
        for cleanup in cleanups:
            cleanup()

    def _on_master_destroy(self, event: object) -> None:
        if getattr(event, "widget", None) is self._master:
            self.dispose()

    def _ensure_owner_thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeThreadAffinityError(
                "Tk API можно настраивать только из owner thread"
            )
