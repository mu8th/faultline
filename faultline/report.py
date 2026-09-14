"""Report models and rendering (JSON dict + Markdown)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .telemetry.slo import SloResult


@dataclass
class Report:
    experiment: str
    description: str
    started_at: str
    duration_s: float
    verdict: str  # "pass" | "fail"
    target_info: dict[str, Any]
    windows: dict[str, dict[str, Any]]
    faults: list[dict[str, Any]] = field(default_factory=list)
    slo_results: list[SloResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "description": self.description,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
            "verdict": self.verdict,
            "target": self.target_info,
            "windows": self.windows,
            "faults": self.faults,
            "slo_results": [r.to_dict() for r in self.slo_results],
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# FaultLine report -- {self.experiment}")
        lines.append("")
        if self.description:
            lines.append(f"> {self.description}")
            lines.append("")
        mark = "PASS" if self.verdict == "pass" else "FAIL"
        lines.append(
            f"**Verdict: {mark}** -- started {self.started_at}, "
            f"duration {self.duration_s:.1f}s, target "
            f"{self.target_info.get('kind')} (port {self.target_info.get('port')})"
        )
        lines.append("")
        lines.append("## Windows")
        lines.append("")
        lines.append("| window | samples | ok | failed | p50 ms | p95 ms | p99 ms | error rate |")
        lines.append("|--------|---------|----|--------|--------|--------|--------|------------|")
        for name in ("baseline", "fault", "recovery"):
            m = self.windows.get(name)
            if not m:
                continue
            lines.append(
                f"| {name} | {m['samples']} | {m['ok']} | {m['failed']} "
                f"| {m['p50_ms']} | {m['p95_ms']} | {m['p99_ms']} | {m['error_rate']} |"
            )
        if self.faults:
            lines.append("")
            lines.append("## Faults")
            lines.append("")
            lines.append("| fault | duration s | p95 ms | error rate | params |")
            lines.append("|-------|------------|--------|------------|--------|")
            for f in self.faults:
                lines.append(
                    f"| {f['type']} | {f['duration_s']:.0f} | {f.get('p95_ms')} "
                    f"| {f.get('error_rate')} | {f.get('params')} |"
                )
        if self.slo_results:
            lines.append("")
            lines.append("## SLO hypotheses")
            lines.append("")
            lines.append("| hypothesis | window | verdict | evidence |")
            lines.append("|------------|--------|---------|----------|")
            for r in self.slo_results:
                verdict = "PASS" if r.passed else "FAIL"
                checks = "; ".join(
                    f"{c['check']}={c['actual']} (limit {c['limit']})" for c in r.checks
                )
                lines.append(f"| {r.name} | {r.window} | {verdict} | {checks} |")
        lines.append("")
        return "\n".join(lines)
