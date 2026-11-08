"""Проверка и компиляция декларативной модели в исполняемое описание."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, Signature, _empty, signature
from types import MappingProxyType, NoneType
from typing import Any, Mapping, get_type_hints

from ciao.domain.connections import Endpoint
from ciao.domain.model import Automaton, AutomatonContext, AutomatonObject, Program, State
from ciao.domain.operations import Operation, OperationDirection, OperationKind
from ciao.domain.transition import Action, Behavior, Guard, Transition

from .errors import ModelValidationError


@dataclass(frozen=True)
class AutomatonDefinition:
    """Проверенное описание одного автоматного класса."""

    automaton_type: type[Automaton[Any]]
    context_type: type[AutomatonContext]
    states: tuple[State, ...]
    initial_state: State
    operations: tuple[Operation, ...]
    guards: tuple[Guard, ...]
    actions: tuple[Action, ...]
    transitions: tuple[Transition, ...]


@dataclass(frozen=True)
class CompiledProgram:
    """Проверенная модель с готовой таблицей маршрутизации."""

    program: Program
    definitions: Mapping[type[Automaton[Any]], AutomatonDefinition]
    routes: Mapping[Endpoint, Endpoint]


def _declared_members(owner: type[Any], member_type: type[Any]) -> tuple[Any, ...]:
    members: list[Any] = []
    for cls in reversed(owner.__mro__):
        if not issubclass(cls, Automaton):
            continue
        members.extend(value for value in vars(cls).values() if isinstance(value, member_type))
    return tuple(dict.fromkeys(members))


def _type_hints(function: Any, owner: type[Any]) -> dict[str, Any]:
    try:
        return get_type_hints(
            function,
            globalns=function.__globals__,
            localns=dict(vars(owner)),
        )
    except Exception as error:
        raise ModelValidationError(
            f"Не удалось разрешить аннотации {owner.__name__}.{function.__name__}: {error}"
        ) from error


def _function_parameters(function: Any) -> list[Parameter]:
    parameters = list(signature(function).parameters.values())
    if not parameters or parameters[0].name != "self":
        raise ModelValidationError(
            f"Метод {function.__qualname__} должен первым параметром принимать self"
        )
    return parameters[1:]


def _validate_behavior(
    behavior: Behavior,
    definition_owner: type[Automaton[Any]],
    context_type: type[AutomatonContext],
    expected_return: type[Any],
) -> None:
    parameters = _function_parameters(behavior.function)
    if not parameters or parameters[0].name != "ctx":
        raise ModelValidationError(
            f"{behavior.qualified_name} должен принимать ctx сразу после self"
        )
    hints = _type_hints(behavior.function, definition_owner)
    context_annotation = hints.get("ctx", _empty)
    if context_annotation is not context_type:
        raise ModelValidationError(
            f"{behavior.qualified_name} ожидает контекст {context_annotation!r}, "
            f"но автомат использует {context_type.__name__}"
        )
    actual_return = hints.get("return", _empty)
    if actual_return is not expected_return:
        expected_name = "bool" if expected_return is bool else "None"
        raise ModelValidationError(
            f"{behavior.qualified_name} должен иметь возвращаемый тип {expected_name}"
        )
    for parameter in parameters[1:]:
        if parameter.kind is Parameter.POSITIONAL_ONLY:
            raise ModelValidationError(
                f"{behavior.qualified_name}: позиционные-only параметры не поддерживаются"
            )
        if hints.get(parameter.name, _empty) is _empty:
            raise ModelValidationError(
                f"{behavior.qualified_name}: параметр {parameter.name!r} должен иметь аннотацию"
            )


def _resolved_payload(operation: Operation) -> tuple[tuple[Parameter, Any], ...]:
    owner = operation.owner
    if owner is None:
        raise ModelValidationError(f"Операция {operation.name} не привязана к классу")
    hints = _type_hints(operation.function, owner)
    result: list[tuple[Parameter, Any]] = []
    for parameter in operation.payload_signature.parameters.values():
        if parameter.kind is Parameter.POSITIONAL_ONLY:
            raise ModelValidationError(
                f"{operation.qualified_name}: positional-only параметры не поддерживаются"
            )
        result.append((parameter, hints.get(parameter.name, parameter.annotation)))
    return tuple(result)


def _resolved_return(operation: Operation) -> Any:
    owner = operation.owner
    if owner is None:
        return operation.return_annotation
    return _type_hints(operation.function, owner).get("return", operation.return_annotation)


def _validate_handler_for_event(
    behavior: Behavior,
    event: Operation,
) -> None:
    owner = behavior.owner
    if owner is None:
        raise ModelValidationError(f"Обработчик {behavior.name} не привязан к классу")
    hints = _type_hints(behavior.function, owner)
    parameters = _function_parameters(behavior.function)[1:]
    event_parameters = {parameter.name: annotation for parameter, annotation in _resolved_payload(event)}
    for parameter in parameters:
        if parameter.name not in event_parameters:
            raise ModelValidationError(
                f"{behavior.qualified_name}: параметр {parameter.name!r} отсутствует "
                f"в событии {event.qualified_name}"
            )
        handler_type = hints.get(parameter.name, parameter.annotation)
        event_type = event_parameters[parameter.name]
        if handler_type is not _empty and event_type is not _empty and handler_type != event_type:
            raise ModelValidationError(
                f"{behavior.qualified_name}: тип параметра {parameter.name!r} "
                f"несовместим с {event.qualified_name}"
            )


def _compile_automaton(automaton_type: type[Automaton[Any]]) -> AutomatonDefinition:
    context_type = getattr(automaton_type, "_context_type", None)
    if not isinstance(context_type, type) or not issubclass(context_type, AutomatonContext):
        raise ModelValidationError(
            f"{automaton_type.__name__} должен наследоваться от Automaton[ContextT]"
        )

    states = _declared_members(automaton_type, State)
    operations = _declared_members(automaton_type, Operation)
    guards = _declared_members(automaton_type, Guard)
    actions = _declared_members(automaton_type, Action)
    transitions = _declared_members(automaton_type, Transition)

    initial_states = tuple(state for state in states if state.initial)
    if len(initial_states) != 1:
        raise ModelValidationError(
            f"{automaton_type.__name__} должен иметь ровно одно начальное состояние"
        )

    for operation in operations:
        parameters = _function_parameters(operation.function)
        if parameters and parameters[0].name == "ctx":
            hints = _type_hints(operation.function, automaton_type)
            if hints.get("ctx", _empty) is not context_type:
                raise ModelValidationError(
                    f"{operation.qualified_name} должен использовать "
                    f"контекст {context_type.__name__}"
                )
        _resolved_payload(operation)
        return_type = _resolved_return(operation)
        if operation.kind is OperationKind.COMMAND and return_type not in (_empty, None, NoneType):
            raise ModelValidationError(
                f"Команда {operation.qualified_name} должна возвращать None"
            )

    for item in guards:
        _validate_behavior(item, automaton_type, context_type, bool)
    for item in actions:
        _validate_behavior(item, automaton_type, context_type, NoneType)

    for item in transitions:
        if item.owner is not automaton_type:
            continue
        if item.source not in states or item.target not in states:
            raise ModelValidationError(
                f"{item.qualified_name}: состояния должны принадлежать автомату"
            )
        if item.event not in operations:
            raise ModelValidationError(
                f"{item.qualified_name}: событие должно принадлежать автомату"
            )
        if not (
            item.event.kind is OperationKind.COMMAND
            and item.event.direction is OperationDirection.PROVIDED
        ):
            raise ModelValidationError(
                f"{item.qualified_name}: событием может быть только provided-команда"
            )
        if item.guard is not None:
            if item.guard not in guards:
                raise ModelValidationError(
                    f"{item.qualified_name}: Guard должен принадлежать автомату"
                )
            _validate_handler_for_event(item.guard, item.event)
        for action_item in item.actions:
            if action_item not in actions:
                raise ModelValidationError(
                    f"{item.qualified_name}: Action должен принадлежать автомату"
                )
            _validate_handler_for_event(action_item, item.event)

    return AutomatonDefinition(
        automaton_type=automaton_type,
        context_type=context_type,
        states=states,
        initial_state=initial_states[0],
        operations=operations,
        guards=guards,
        actions=actions,
        transitions=transitions,
    )


def _validate_endpoint(endpoint: Endpoint, program: Program) -> None:
    if endpoint.object not in program.objects:
        raise ModelValidationError("Endpoint ссылается на объект вне Program")
    owner = endpoint.operation.owner
    if owner is None or not issubclass(endpoint.object.automaton, owner):
        raise ModelValidationError(
            f"Операция {endpoint.operation.qualified_name} не принадлежит "
            f"объекту {endpoint.object.name}"
        )


def _validate_signature(required: Operation, provided: Operation) -> None:
    required_parameters = _resolved_payload(required)
    provided_parameters = _resolved_payload(provided)
    if len(required_parameters) != len(provided_parameters):
        raise ModelValidationError(
            f"Несовместимые сигнатуры {required.qualified_name} и {provided.qualified_name}"
        )
    for (required_parameter, required_type), (provided_parameter, provided_type) in zip(
        required_parameters,
        provided_parameters,
        strict=True,
    ):
        if required_parameter.kind != provided_parameter.kind:
            raise ModelValidationError(
                f"Несовместимые виды параметров {required.qualified_name} "
                f"и {provided.qualified_name}"
            )
        if required_type is not _empty and provided_type is not _empty and required_type != provided_type:
            raise ModelValidationError(
                f"Несовместимые типы параметров {required.qualified_name} "
                f"и {provided.qualified_name}"
            )
    if required.kind is OperationKind.QUERY:
        required_return = _resolved_return(required)
        provided_return = _resolved_return(provided)
        if (
            required_return is not _empty
            and provided_return is not _empty
            and required_return != provided_return
        ):
            raise ModelValidationError(
                f"Несовместимые типы результата {required.qualified_name} "
                f"и {provided.qualified_name}"
            )


def compile_program(program: Program) -> CompiledProgram:
    """Проверяет программу и создаёт таблицу однозначной маршрутизации."""

    if not program.objects:
        raise ModelValidationError("Program должен содержать хотя бы один объект")
    names = [object_ref.name for object_ref in program.objects]
    if len(names) != len(set(names)):
        raise ModelValidationError("Имена AutomatonObject должны быть уникальны")

    definitions: dict[type[Automaton[Any]], AutomatonDefinition] = {}
    for object_ref in program.objects:
        definition = definitions.setdefault(
            object_ref.automaton,
            _compile_automaton(object_ref.automaton),
        )
        if type(object_ref.initial_context) is not definition.context_type:
            raise ModelValidationError(
                f"Объект {object_ref.name} ожидает {definition.context_type.__name__}, "
                f"получен {type(object_ref.initial_context).__name__}"
            )

    routes: dict[Endpoint, Endpoint] = {}
    for connection in program.connections:
        required = connection.required
        provided = connection.provided
        _validate_endpoint(required, program)
        _validate_endpoint(provided, program)
        if required.operation.direction is not OperationDirection.REQUIRED:
            raise ModelValidationError("Левая сторона Connection должна быть required")
        if provided.operation.direction is not OperationDirection.PROVIDED:
            raise ModelValidationError("Правая сторона Connection должна быть provided")
        if required.operation.kind is not provided.operation.kind:
            raise ModelValidationError("Connection связывает разные виды операций")
        if required in routes:
            raise ModelValidationError(
                f"Для {required.object.name}.{required.operation.name} задано несколько связей"
            )
        _validate_signature(required.operation, provided.operation)
        routes[required] = provided

    for object_ref in program.objects:
        definition = definitions[object_ref.automaton]
        for operation in definition.operations:
            if operation.direction is OperationDirection.REQUIRED:
                endpoint = Endpoint(object_ref, operation)
                if endpoint not in routes:
                    raise ModelValidationError(
                        f"Для required-операции {object_ref.name}.{operation.name} "
                        "не задан Connection"
                    )

    return CompiledProgram(
        program=program,
        definitions=MappingProxyType(definitions),
        routes=MappingProxyType(routes),
    )
