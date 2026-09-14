"""SLO math and hypothesis evaluation.

percentile() uses linear interpolation between closest ranks (the same method as
numpy's default), implemented by hand to keep the dependency footprint small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import SloSpec
from .probe import ProbeSample


def percentile(values: list[float], p: float) -> float | None:
    """Return the p-th percentile of values (0-100); None when values is empty."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (p / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _round(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def summarize(samples: list[ProbeSample]) -> dict[str, Any]:
    """Aggregate a window of samples into the metrics SLO checks compare against."""
    ok = [s for s in samples if s.ok and s.latency_ms is not None]
    latencies = [s.latency_ms for s in ok]
    total = len(samples)
    failed = total - len(ok)
    return {
        "samples": total,
        "ok": len(ok),
        "failed": failed,
        "p50_ms": _round(percentile(latencies, 50)),
        "p95_ms": _round(percentile(latencies, 95)),
        "p99_ms": _round(percentile(latencies, 99)),
        "error_rate": round(failed / total, 4) if total else None,
    }


@dataclass
class SloResult:
    name: str
    window: str
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "window": self.window,
            "passed": self.passed,
            "checks": self.checks,
            "evidence": self.evidence,
        }


def evaluate_slo(spec: SloSpec, samples: list[ProbeSample]) -> SloResult:
    """Grade one SLO hypothesis against the samples of its window.

    A check with no data fails (no successful samples => no p95 to compare;
    zero total samples => nothing was observed at all).
    """
    metrics = summarize(samples)
    checks: list[dict[str, Any]] = []

    if spec.p95_latency_ms is not None:
        actual = metrics["p95_ms"]
        passed = actual is not None and actual <= spec.p95_latency_ms
        checks.append(
            {
                "check": "p95_latency_ms",
                "limit": spec.p95_latency_ms,
                "actual": actual,
                "passed": passed,
            }
        )

    if spec.error_rate_max is not None:
        actual = metrics["error_rate"]
        passed = actual is not None and actual <= spec.error_rate_max
        checks.append(
            {
                "check": "error_rate",
                "limit": spec.error_rate_max,
                "actual": actual,
                "passed": passed,
            }
        )

    return SloResult(spec.name, spec.window, all(c["passed"] for c in checks), checks, metrics)
