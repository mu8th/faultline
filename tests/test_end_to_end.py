"""Full experiments against the real shop target (no Docker required).

These spawn actual child processes and probe them over loopback HTTP, which is
the same code path the CLI and API use.
"""

from __future__ import annotations

from faultline.engine import ExperimentRunner
from faultline.models import SloSpec, load_experiment
from tests.conftest import REPO_ROOT, make_spec, run_async

EXAMPLES = REPO_ROOT / "examples" / "experiments"


def _run(spec):
    events: list[dict] = []
    report = run_async(ExperimentRunner(spec, events.append, base_dir=EXAMPLES).run())
    return report, events


def test_baseline_experiment_passes():
    spec = load_experiment(EXAMPLES / "baseline.yml")
    report, events = _run(spec)
    assert report.verdict == "pass"
    assert len(report.slo_results) == 2
    assert all(r.passed for r in report.slo_results)
    assert report.windows["baseline"]["samples"] >= 4
    assert report.target_info["port"] is not None
    assert any(e["phase"] == "done" and e.get("verdict") == "pass" for e in events)


def test_kill_restart_experiment_bounded_downtime():
    spec = load_experiment(EXAMPLES / "kill-restart.yml")
    report, events = _run(spec)
    assert report.verdict == "pass"
    # The kill must be visible: some fault-window probes failed.
    assert report.windows["fault"]["failed"] > 0
    # ...but the service came back clean in the recovery window.
    assert report.windows["recovery"]["error_rate"] == 0.0
    assert any("restarted" in e.get("message", "") for e in events)
    assert report.faults[0]["type"] == "process_kill"


def test_tight_slo_fails_loose_passes():
    # A p95 limit of 0.5ms is physically unreachable over loopback HTTP, so the
    # failure path is deterministic; a 5s limit is trivially satisfied.
    report_fail, _ = _run(
        make_spec(slo=[SloSpec(name="impossible", window="baseline", probe=1, p95_latency_ms=0.5)])
    )
    assert report_fail.verdict == "fail"
    assert report_fail.slo_results[0].passed is False

    report_pass, _ = _run(
        make_spec(slo=[SloSpec(name="easy", window="baseline", probe=1, p95_latency_ms=5000.0)])
    )
    assert report_pass.verdict == "pass"
    assert report_pass.slo_results[0].passed is True


def test_report_markdown_renders():
    spec = load_experiment(EXAMPLES / "baseline.yml")
    report, _ = _run(spec)
    md = report.to_markdown()
    assert "# FaultLine report" in md
    assert "VERDICT" not in md  # markdown uses the verdict line, not the CLI banner
    assert "SLO hypotheses" in md
