"""Однопоточный FIFO-исполнитель с пошаговой трассировкой."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from inspect import Parameter, signature
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ciao.domain.connections import Endpoint
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
from ciao.domain.transition import Behavior, Transition

from .compiler import (
    ActionInjectionPlan,
    AutomatonDefinition,
    CompiledProgram,
    compile_program,
)
from .errors import (
    ActionExecutionError,
    AmbiguousTransitionError,
    GuardExecutionError,
    InvalidRuntimeCallError,
    NoTransitionError,
    QueryRoutingError,
    RuntimeExecutionError,
    StepLimitExceeded,
)


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
    pending: list[_Message]


class Runtime:
    """Исполняет скомпилированную программу в однопоточном FIFO-порядке."""

    DEFAULT_MAX_STEPS = 10_000

    def __init__(self, program: Program, *, strict: bool = True) -> None:
        self.strict = strict
        self._compiled: CompiledProgram = compile_program(program)
        self._queue: deque[_Message] = deque()
        self._objects: dict[AutomatonObject, _RuntimeObject] = {}
        self._trace: list[TraceEvent] = []
        self._listeners: list[Callable[[TraceEvent], None]] = []
        self._step_number = 0
        self._active_frame: _ExecutionFrame | None = None
        self._query_stack: list[Endpoint] = []

        for object_ref in program.objects:
            definition = self._compiled.definitions[object_ref.automaton]
            context = deepcopy(object_ref.initial_context)
            context._ciao_bind(self, object_ref)
            self._objects[object_ref] = _RuntimeObject(
                definition=definition,
                automaton=object_ref.automaton(),
                context=context,
                state=definition.initial_state,
            )

    @property
    def pending_messages(self) -> int:
        return len(self._queue)

    @property
    def trace(self) -> tuple[TraceEvent, ...]:
        return tuple(self._trace)

    def subscribe(self, listener: Callable[[TraceEvent], None]) -> None:
        """Регистрирует обработчик неизменяемых событий трассы."""

        self._listeners.append(listener)

    def snapshot(self, object_ref: AutomatonObject) -> AutomatonSnapshot[Any]:
        """Возвращает отсоединённую копию контекста и текущее состояние."""

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
        self._queue.append(_Message(target, operation, _message_mapping(parameters)))

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
        target = self._route(frame.object_ref, operation)
        parameters = operation.bind_payload(*args, **kwargs)
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
        source: AutomatonContext | AutomatonObject,
        operation: Operation,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Выполняет required-запрос из контекста или внешний provided-запрос."""

        if isinstance(source, AutomatonContext):
            object_ref = getattr(source, "_ciao_object_ref", None)
            if object_ref is None or object_ref not in self._objects:
                raise QueryRoutingError("Контекст не принадлежит этому Runtime")
            if not (
                operation.kind is OperationKind.QUERY
                and operation.direction is OperationDirection.REQUIRED
            ):
                raise InvalidRuntimeCallError("self.query принимает required-запрос")
            self._ensure_endpoint_owner(object_ref, operation)
            target = self._route(object_ref, operation)
        else:
            object_ref = source
            self._object(object_ref)
            if not (
                operation.kind is OperationKind.QUERY
                and operation.direction is OperationDirection.PROVIDED
            ):
                raise InvalidRuntimeCallError("Runtime.query принимает provided-запрос")
            self._ensure_endpoint_owner(object_ref, operation)
            target = Endpoint(object_ref, operation)

        parameters = operation.bind_payload(*args, **kwargs)
        if isinstance(source, AutomatonContext):
            parameters = self._translate_parameters(
                operation,
                target.operation,
                parameters,
            )
        if target in self._query_stack:
            raise QueryRoutingError(
                f"Обнаружен рекурсивный цикл запросов на {target.operation.qualified_name}"
            )
        self._query_stack.append(target)
        try:
            return self._invoke_query(target, parameters)
        finally:
            self._query_stack.pop()

    def step(self) -> StepResult:
        """Обрабатывает ровно одно сообщение FIFO."""

        if not self._queue:
            return StepResult(step_number=self._step_number, status=StepStatus.EMPTY)

        message = self._queue.popleft()
        runtime_object = self._object(message.target)
        source_state = runtime_object.state
        self._step_number += 1

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
            self._active_frame = _ExecutionFrame(
                message.target,
                runtime_object.context,
                "guard",
                [],
            )
            try:
                accepted = self._invoke_behavior(
                    item.guard,
                    runtime_object,
                    message.parameters,
                )
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
                plan = runtime_object.definition.action_injections[action_item]
                capability = self._create_action_capability(
                    plan,
                    action_item.qualified_name,
                    frame,
                )
                injected = (
                    {plan.parameter_name: capability}
                    if plan is not None and capability is not None
                    else {}
                )
                try:
                    self._invoke_behavior(
                        action_item,
                        runtime_object,
                        message.parameters,
                        injected=injected,
                    )
                finally:
                    if capability is not None:
                        capability._ciao_invalidate()
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
        results: list[StepResult] = []
        while self._queue:
            if max_steps is not None and len(results) >= max_steps:
                if self.strict:
                    raise StepLimitExceeded(
                        f"Достигнут предел run: {max_steps} шагов"
                    )
                return RunResult(RunStatus.LIMIT_REACHED, tuple(results))
            results.append(self.step())
        return RunResult(RunStatus.COMPLETED, tuple(results))

    def _object(self, object_ref: AutomatonObject) -> _RuntimeObject:
        try:
            return self._objects[object_ref]
        except KeyError as error:
            raise InvalidRuntimeCallError("Объект не принадлежит этому Runtime") from error

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

    def _invoke_query(self, endpoint: Endpoint, parameters: Mapping[str, Any]) -> Any:
        runtime_object = self._object(endpoint.object)
        function_parameters = list(
            signature(endpoint.operation.function).parameters.values()
        )
        arguments: list[Any] = [runtime_object.automaton]
        if len(function_parameters) > 1 and function_parameters[1].name == "ctx":
            arguments.append(runtime_object.context)
        return endpoint.operation.function(*arguments, **dict(parameters))

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
        self._trace.append(event)
        for listener in tuple(self._listeners):
            listener(event)

    @staticmethod
    def _message_info(message: _Message) -> EmittedMessage:
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
