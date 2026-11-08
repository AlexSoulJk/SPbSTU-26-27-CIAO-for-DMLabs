"""Экспортирует учебную программу суммы массива в редактируемый draw.io."""

from __future__ import annotations

from pathlib import Path

from ciao.visualization.drawio import export_program_drawio
from test_mock_sample import build_sample


def main() -> None:
    output = export_program_drawio(
        build_sample().program,
        Path(__file__).with_name("sum_program.drawio"),
    )
    print(f"Диаграмма сохранена: {output}")


if __name__ == "__main__":
    main()
