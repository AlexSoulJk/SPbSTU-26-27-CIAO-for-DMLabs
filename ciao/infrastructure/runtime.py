"""Однопоточный FIFO-исполнитель с пошаговой трассировкой."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from inspect import Parameter, _empty, isfunction, ismethod, signature
from threading import Lock, get_ident
from types import MappingProxyType, NoneType
from typing import Any, Callable, Mapping, get_type_hints

from ciao.domain.connections import Endpoint, EndpointLike
from ciao.domain.emission import Emit, Emits, _create_emission_scope
from ciao.domain.model import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    AutomatonSnapshot,
    Program,
    State,
)
from ciao.domain.operations import Operation, OperationDirection, OperationKind
from ciao.domain.query import Queries, Query, _create_query_scope
from ciao.domain.transition import Behavior, Transition

from .compiler import (
    ActionInjectionPlan,
    AutomatonDefinition,
    CompiledProgram,
    OperationSignature,
    QueryInjectionPlan,
    compile_program,
)
from .errors import (
    ActionExecutionError,
    AmbiguousTransitionError,
    ExternalBindingConflictError,
    ExternalHandlerExecutionError,
    ExternalHandlerSignatureError,
    GuardExecutionError,
    InvalidRuntimeCallError,
    NoTransitionError,
    QueryExecutionError,
    QueryRoutingError,
    RuntimeExecutionError,
    RuntimeReentryError,
    RuntimeThreadAffinityError,
    StepLimitExceeded,
)
from .lifecycle import Subscription


class StepStatus(str, Enum):
    """Результат обработки одного сообщения."""

    PROCESSED = "processed"
    IGNORED = "ignored"
    EMPTY = "empty"
    ERROR = "error"


class RunStatus(str, Enum):
    """Причина завершения ``run``."""

    COMPLETED = "completed"
    LIMIT_REACHED = "limit_reached"


def _freeze_value(value: Any) -> Any:
    """Рекурсивно отделяет и замораживает данные публичной трассы."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return deepcopy(value)


def _frozen_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze_value(values)


def _message_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    """Копирует payload сообщения, сохраняя пользовательские типы контейнеров."""

    return MappingProxyType(deepcopy(dict(values)))


@dataclass(frozen=True)
class EmittedMessage:
    """Безопасное описание сообщения, созданного переходом."""

    target: str
    operation: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class StepResult:
    """Структурированный результат одного шага runtime."""

    step_number: int
    status: StepStatus
    object_name: str | None = None
    operation: str | None = None
    source_state: str | None = None
    target_state: str | None = None
    parameters: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    result: Any = None
    emitted: tuple[EmittedMessage, ...] = ()
    error: str | None = None
    transition: str | None = None


@dataclass(frozen=True)
class TraceEvent:
    """Неизменяемая запись трассы исполнения."""

    step_number: int
    status: StepStatus
    object_name: str
    operation: str
    source_state: str
    target_state: str
    parameters: Mapping[str, Any]
    result: Any
    emitted: tuple[EmittedMessage, ...]
    error: str | None = None
    transition: str | None = None


@dataclass(frozen=True)
class RunResult:
    """Итог серии шагов ``run``."""

    status: RunStatus
    steps: tuple[StepResult, ...]


@dataclass(frozen=True)
class _Message:
    target: AutomatonObject
    operation: Operation
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class _ExternalDelivery:
    source: Endpoint
    parameters: Mapping[str, Any]


_QueueMessage = _Message | _ExternalDelivery


@dataclass(frozen=True)
class _ExternalBinding:
    callback: Callable[..., Any]
    positional_names: tuple[str, ...]
    keyword_names: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class _ListenerRegistration:
    callback: Callable[[TraceEvent], None]


@dataclass
class _RuntimeObject:
    definition: AutomatonDefinition
    automaton: Automaton[Any]
    context: AutomatonContext
    state: State


@dataclass
class _ExecutionFrame:
    object_ref: AutomatonObject
    context: AutomatonContext
    phase: str
    pending: list[_QueueMessage]


class Runtime:
    """Исполняет скомпилированную программу в однопоточном FIFO-порядке."""

    DEFAULT_MAX_STEPS = 10_000

    def __init__(self, program: Program, *, strict: bool = True) -> None:
        self.strict = strict
        self._compiled: CompiledProgram = compile_program(program)
        self._queue: deque[_QueueMessage] = deque()
        self._objects: dict[AutomatonObject, _RuntimeObject] = {}
        self._trace: list[TraceEvent] = []
        self._listeners: list[_ListenerRegistration] = []
        self._external_handlers: dict[Endpoint, _ExternalBinding] = {}
        self._step_number = 0
        self._active_frame: _ExecutionFrame | None = None
        self._query_stack: list[Endpoint] = []
        self._queue_lock = Lock()
        self._trace_lock = Lock()
        self._registry_lock = Lock()
        self._execution_lock = Lock()
        self._execution_state_lock = Lock()
        self._execution_owner: int | None = None
        self._execution_phase: str | None = None
        self._affinity_thread: int | None = None
        self._affinity_leases = 0

        for object_ref in program.objects:
            definition = self._compiled.definitions[object_ref.automaton]
            context = deepcopy(object_ref.initial_context)
            self._objects[object_ref] = _RuntimeObject(
                definition=definition,
                automaton=object_ref.automaton(),
                context=context,
                state=definition.initial_state,
            )

    @property
    def pending_messages(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    @property
    def trace(self) -> tuple[TraceEvent, ...]:
        with self._trace_lock:
            return tuple(self._trace)

    def subscribe(self, listener: Callable[[TraceEvent], None]) -> Subscription:
        """Регистрирует обработчик неизменяемых событий трассы."""

        if not callable(listener):
            raise TypeError("listener должен быть callable")
        registration = _ListenerRegistration(listener)
        with self._registry_lock:
            self._listeners.append(registration)

        def dispose() -> None:
            with self._registry_lock:
                if registration in self._listeners:
                    self._listeners.remove(registration)

        return Subscription(dispose)

    def bind_external(
        self,
        endpoint: EndpointLike,
        callback: Callable[..., Any],
    ) -> Subscription:
        """Регистрирует единственный handler external required-команды."""

        normalized = self._normalize_endpoint(endpoint)
        operation = normalized.operation
        if not (
            operation.kind is OperationKind.COMMAND
            and operation.direction is OperationDirection.REQUIRED
            and operation.external
        ):
            raise InvalidRuntimeCallError(
                "bind_external принимает только external required-команду"
            )
        if not callable(callback):
            raise ExternalHandlerSignatureError("external handler должен быть callable")

        runtime_object = self._object(normalized.object)
        operation_signature = runtime_object.definition.operation_signatures[operation]
        binding = self._compile_external_binding(
            normalized,
            operation_signature,
            callback,
        )
        with self._registry_lock:
            if normalized in self._external_handlers:
                raise ExternalBindingConflictError(
                    f"Для {normalized.object.name}.{operation.name} уже задан handler"
                )
            self._external_handlers[normalized] = binding

        def dispose() -> None:
            with self._registry_lock:
                if self._external_handlers.get(normalized) is binding:
                    del self._external_handlers[normalized]

        return Subscription(dispose)

    def snapshot(self, object_ref: AutomatonObject) -> AutomatonSnapshot[Any]:
        """Возвращает отсоединённую копию контекста и текущее состояние."""

        self._ensure_not_execution_owner("snapshot")
        with self._execution_lock:
            runtime_object = self._object(object_ref)
            return AutomatonSnapshot(
                object_name=object_ref.name,
                state=runtime_object.state,
                context=deepcopy(runtime_object.context),
            )

    def send(
        self,
        target: AutomatonObject,
        operation: Operation,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Помещает внешнюю provided-команду в FIFO."""

        self._object(target)
        self._ensure_endpoint_owner(target, operation)
        if not (
            operation.kind is OperationKind.COMMAND
            and operation.direction is OperationDirection.PROVIDED
        ):
            raise InvalidRuntimeCallError("send принимает только provided-команду")
        parameters = operation.bind_payload(*args, **kwargs)
        with self._queue_lock:
            self._queue.append(
                _Message(target, operation, _message_mapping(parameters))
            )

    def _emit_from_capability(
        self,
        frame: _ExecutionFrame,
        operation: Operation,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Буферизует required-команду активной capability."""

        if self._active_frame is not frame or frame.phase != "action":
            raise InvalidRuntimeCallError(
                "Emit не принадлежит текущему Action"
            )
        if not (
            operation.kind is OperationKind.COMMAND
            and operation.direction is OperationDirection.REQUIRED
        ):
            raise InvalidRuntimeCallError("emit принимает только required-команду")
        self._ensure_endpoint_owner(frame.object_ref, operation)
        parameters = operation.bind_payload(*args, **kwargs)
        if operation.external:
            frame.pending.append(
                _ExternalDelivery(
                    Endpoint(frame.object_ref, operation),
                    _message_mapping(parameters),
                )
            )
            return

        target = self._route(frame.object_ref, operation)
        target_parameters = self._translate_parameters(
            operation,
            target.operation,
            parameters,
        )
        # Сообщение остаётся локальным до успешного завершения всех действий.
        frame.pending.append(
            _Message(
                target.object,
                target.operation,
                _message_mapping(target_parameters),
            )
        )

    def query(
        self,
        target_object: AutomatonObject,
        operation: Operation,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Выполняет внешний вызов provided-query конкретного объекта."""

        self._object(target_object)
        if not (
            operation.kind is OperationKind.QUERY
            and operation.direction is OperationDirection.PROVIDED
        ):
            raise InvalidRuntimeCallError("Runtime.query принимает provided-запрос")
        self._ensure_endpoint_owner(target_object, operation)
        target = Endpoint(target_object, operation)
        parameters = operation.bind_payload(*args, **kwargs)
        return self._execute_query(None, target, parameters)

    def _query_from_capability(
        self,
        frame: _ExecutionFrame,
        operation: Operation,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Выполняет required-query capability текущего Guard или Action."""

        if self._active_frame is not frame or frame.phase not in ("guard", "action"):
            raise InvalidRuntimeCallError(
                "Query не принадлежит текущему Guard или Action"
            )
        if not (
            operation.kind is OperationKind.QUERY
            and operation.direction is OperationDirection.REQUIRED
        ):
            raise InvalidRuntimeCallError("Query принимает только required-query")
        self._ensure_endpoint_owner(frame.object_ref, operation)
        source = Endpoint(frame.object_ref, operation)
        target = self._route(frame.object_ref, operation)
        parameters = operation.bind_payload(*args, **kwargs)
        target_parameters = self._translate_parameters(
            operation,
            target.operation,
            parameters,
        )
        return self._execute_query(source, target, target_parameters)

    def _execute_query(
        self,
        source: Endpoint | None,
        target: Endpoint,
        parameters: Mapping[str, Any],
    ) -> Any:
        """Исполняет provider и добавляет предметный контекст к его ошибке."""

        if target in self._query_stack:
            raise QueryRoutingError(
                f"Обнаружен рекурсивный цикл запросов на {target.operation.qualified_name}"
            )
        self._query_stack.append(target)
        try:
            try:
                return self._invoke_query(target, parameters)
            except (QueryExecutionError, QueryRoutingError, RuntimeReentryError):
                raise
            except Exception as error:
                source_name = (
                    f"{source.object.name}.{source.operation.name}"
                    if source is not None
                    else "внешнее окружение"
                )
                raise QueryExecutionError(
                    f"Ошибка Query {source_name} -> "
                    f"{target.object.name}.{target.operation.name}: {error}"
                ) from error
        finally:
            self._query_stack.pop()

    def step(self) -> StepResult:
        """Сериализованно обрабатывает ровно одно сообщение FIFO."""

        self._begin_execution("step")
        try:
            return self._step_impl()
        finally:
            self._end_execution()

    def _step_impl(self) -> StepResult:
        """Обрабатывает ровно одно сообщение FIFO."""

        with self._queue_lock:
            if not self._queue:
                return StepResult(
                    step_number=self._step_number,
                    status=StepStatus.EMPTY,
                )
            message = self._queue.popleft()
        self._step_number += 1
        if isinstance(message, _ExternalDelivery):
            return self._deliver_external(message)

        runtime_object = self._object(message.target)
        source_state = runtime_object.state

        matching = tuple(
            item
            for item in runtime_object.definition.transitions
            if item.source is source_state and item.event is message.operation
        )
        fallback = next((item for item in matching if item.otherwise), None)
        unconditional = next(
            (
                item
                for item in matching
                if item.guard is None and not item.otherwise
            ),
            None,
        )
        accepted_transitions: list[Transition] = []
        for item in (item for item in matching if item.guard is not None):
            frame = _ExecutionFrame(
                message.target,
                runtime_object.context,
                "guard",
                [],
            )
            self._active_frame = frame
            query_plan = runtime_object.definition.guard_query_injections[item.guard]
            query_capability = self._create_query_capability(
                query_plan,
                item.guard.qualified_name,
                frame,
            )
            injected = (
                {query_plan.parameter_name: query_capability}
                if query_plan is not None and query_capability is not None
                else {}
            )
            try:
                try:
                    accepted = self._invoke_behavior(
                        item.guard,
                        runtime_object,
                        message.parameters,
                        injected=injected,
                    )
                finally:
                    if query_capability is not None:
                        query_capability._ciao_invalidate()
            except RuntimeReentryError as error:
                self._record_error(message, source_state, error)
                raise
            except Exception as error:
                wrapped = GuardExecutionError(
                    f"Ошибка Guard {item.guard.qualified_name}: {error}"
                )
                self._record_error(message, source_state, wrapped)
                raise wrapped from error
            finally:
                self._active_frame = None
            if accepted:
                accepted_transitions.append(item)

        if len(accepted_transitions) > 1:
            error = AmbiguousTransitionError(
                f"Для {message.target.name}.{message.operation.name} применимы "
                f"{len(accepted_transitions)} перехода"
            )
            self._record_error(message, source_state, error)
            raise error

        selected = (
            accepted_transitions[0]
            if accepted_transitions
            else fallback or unconditional
        )
        if selected is None:
            missing_group = not matching
            reason = (
                f"Для состояния {source_state.name} и события "
                f"{message.operation.name} переходы не объявлены"
                if missing_group
                else f"Все Guard ложны, ветвь otherwise отсутствует для "
                f"{message.target.name}.{message.operation.name} в состоянии "
                f"{source_state.name}"
            )
            if self.strict:
                error = NoTransitionError(reason)
                self._record_error(message, source_state, error)
                raise error
            return self._record_ignored(message, source_state, reason)

        frame = _ExecutionFrame(
            message.target,
            runtime_object.context,
            "action",
            [],
        )
        self._active_frame = frame
        try:
            for action_item in selected.actions:
                emission_plan = runtime_object.definition.action_injections[action_item]
                query_plan = runtime_object.definition.action_query_injections[
                    action_item
                ]
                emission_capability = self._create_action_capability(
                    emission_plan,
                    action_item.qualified_name,
                    frame,
                )
                query_capability = self._create_query_capability(
                    query_plan,
                    action_item.qualified_name,
                    frame,
                )
                injected: dict[str, Any] = {}
                if emission_plan is not None and emission_capability is not None:
                    injected[emission_plan.parameter_name] = emission_capability
                if query_plan is not None and query_capability is not None:
                    injected[query_plan.parameter_name] = query_capability
                try:
                    self._invoke_behavior(
                        action_item,
                        runtime_object,
                        message.parameters,
                        injected=injected,
                    )
                finally:
                    if emission_capability is not None:
                        emission_capability._ciao_invalidate()
                    if query_capability is not None:
                        query_capability._ciao_invalidate()
        except RuntimeReentryError as error:
            self._record_error(
                message,
                source_state,
                error,
                transition=selected.name,
            )
            raise
        except Exception as error:
            wrapped = ActionExecutionError(
                f"Ошибка Action в переходе {selected.qualified_name}: {error}"
            )
            self._record_error(
                message,
                source_state,
                wrapped,
                transition=selected.name,
            )
            raise wrapped from error
        finally:
            self._active_frame = None

        runtime_object.state = selected.target
        with self._queue_lock:
            self._queue.extend(frame.pending)
        emitted = tuple(self._message_info(item) for item in frame.pending)
        result = StepResult(
            step_number=self._step_number,
            status=StepStatus.PROCESSED,
            object_name=message.target.name,
            operation=message.operation.name,
            transition=selected.name,
            source_state=source_state.name,
            target_state=selected.target.name,
            parameters=_frozen_mapping(message.parameters),
            emitted=emitted,
        )
        self._record_trace(result)
        return result

    def run(self, *, max_steps: int | None = DEFAULT_MAX_STEPS) -> RunResult:
        """Обрабатывает очередь до опустошения или заданного предела."""

        if max_steps is not None and max_steps < 0:
            raise ValueError("max_steps не может быть отрицательным")
        self._begin_execution("run")
        try:
            results: list[StepResult] = []
            while self._has_pending_messages():
                if max_steps is not None and len(results) >= max_steps:
                    if self.strict:
                        raise StepLimitExceeded(
                            f"Достигнут предел run: {max_steps} шагов"
                        )
                    return RunResult(RunStatus.LIMIT_REACHED, tuple(results))
                results.append(self._step_impl())
            return RunResult(RunStatus.COMPLETED, tuple(results))
        finally:
            self._end_execution()

    def _has_pending_messages(self) -> bool:
        with self._queue_lock:
            return bool(self._queue)

    def _begin_execution(self, phase: str) -> None:
        current_thread = get_ident()
        with self._execution_state_lock:
            if self._execution_owner == current_thread:
                raise RuntimeReentryError(
                    f"Runtime.{phase} нельзя вызывать из активного "
                    f"{self._execution_phase}"
                )
            affinity = self._affinity_thread
        if affinity is not None and affinity != current_thread:
            raise RuntimeThreadAffinityError(
                "Runtime закреплён за другим потоком исполнения"
            )

        self._execution_lock.acquire()
        try:
            with self._execution_state_lock:
                # Affinity могла быть установлена, пока поток ожидал executor.
                affinity = self._affinity_thread
                if affinity is not None and affinity != current_thread:
                    raise RuntimeThreadAffinityError(
                        "Runtime закреплён за другим потоком исполнения"
                    )
                self._execution_owner = current_thread
                self._execution_phase = phase
        except Exception:
            self._execution_lock.release()
            raise

    def _end_execution(self) -> None:
        with self._execution_state_lock:
            self._execution_owner = None
            self._execution_phase = None
        self._execution_lock.release()

    def _ensure_not_execution_owner(self, operation: str) -> None:
        with self._execution_state_lock:
            if self._execution_owner == get_ident():
                raise RuntimeReentryError(
                    f"Runtime.{operation} нельзя вызывать из активного шага"
                )

    def _acquire_thread_affinity(self) -> Subscription:
        """Закрепляет executor за текущим потоком на срок жизни подключения."""

        current_thread = get_ident()
        with self._execution_state_lock:
            if (
                self._affinity_thread is not None
                and self._affinity_thread != current_thread
            ):
                raise RuntimeThreadAffinityError(
                    "Runtime уже закреплён за другим потоком"
                )
            self._affinity_thread = current_thread
            self._affinity_leases += 1
        released = False

        def dispose() -> None:
            nonlocal released
            with self._execution_state_lock:
                if released:
                    return
                released = True
                self._affinity_leases -= 1
                if self._affinity_leases == 0:
                    self._affinity_thread = None

        return Subscription(dispose)

    def _object(self, object_ref: AutomatonObject) -> _RuntimeObject:
        try:
            return self._objects[object_ref]
        except KeyError as error:
            raise InvalidRuntimeCallError("Объект не принадлежит этому Runtime") from error

    def _normalize_endpoint(self, endpoint: EndpointLike) -> Endpoint:
        if isinstance(endpoint, Endpoint):
            normalized = endpoint
        else:
            try:
                object_ref, operation = endpoint
            except (TypeError, ValueError) as error:
                raise InvalidRuntimeCallError(
                    "endpoint должен быть Endpoint или парой (object, operation)"
                ) from error
            normalized = Endpoint(object_ref, operation)

        runtime_object = self._object(normalized.object)
        self._ensure_endpoint_owner(normalized.object, normalized.operation)
        if normalized.operation not in runtime_object.definition.operations:
            raise InvalidRuntimeCallError(
                f"Операция {normalized.operation.qualified_name} не объявлена "
                f"у {normalized.object.name}"
            )
        return normalized

    @staticmethod
    def _ensure_endpoint_owner(object_ref: AutomatonObject, operation: Operation) -> None:
        owner = operation.owner
        if owner is None or not issubclass(object_ref.automaton, owner):
            raise InvalidRuntimeCallError(
                f"Операция {operation.qualified_name} не принадлежит {object_ref.name}"
            )

    def _route(self, object_ref: AutomatonObject, operation: Operation) -> Endpoint:
        endpoint = Endpoint(object_ref, operation)
        try:
            return self._compiled.routes[endpoint]
        except KeyError as error:
            raise QueryRoutingError(
                f"Для {object_ref.name}.{operation.name} не задан Connection"
            ) from error

    def _invoke_behavior(
        self,
        behavior: Behavior,
        runtime_object: _RuntimeObject,
        parameters: Mapping[str, Any],
        *,
        injected: Mapping[str, Any] = MappingProxyType({}),
    ) -> Any:
        function_parameters = list(signature(behavior.function).parameters.values())[2:]
        selected: dict[str, Any] = dict(injected)
        for parameter in function_parameters:
            if parameter.name in injected:
                continue
            if parameter.name in parameters:
                selected[parameter.name] = parameters[parameter.name]
            elif parameter.default is Parameter.empty:
                raise RuntimeExecutionError(
                    f"Для {behavior.qualified_name} отсутствует параметр {parameter.name}"
                )
        return behavior.function(
            runtime_object.automaton,
            runtime_object.context,
            **selected,
        )

    def _create_action_capability(
        self,
        plan: ActionInjectionPlan | None,
        action_name: str,
        frame: _ExecutionFrame,
    ) -> Emit | Emits | None:
        if plan is None:
            return None

        scope = _create_emission_scope(
            action_name,
            lambda operation, args, kwargs: self._emit_from_capability(
                frame,
                operation,
                args,
                kwargs,
            ),
            InvalidRuntimeCallError,
        )
        if plan.capability_type is Emit:
            return Emit._ciao_create(scope, plan.commands[0])
        return Emits._ciao_create(scope, plan.commands)

    def _create_query_capability(
        self,
        plan: QueryInjectionPlan | None,
        behavior_name: str,
        frame: _ExecutionFrame,
    ) -> Query | Queries | None:
        if plan is None:
            return None

        scope = _create_query_scope(
            behavior_name,
            lambda operation, args, kwargs: self._query_from_capability(
                frame,
                operation,
                args,
                kwargs,
            ),
            InvalidRuntimeCallError,
        )
        if plan.capability_type is Query:
            return Query._ciao_create(scope, plan.queries[0])
        return Queries._ciao_create(scope, plan.queries)

    def _invoke_query(self, endpoint: Endpoint, parameters: Mapping[str, Any]) -> Any:
        runtime_object = self._object(endpoint.object)
        function_parameters = list(
            signature(endpoint.operation.function).parameters.values()
        )
        arguments: list[Any] = [runtime_object.automaton]
        if len(function_parameters) > 1 and function_parameters[1].name == "ctx":
            arguments.append(runtime_object.context)
        return endpoint.operation.function(*arguments, **dict(parameters))

    def _deliver_external(self, message: _ExternalDelivery) -> StepResult:
        """Обрабатывает одну внешнюю доставку как самостоятельный шаг FIFO."""

        runtime_object = self._object(message.source.object)
        state = runtime_object.state
        with self._registry_lock:
            binding = self._external_handlers.get(message.source)
        if binding is not None:
            args = tuple(
                message.parameters[name] for name in binding.positional_names
            )
            kwargs = {
                name: message.parameters[name] for name in binding.keyword_names
            }
            try:
                binding.callback(*args, **kwargs)
            except RuntimeReentryError as error:
                self._record_external_error(message, state, error)
                raise
            except Exception as error:
                wrapped = ExternalHandlerExecutionError(
                    "Ошибка external handler для "
                    f"{message.source.object.name}.{message.source.operation.name}: "
                    f"{error}"
                )
                self._record_external_error(message, state, wrapped)
                raise wrapped from error

        result = StepResult(
            step_number=self._step_number,
            status=StepStatus.PROCESSED,
            object_name=message.source.object.name,
            operation=message.source.operation.name,
            source_state=state.name,
            target_state=state.name,
            parameters=_frozen_mapping(message.parameters),
        )
        self._record_trace(result)
        return result

    @staticmethod
    def _external_handler_hints(callback: Callable[..., Any]) -> dict[str, Any]:
        base = callback.func if isinstance(callback, partial) else callback
        target: Any
        if isfunction(base) or ismethod(base):
            target = base
        else:
            target = base.__call__
        try:
            return get_type_hints(target)
        except Exception as error:
            raise ExternalHandlerSignatureError(
                f"Не удалось разрешить аннотации external handler: {error}"
            ) from error

    @classmethod
    def _compile_external_binding(
        cls,
        endpoint: Endpoint,
        operation_signature: OperationSignature,
        callback: Callable[..., Any],
    ) -> _ExternalBinding:
        """Один раз проверяет handler и сохраняет готовый план его вызова."""

        try:
            handler_signature = signature(callback)
        except (TypeError, ValueError) as error:
            raise ExternalHandlerSignatureError(
                f"Не удалось получить сигнатуру external handler: {error}"
            ) from error
        hints = cls._external_handler_hints(callback)
        handler_parameters = tuple(handler_signature.parameters.values())
        unsupported = tuple(
            parameter
            for parameter in handler_parameters
            if parameter.kind
            in (
                Parameter.POSITIONAL_ONLY,
                Parameter.VAR_POSITIONAL,
                Parameter.VAR_KEYWORD,
            )
        )
        if unsupported:
            names = ", ".join(parameter.name for parameter in unsupported)
            raise ExternalHandlerSignatureError(
                f"{endpoint.object.name}.{endpoint.operation.name}: "
                f"неподдерживаемые параметры handler: {names}"
            )
        operation_parameters = operation_signature.parameters
        if len(handler_parameters) != len(operation_parameters):
            raise ExternalHandlerSignatureError(
                f"{endpoint.object.name}.{endpoint.operation.name}: handler принимает "
                f"{len(handler_parameters)} параметров вместо {len(operation_parameters)}"
            )

        positional_names: list[str] = []
        keyword_names: list[str] = []
        for operation_parameter, handler_parameter in zip(
            operation_parameters,
            handler_parameters,
            strict=True,
        ):
            if handler_parameter.kind is not operation_parameter.kind:
                raise ExternalHandlerSignatureError(
                    f"{endpoint.object.name}.{endpoint.operation.name}: вид параметра "
                    f"{handler_parameter.name!r} несовместим с "
                    f"{operation_parameter.name!r}"
                )
            if handler_parameter.kind is Parameter.KEYWORD_ONLY:
                if handler_parameter.name != operation_parameter.name:
                    raise ExternalHandlerSignatureError(
                        f"{endpoint.object.name}.{endpoint.operation.name}: имя "
                        f"keyword-only параметра должно быть "
                        f"{operation_parameter.name!r}"
                    )
                keyword_names.append(operation_parameter.name)
            else:
                positional_names.append(operation_parameter.name)

            handler_type = hints.get(
                handler_parameter.name,
                handler_parameter.annotation,
            )
            operation_type = operation_parameter.annotation
            if (
                handler_type is not _empty
                and operation_type is not _empty
                and handler_type != operation_type
            ):
                raise ExternalHandlerSignatureError(
                    f"{endpoint.object.name}.{endpoint.operation.name}: тип параметра "
                    f"{handler_parameter.name!r} несовместим с "
                    f"{operation_parameter.name!r}"
                )

        return_type = hints.get("return", handler_signature.return_annotation)
        if return_type not in (_empty, None, NoneType):
            raise ExternalHandlerSignatureError(
                f"{endpoint.object.name}.{endpoint.operation.name}: handler должен "
                "возвращать None"
            )
        return _ExternalBinding(
            callback=callback,
            positional_names=tuple(positional_names),
            keyword_names=tuple(keyword_names),
        )

    def _record_ignored(
        self,
        message: _Message,
        state: State,
        reason: str,
    ) -> StepResult:
        result = StepResult(
            step_number=self._step_number,
            status=StepStatus.IGNORED,
            object_name=message.target.name,
            operation=message.operation.name,
            source_state=state.name,
            target_state=state.name,
            parameters=_frozen_mapping(message.parameters),
            error=reason,
        )
        self._record_trace(result)
        return result

    def _record_error(
        self,
        message: _Message,
        state: State,
        error: Exception,
        *,
        transition: str | None = None,
    ) -> None:
        result = StepResult(
            step_number=self._step_number,
            status=StepStatus.ERROR,
            object_name=message.target.name,
            operation=message.operation.name,
            transition=transition,
            source_state=state.name,
            target_state=state.name,
            parameters=_frozen_mapping(message.parameters),
            error=str(error),
        )
        self._record_trace(result)

    def _record_external_error(
        self,
        message: _ExternalDelivery,
        state: State,
        error: Exception,
    ) -> None:
        result = StepResult(
            step_number=self._step_number,
            status=StepStatus.ERROR,
            object_name=message.source.object.name,
            operation=message.source.operation.name,
            source_state=state.name,
            target_state=state.name,
            parameters=_frozen_mapping(message.parameters),
            error=str(error),
        )
        self._record_trace(result)

    def _record_trace(self, result: StepResult) -> None:
        if result.object_name is None or result.operation is None:
            return
        event = TraceEvent(
            step_number=result.step_number,
            status=result.status,
            object_name=result.object_name,
            operation=result.operation,
            transition=result.transition,
            source_state=result.source_state or "",
            target_state=result.target_state or "",
            parameters=result.parameters,
            result=result.result,
            emitted=result.emitted,
            error=result.error,
        )
        with self._trace_lock:
            self._trace.append(event)
        with self._registry_lock:
            listeners = tuple(self._listeners)
        for registration in listeners:
            registration.callback(event)

    @staticmethod
    def _message_info(message: _QueueMessage) -> EmittedMessage:
        if isinstance(message, _ExternalDelivery):
            return EmittedMessage(
                target="<external>",
                operation=message.source.operation.name,
                parameters=_frozen_mapping(message.parameters),
            )
        return EmittedMessage(
            target=message.target.name,
            operation=message.operation.name,
            parameters=_frozen_mapping(message.parameters),
        )

    @staticmethod
    def _translate_parameters(
        source: Operation,
        target: Operation,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Переносит совместимую нагрузку между endpoint с разными именами."""

        source_names = tuple(source.payload_signature.parameters)
        target_names = tuple(target.payload_signature.parameters)
        translated = {
            target_name: parameters[source_name]
            for source_name, target_name in zip(source_names, target_names, strict=True)
        }
        return target.bind_payload(**translated)
