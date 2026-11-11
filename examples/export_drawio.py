"""Экспортирует учебную программу суммы массива в редактируемый draw.io."""

from __future__ import annotations

from pathlib import Path

from ciao.visualization.drawio import export_program_drawio
from array_sum.program import build_sample as build_mock_sample
from query_di import build_sample as build_query_sample
from calculator.program import build_calculator_program as build_calculator_sample


def main() -> None:
    output_directory = (
        Path(__file__).with_name("schemas") / "generated_drawio"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs = [
        export_program_drawio(
            build_mock_sample().program,
            output_directory / "sum_program.drawio",
        ),
        export_program_drawio(
            build_query_sample(),
            output_directory / "query_program.drawio",
        ),
        export_program_drawio(
            build_calculator_sample()[0],
            output_directory / "calculator_program.drawio",
        ),
    ]
    for output in outputs:
        print(f"Диаграмма сохранена: {output}")


if __name__ == "__main__":
    main()
