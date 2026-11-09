"""Построение семантического представления диаграммы из CompiledProgram."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from inspect import _empty
from types import NoneType, UnionType
from typing import Any, get_args, get_origin, get_type_hints

from ciao.domain import AutomatonContext, OperationKind
from ciao.infrastructure import CompiledProgram, OperationParameter, OperationSignature

from .diagram_model import (
    AutomatonView,
    ConnectionView,
    ContextField,
    DiagramDescription,
    OperationView,
    StateView,
    TransitionView,
)


def format_type(annotation: Any) -> str:
    """Возвращает компактное стабильное имя типа для подписи диаграммы."""

    if annotation is _empty:
        return "Any"
    if annotation is Ellipsis:
        return "..."
    if annotation in (None, NoneType):
        return "None"
    if isinstance(annotation, str):
        return annotation
    origin = get_origin(annotation)
    if origin in (UnionType,):
        return " | ".join(format_type(item) for item in get_args(annotation))
    if origin is not None:
        origin_name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
        arguments = ", ".join(format_type(item) for item in get_args(annotation))
        return f"{origin_name}[{arguments}]" if arguments else origin_name
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def _context_fields(context_type: type[AutomatonContext]) -> tuple[ContextField, ...]:
    try:
        resolved = get_type_hints(context_type)
    except Exception:
        resolved = {}

    if is_dataclass(context_type):
        return tuple(
            ContextField(item.name, resolved.get(item.name, item.type))
            for item in fields(context_type)
            if not item.name.startswith("_")
        )

    ordered: dict[str, Any] = {}
    for owner in reversed(context_type.__mro__):
        if not issubclass(owner, AutomatonContext):
            continue
        for name, annotation in owner.__dict__.get("__annotations__", {}).items():
            if not name.startswith("_"):
                # Присваивание существующему ключу сохраняет исходную позицию поля.
                ordered[name] = resolved.get(name, annotation)
    return tuple(ContextField(name, annotation) for name, annotation in ordered.items())


def _parameter_label(parameter: OperationParameter) -> str:
    suffix = "" if not parameter.has_default else f"={parameter.default!r}"
    return f"{parameter.name}: {format_type(parameter.annotation)}{suffix}"


def _visible_parameter_label(parameter: OperationParameter) -> str:
    """Формирует компактный параметр без аннотации типа для рисунка."""

    suffix = "" if not parameter.has_default else f"={parameter.default!r}"
    return f"{parameter.name}{suffix}"


def _operation_signature_label(
    operation: Any,
    signature: OperationSignature,
) -> str:
    """Формирует компактную видимую сигнатуру без типов, self и ctx."""

    parameters = ", ".join(
        _visible_parameter_label(item) for item in signature.parameters
    )
    return f"{operation.name}({parameters})"


def _typed_operation_signature_label(
    operation: Any,
    signature: OperationSignature,
) -> str:
    """Сохраняет полную типизированную сигнатуру в семантических метаданных."""

    parameters = ", ".join(_parameter_label(item) for item in signature.parameters)
    label = f"{operation.name}({parameters})"
    if operation.kind is OperationKind.QUERY:
        label += f" -> {format_type(signature.return_type)}"
    return label


def _operation_label(operation: Any, signature: OperationSignature) -> str:
    return (
        f"{operation.direction.value} {operation.kind.value} "
        f"{_typed_operation_signature_label(operation, signature)}"
    )


def _connection_label(operation: Any, _: OperationSignature) -> str:
    """Оставляет на assembly-связи только компактное имя операции."""

    return operation.name


def build_diagram(compiled: CompiledProgram) -> DiagramDescription:
    """Преобразует уже проверенную модель без повторной компиляции операций."""

    blocks: list[AutomatonView] = []
    endpoint_ids: dict[tuple[int, Any], str] = {}

    for object_index, object_ref in enumerate(compiled.program.objects):
        definition = compiled.definitions[object_ref.automaton]
        block_id = f"object-{object_index}"
        states = tuple(
            StateView(f"{block_id}-state-{index}", state)
            for index, state in enumerate(definition.states)
        )
        operations: list[OperationView] = []
        for operation_index, operation in enumerate(definition.operations):
            endpoint_id = f"{block_id}-operation-{operation_index}"
            endpoint_ids[(id(object_ref), operation)] = endpoint_id
            signature = definition.operation_signatures[operation]
            operations.append(
                OperationView(
                    id=endpoint_id,
                    operation=operation,
                    signature=signature,
                    signature_label=_operation_signature_label(
                        operation,
                        signature,
                    ),
                    label=_operation_label(operation, signature),
                )
            )
        transitions = tuple(
            TransitionView(f"{block_id}-transition-{index}", transition)
            for index, transition in enumerate(definition.transitions)
        )
        blocks.append(
            AutomatonView(
                id=block_id,
                object_ref=object_ref,
                role=definition.role,
                context_fields=_context_fields(definition.context_type),
                states=states,
                operations=tuple(operations),
                transitions=transitions,
            )
        )

    connections: list[ConnectionView] = []
    for index, connection in enumerate(compiled.program.connections):
        required = connection.required
        provided = connection.provided
        required_signature = compiled.definitions[
            required.object.automaton
        ].operation_signatures[required.operation]
        connection_label = _connection_label(required.operation, required_signature)
        connections.append(
            ConnectionView(
                id=f"connection-{index}",
                required_endpoint_id=endpoint_ids[
                    (id(required.object), required.operation)
                ],
                provided_endpoint_id=endpoint_ids[
                    (id(provided.object), provided.operation)
                ],
                # Направления видны по концам связи, поэтому в подписи остаётся
                # только пользовательская сигнатура без provided/required.
                label=connection_label,
            )
        )

    return DiagramDescription(tuple(blocks), tuple(connections))


__all__ = ["build_diagram", "format_type"]
