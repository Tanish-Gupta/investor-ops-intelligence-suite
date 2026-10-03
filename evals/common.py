"""Result types shared by the eval suites and the report writer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Check:
    id: str
    name: str
    passed: bool
    detail: str = ""
    score: float | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metric:
    name: str
    value: str
    threshold: str
    passed: bool


@dataclass
class SuiteResult:
    key: str
    title: str
    metrics: list[Metric] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.metrics) and all(m.passed for m in self.metrics)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


def ratio(n: int, d: int) -> str:
    return f"{n}/{d}"
