"""Сравнение baseline и экспериментальной стратегии компоновки."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .diagram_model import DiagramDescription, DiagramPage
from .layout import layout_diagram
from .layout_elk import layout_diagram_elk
from .layout_multiphase import layout_diagram_multiphase
from .metrics import LayoutMetrics, evaluate_layout


@dataclass(frozen=True)
class StrategyBenchmark:
    """Размер страницы и метрики одной стратегии."""

    strategy: str
    width: int
    height: int
    metrics: LayoutMetrics

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        return result


@dataclass(frozen=True)
class LayoutBenchmark:
    """Парный результат на одном семантическом описании диаграммы."""

    baseline: StrategyBenchmark
    multiphase: StrategyBenchmark
    elk: StrategyBenchmark | None = None

    @property
    def quality_improvement_percent(self) -> float:
        baseline = self.baseline.metrics.quality_penalty
        if baseline == 0:
            return 0.0
        return round(
            100.0 * (baseline - self.multiphase.metrics.quality_penalty) / baseline,
            2,
        )

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "baseline": self.baseline.as_dict(),
            "multiphase": self.multiphase.as_dict(),
            "quality_improvement_percent": self.quality_improvement_percent,
        }
        if self.elk is not None:
            result["elk"] = self.elk.as_dict()
            result["elk_quality_improvement_percent"] = (
                self.elk_quality_improvement_percent
            )
        return result

    @property
    def elk_quality_improvement_percent(self) -> float | None:
        """Возвращает улучшение ELK относительно baseline, если он запускался."""

        if self.elk is None:
            return None
        baseline = self.baseline.metrics.quality_penalty
        if baseline == 0:
            return 0.0
        return round(
            100.0 * (baseline - self.elk.metrics.quality_penalty) / baseline,
            2,
        )


def _strategy_result(strategy: str, page: DiagramPage) -> StrategyBenchmark:
    return StrategyBenchmark(
        strategy=strategy,
        width=page.width,
        height=page.height,
        metrics=evaluate_layout(page),
    )


def benchmark_layouts(
    description: DiagramDescription,
) -> tuple[LayoutBenchmark, DiagramPage, DiagramPage]:
    """Строит обе страницы и оценивает их одной и той же метрикой."""

    baseline_page = layout_diagram(description)
    multiphase_page = layout_diagram_multiphase(description)
    result = LayoutBenchmark(
        baseline=_strategy_result("baseline", baseline_page),
        multiphase=_strategy_result("multiphase", multiphase_page),
    )
    return result, baseline_page, multiphase_page


def benchmark_layouts_with_elk(
    description: DiagramDescription,
    *,
    node_executable: str = "node",
) -> tuple[LayoutBenchmark, DiagramPage, DiagramPage, DiagramPage]:
    """Дополнительно запускает закреплённую экспериментальную ELK-стратегию."""

    result, baseline_page, multiphase_page = benchmark_layouts(description)
    elk_page = layout_diagram_elk(
        description,
        node_executable=node_executable,
    )
    result = replace(result, elk=_strategy_result("elk", elk_page))
    return result, baseline_page, multiphase_page, elk_page


__all__ = [
    "LayoutBenchmark",
    "StrategyBenchmark",
    "benchmark_layouts",
    "benchmark_layouts_with_elk",
]
