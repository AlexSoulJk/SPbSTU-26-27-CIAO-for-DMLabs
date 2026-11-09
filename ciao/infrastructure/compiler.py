"""Проверка и компиляция декларативной модели в исполняемое описание."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from inspect import Parameter, Signature, _empty, signature
from types import MappingProxyType, NoneType
from typing import Any, Mapping, get_args, get_type_hints

from ciao.domain.connections import Endpoint
from ciao.domain.emission import Emit, Emits
from ciao.domain.model import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    AutomatonRole,
    ControllerAutomaton,
    Program,
    State,
    ViewAutomaton,
)
from ciao.domain.operations import Operation, OperationDirection, OperationKind
from ciao.domain.transition import Action, Behavior, Guard, Transition

from .errors import MissingOtherwiseWarning, ModelValidationError


@dataclass(frozen=True)
class OperationParameter:
    """Разрешённый параметр полезной нагрузки операции."""

    name: str
    kind: Any
    annotation: Any
    has_default: bool
    default: Any = None


@dataclass(frozen=True)
class OperationSignature:
    """Проверенная сигнатура операции без служебных ``self`` и ``ctx``."""

    parameters: tuple[OperationParameter, ...]
    return_type: Any


@dataclass(frozen=True)
class ActionInjectionPlan:
    """Проверенный план внедрения capability в один Action."""

    parameter_name: str
    capability_type: type[Emit] | type[Emits]
    commands: tuple[Operation, ...]


@dataclass(frozen=True)
class AutomatonDefinition:
    """Проверенное описание одного автоматного класса."""

    automaton_type: type[Automaton[Any]]
    context_type: type[AutomatonContext]
    role: AutomatonRole
    states: tuple[State, ...]
    initial_state: State
    operations: tuple[Operation, ...]
    operation_signatures: Mapping[Operation, OperationSignature]
    guards: tuple[Guard, ...]
    actions: tuple[Action, ...]
    action_injections: Mapping[Action, ActionInjectionPlan | None]
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


def _type_hints(
    function: Any,
    owner: type[Any],
    *,
    include_extras: bool = False,
) -> dict[str, Any]:
    try:
        return get_type_hints(
            function,
            globalns=function.__globals__,
            localns=dict(vars(owner)),
            include_extras=include_extras,
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


def _compile_operation_signature(
    operation: Operation,
    context_type: type[AutomatonContext],
) -> OperationSignature:
    """Один раз разрешает аннотации операции для всех последующих потребителей."""

    owner = operation.owner
    if owner is None:
        raise ModelValidationError(f"Операция {operation.name} не привязана к классу")
    hints = _type_hints(operation.function, owner)
    parameters = _function_parameters(operation.function)
    if parameters and parameters[0].name == "ctx":
        if hints.get("ctx", _empty) is not context_type:
            raise ModelValidationError(
                f"{operation.qualified_name} должен использовать "
                f"контекст {context_type.__name__}"
            )

    result: list[OperationParameter] = []
    for parameter in operation.payload_signature.parameters.values():
        if parameter.kind is Parameter.POSITIONAL_ONLY:
            raise ModelValidationError(
                f"{operation.qualified_name}: positional-only параметры не поддерживаются"
            )
        result.append(
            OperationParameter(
                name=parameter.name,
                kind=parameter.kind,
                annotation=hints.get(parameter.name, parameter.annotation),
                has_default=parameter.default is not _empty,
                default=None if parameter.default is _empty else parameter.default,
            )
        )
    return OperationSignature(
        parameters=tuple(result),
        return_type=hints.get("return", operation.return_annotation),
    )


def _validate_handler_for_event(
    behavior: Behavior,
    event: Operation,
    event_signature: OperationSignature,
    *,
    excluded_parameters: frozenset[str] = frozenset(),
) -> None:
    owner = behavior.owner
    if owner is None:
        raise ModelValidationError(f"Обработчик {behavior.name} не привязан к классу")
    hints = _type_hints(behavior.function, owner)
    parameters = _function_parameters(behavior.function)[1:]
    event_parameters = {
        parameter.name: parameter.annotation
        for parameter in event_signature.parameters
    }
    for parameter in parameters:
        if parameter.name in excluded_parameters:
            continue
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


def _is_capability_annotation(annotation: Any) -> bool:
    """Находит также запрещённые Optional/Annotated/подтипы capability."""

    if annotation in (Emit, Emits):
        return True
    if isinstance(annotation, type) and issubclass(annotation, (Emit, Emits)):
        return True
    return any(_is_capability_annotation(item) for item in get_args(annotation))


def _compile_action_injection(
    action_item: Action,
    automaton_type: type[Automaton[Any]],
    operations: tuple[Operation, ...],
) -> ActionInjectionPlan | None:
    if action_item.emit is not None and action_item.emits is not None:
        raise ModelValidationError(
            f"{action_item.qualified_name}: emit и emits взаимоисключаются"
        )
    if action_item.emits is not None:
        if not isinstance(action_item.emits, tuple):
            raise ModelValidationError(
                f"{action_item.qualified_name}: emits должен быть кортежем"
            )
        if not action_item.emits:
            raise ModelValidationError(
                f"{action_item.qualified_name}: emits должен быть непустым"
            )

    commands = action_item.outgoing_commands
    seen: set[Operation] = set()
    for command in commands:
        if not isinstance(command, Operation):
            raise ModelValidationError(
                f"{action_item.qualified_name}: emit/emits должен ссылаться "
                "на @required_command"
            )
        if command in seen:
            raise ModelValidationError(
                f"{action_item.qualified_name}: команда {command.qualified_name} "
                "повторена в emits"
            )
        seen.add(command)
        if command not in operations:
            raise ModelValidationError(
                f"{action_item.qualified_name}: команда {command.qualified_name} "
                f"не принадлежит {automaton_type.__name__}"
            )
        if not (
            command.kind is OperationKind.COMMAND
            and command.direction is OperationDirection.REQUIRED
        ):
            raise ModelValidationError(
                f"{action_item.qualified_name}: {command.qualified_name} "
                "не является required-командой"
            )

    # include_extras нужен, чтобы Annotated[Emit, ...] не стал
    # незаметно эквивалентен разрешённому точному типу Emit.
    hints = _type_hints(
        action_item.function,
        automaton_type,
        include_extras=True,
    )
    parameters = _function_parameters(action_item.function)[1:]
    related = [
        parameter
        for parameter in parameters
        if _is_capability_annotation(hints.get(parameter.name, _empty))
    ]

    if not commands:
        if related:
            raise ModelValidationError(
                f"{action_item.qualified_name}: capability-параметр разрешён "
                "только для @action(emit=...) и @action(emits=...)"
            )
        return None

    expected_type: type[Emit] | type[Emits]
    expected_type = Emit if action_item.emit is not None else Emits
    exact = [
        parameter
        for parameter in parameters
        if hints.get(parameter.name, _empty) is expected_type
    ]
    if len(exact) != 1:
        raise ModelValidationError(
            f"{action_item.qualified_name}: ожидается ровно один параметр "
            f"с точной аннотацией {expected_type.__name__}"
        )
    if any(parameter not in exact for parameter in related):
        raise ModelValidationError(
            f"{action_item.qualified_name}: допустима только точная "
            f"аннотация {expected_type.__name__}"
        )

    parameter = exact[0]
    if parameter.kind not in (
        Parameter.POSITIONAL_OR_KEYWORD,
        Parameter.KEYWORD_ONLY,
    ):
        raise ModelValidationError(
            f"{action_item.qualified_name}: DI-параметр {parameter.name!r} "
            "должен быть positional-or-keyword или keyword-only"
        )
    if parameter.default is not _empty:
        raise ModelValidationError(
            f"{action_item.qualified_name}: DI-параметр {parameter.name!r} "
            "не должен иметь значение по умолчанию"
        )
    return ActionInjectionPlan(
        parameter_name=parameter.name,
        capability_type=expected_type,
        commands=commands,
    )


def _validate_guard_has_no_capability(
    guard_item: Guard,
    automaton_type: type[Automaton[Any]],
) -> None:
    hints = _type_hints(
        guard_item.function,
        automaton_type,
        include_extras=True,
    )
    parameters = _function_parameters(guard_item.function)[1:]
    if any(
        _is_capability_annotation(hints.get(parameter.name, _empty))
        for parameter in parameters
    ):
        raise ModelValidationError(
            f"{guard_item.qualified_name}: Emit/Emits можно внедрять только в Action"
        )


def _validate_transition_groups(
    automaton_type: type[Automaton[Any]],
    transitions: tuple[Transition, ...],
) -> None:
    """Проверяет взаимоисключающие формы переходов одной группы."""

    groups: dict[tuple[State, Operation], list[Transition]] = {}
    for item in transitions:
        if item.guard is not None and item.otherwise:
            raise ModelValidationError(
                f"{item.qualified_name}: guard нельзя сочетать с otherwise=True"
            )
        groups.setdefault((item.source, item.event), []).append(item)

    for (source, event), group in groups.items():
        fallback = tuple(item for item in group if item.otherwise)
        guarded = tuple(item for item in group if item.guard is not None)
        unconditional = tuple(
            item
            for item in group
            if item.guard is None and not item.otherwise
        )
        group_name = (
            f"{automaton_type.__name__}: состояние {source.name}, "
            f"событие {event.name}"
        )

        if len(fallback) > 1:
            raise ModelValidationError(
                f"{group_name}: разрешён только один переход otherwise"
            )
        if unconditional and len(group) > 1:
            raise ModelValidationError(
                f"{group_name}: безусловный переход нельзя смешивать "
                "с альтернативами; используйте otherwise=True"
            )
        if fallback and not guarded:
            raise ModelValidationError(
                f"{group_name}: otherwise требует хотя бы один переход с Guard"
            )
        if guarded and not fallback:
            warnings.warn(
                f"{group_name}: условная группа не содержит otherwise; "
                "если все Guard ложны, применимый переход отсутствует",
                MissingOtherwiseWarning,
                stacklevel=4,
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

    is_controller = issubclass(automaton_type, ControllerAutomaton)
    is_view = issubclass(automaton_type, ViewAutomaton)
    if is_controller and is_view:
        raise ModelValidationError(
            f"{automaton_type.__name__} не может одновременно иметь роли Controller и View"
        )
    if is_controller:
        expected_role = AutomatonRole.CONTROLLER
    elif is_view:
        expected_role = AutomatonRole.VIEW
    else:
        expected_role = AutomatonRole.BASE
    if getattr(automaton_type, "role", None) is not expected_role:
        raise ModelValidationError(
            f"{automaton_type.__name__}: роль задаётся выбором базового класса, "
            "а не переопределением атрибута role"
        )

    initial_states = tuple(state for state in states if state.initial)
    if len(initial_states) != 1:
        raise ModelValidationError(
            f"{automaton_type.__name__} должен иметь ровно одно начальное состояние"
        )

    operation_signatures: dict[Operation, OperationSignature] = {}
    for operation in operations:
        operation_signature = _compile_operation_signature(operation, context_type)
        operation_signatures[operation] = operation_signature
        return_type = operation_signature.return_type
        if operation.kind is OperationKind.COMMAND and return_type not in (_empty, None, NoneType):
            raise ModelValidationError(
                f"Команда {operation.qualified_name} должна возвращать None"
            )
        if operation.external and operation.direction is not OperationDirection.PROVIDED:
            raise ModelValidationError(
                f"{operation.qualified_name}: external разрешён только для provided-операций"
            )

    for item in guards:
        _validate_behavior(item, automaton_type, context_type, bool)
        _validate_guard_has_no_capability(item, automaton_type)
    action_injections: dict[Action, ActionInjectionPlan | None] = {}
    for item in actions:
        _validate_behavior(item, automaton_type, context_type, NoneType)
        action_injections[item] = _compile_action_injection(
            item,
            automaton_type,
            operations,
        )

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
            _validate_handler_for_event(
                item.guard,
                item.event,
                operation_signatures[item.event],
            )
        for action_item in item.actions:
            if action_item not in actions:
                raise ModelValidationError(
                    f"{item.qualified_name}: Action должен принадлежать автомату"
                )
            _validate_handler_for_event(
                action_item,
                item.event,
                operation_signatures[item.event],
                excluded_parameters=(
                    frozenset(
                        (action_injections[action_item].parameter_name,)
                    )
                    if action_injections[action_item] is not None
                    else frozenset()
                ),
            )

    _validate_transition_groups(automaton_type, transitions)

    return AutomatonDefinition(
        automaton_type=automaton_type,
        context_type=context_type,
        role=expected_role,
        states=states,
        initial_state=initial_states[0],
        operations=operations,
        operation_signatures=MappingProxyType(operation_signatures),
        guards=guards,
        actions=actions,
        action_injections=MappingProxyType(action_injections),
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


def _validate_signature(
    required: Operation,
    required_signature: OperationSignature,
    provided: Operation,
    provided_signature: OperationSignature,
) -> None:
    required_parameters = required_signature.parameters
    provided_parameters = provided_signature.parameters
    if len(required_parameters) != len(provided_parameters):
        raise ModelValidationError(
            f"Несовместимые сигнатуры {required.qualified_name} и {provided.qualified_name}"
        )
    for required_parameter, provided_parameter in zip(
        required_parameters,
        provided_parameters,
        strict=True,
    ):
        if required_parameter.kind != provided_parameter.kind:
            raise ModelValidationError(
                f"Несовместимые виды параметров {required.qualified_name} "
                f"и {provided.qualified_name}"
            )
        if (
            required_parameter.annotation is not _empty
            and provided_parameter.annotation is not _empty
            and required_parameter.annotation != provided_parameter.annotation
        ):
            raise ModelValidationError(
                f"Несовместимые типы параметров {required.qualified_name} "
                f"и {provided.qualified_name}"
            )
    if required.kind is OperationKind.QUERY:
        required_return = required_signature.return_type
        provided_return = provided_signature.return_type
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
        definition = definitions.get(object_ref.automaton)
        if definition is None:
            definition = _compile_automaton(object_ref.automaton)
            definitions[object_ref.automaton] = definition
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
        required_definition = definitions[required.object.automaton]
        provided_definition = definitions[provided.object.automaton]
        _validate_signature(
            required.operation,
            required_definition.operation_signatures[required.operation],
            provided.operation,
            provided_definition.operation_signatures[provided.operation],
        )
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
