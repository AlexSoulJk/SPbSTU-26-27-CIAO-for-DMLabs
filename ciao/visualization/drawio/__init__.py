"""Публичный односторонний экспорт Program в редактируемый draw.io."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from os import PathLike
from pathlib import Path

from ciao.domain import Program
from ciao.infrastructure import compile_program

from .builder import build_diagram
from .diagram_model import DiagramDescription, DiagramPage
from .layout import layout_diagram
from .writer import serialize_drawio


LayoutBuilder = Callable[[DiagramDescription], DiagramPage]


def export_program_drawio(
    program: Program,
    output: str | PathLike[str],
    *,
    layout_builder: LayoutBuilder = layout_diagram,
) -> Path:
    """Проверяет программу и атомарно экспортирует её в ``.drawio``.

    По умолчанию сохраняется стабильная baseline-компоновка. Экспериментальную
    стратегию, например ELK, вызывающая сторона передаёт явно.
    """

    if not callable(layout_builder):
        raise TypeError("layout_builder должен быть callable")

    output_path = Path(output)
    parent = output_path.parent
    if not parent.exists():
        raise FileNotFoundError(f"Каталог для экспорта не существует: {parent}")

    # Компиляция выполняется ровно один раз; builder получает только проверенную
    # модель и не создаёт параллельную систему валидации деклараций.
    compiled = compile_program(program)
    description = build_diagram(compiled)
    page = layout_builder(description)
    content = serialize_drawio(page)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


__all__ = ["LayoutBuilder", "export_program_drawio"]
