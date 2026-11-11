"""Запуск benchmark двух стратегий draw.io на штатных примерах CIAO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from ciao.domain import Program
from ciao.infrastructure import compile_program
from ciao.visualization.drawio.benchmark import (
    benchmark_layouts,
    benchmark_layouts_with_elk,
)
from ciao.visualization.drawio.builder import build_diagram
from ciao.visualization.drawio.writer import serialize_drawio
from examples.array_sum.program import build_sample as build_array_sum
from examples.calculator.program import build_calculator_program
from examples.query_di import build_sample as build_query_di


def _programs() -> dict[str, Callable[[], Program]]:
    return {
        "array_sum": lambda: build_array_sum().program,
        "calculator": lambda: build_calculator_program()[0],
        "query_di": build_query_di,
    }


def _print_table(results: dict[str, dict[str, object]]) -> None:
    header = (
        "example       strategy     page       penalty  obj-overlap  edge-node  "
        "edge-overlap  crossings  label-x  label-dist"
    )
    print(header)
    print("-" * len(header))
    for example, result in results.items():
        strategies = ["baseline", "multiphase"]
        if "elk" in result:
            strategies.append("elk")
        for strategy in strategies:
            item = result[strategy]
            assert isinstance(item, dict)
            metrics = item["metrics"]
            assert isinstance(metrics, dict)
            print(
                f"{example:<13} {strategy:<12} "
                f"{item['width']}x{item['height']:<7} "
                f"{metrics['quality_penalty']:>7.2f}  "
                f"{metrics['object_overlap_area_ratio']:>11.2%}  "
                f"{metrics['edge_object_overlap_ratio']:>9.2%}  "
                f"{metrics['edge_overlap_ratio']:>12.2%}  "
                f"{metrics['edge_crossings']:>9}  "
                f"{metrics['label_edge_intersections']:>7}  "
                f"{metrics['mean_label_distance']:>10.1f}"
            )
        print(
            f"{'':<13} improvement: "
            f"{result['quality_improvement_percent']:+.2f}%"
        )
        if "elk_quality_improvement_percent" in result:
            print(
                f"{'':<13} ELK improvement: "
                f"{result['elk_quality_improvement_percent']:+.2f}%"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сравнить baseline и multiphase draw.io layout.",
    )
    parser.add_argument(
        "examples",
        nargs="*",
        help="Примеры для запуска; по умолчанию запускаются все.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результат в JSON вместо таблицы.",
    )
    parser.add_argument(
        "--elk",
        action="store_true",
        help="Дополнительно запустить ELK Layered; требуется `npm install`.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Дополнительно сохранить обе .drawio-диаграммы для каждого примера.",
    )
    arguments = parser.parse_args()
    if arguments.output_dir is not None:
        arguments.output_dir.mkdir(parents=True, exist_ok=True)

    factories = _programs()
    results: dict[str, dict[str, object]] = {}
    selected_examples = arguments.examples or tuple(factories)
    for name in selected_examples:
        if name not in factories:
            parser.error(
                f"неизвестный пример {name!r}; доступны: {', '.join(factories)}"
            )
        description = build_diagram(compile_program(factories[name]()))
        if arguments.elk:
            benchmark, baseline_page, multiphase_page, elk_page = (
                benchmark_layouts_with_elk(description)
            )
        else:
            benchmark, baseline_page, multiphase_page = benchmark_layouts(
                description
            )
            elk_page = None
        results[name] = benchmark.as_dict()
        if arguments.output_dir is not None:
            pages = [
                ("baseline", baseline_page),
                ("multiphase", multiphase_page),
            ]
            if elk_page is not None:
                pages.append(("elk", elk_page))
            for strategy, page in pages:
                output = arguments.output_dir / f"{name}-{strategy}.drawio"
                output.write_bytes(serialize_drawio(page))

    if arguments.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print_table(results)


if __name__ == "__main__":
    main()
