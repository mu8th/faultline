"""Command-line interface.

Usage:
    python -m faultline run examples/experiments/cpu-pressure.yml [--json OUT] [--markdown OUT]
    python -m faultline faults
    python -m faultline experiments [DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__  # noqa: F401 -- registers built-ins
from .engine import run_experiment
from .models import ExperimentLoadError, load_experiment
from .registry import available as faults_available
from .registry import get as fault_class

_USE_COLOR = sys.stdout.isatty() and sys.stderr.isatty()

_PHASE_COLORS = {
    "target": "\033[35m",
    "baseline": "\033[36m",
    "fault": "\033[31m",
    "recovery": "\033[33m",
    "evaluate": "\033[34m",
    "done": "\033[32m",
    "error": "\033[91m",
}
_RESET = "\033[0m"


def _paint(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def _print_event(event: dict) -> None:
    phase = event.get("phase", "")
    label = phase.upper().ljust(8)
    line = f"[{label}] {event.get('message', '')}"
    print(_paint(line, _PHASE_COLORS.get(phase, "")), flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    try:
        spec = load_experiment(spec_path)
    except ExperimentLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    events: list[dict] = []

    def on_event(event: dict) -> None:
        events.append(event)
        _print_event(event)

    try:
        report = run_experiment(spec, on_event, base_dir=spec_path.parent)
    except Exception as exc:  # noqa: BLE001 - CLI boundary; any failure is a user-facing error
        print(f"error: experiment failed: {exc}", file=sys.stderr)
        return 1

    print()
    for r in report.slo_results:
        verdict = "PASS" if r.passed else "FAIL"
        checks = "; ".join(f"{c['check']}={c['actual']} (limit {c['limit']})" for c in r.checks)
        line = f"SLO  {r.name} [{r.window}]: {verdict}  -- {checks}"
        print(_paint(line, "\033[32m" if r.passed else "\033[31m"), flush=True)
    print()
    print(
        _paint(
            f"VERDICT: {report.verdict.upper()}  ({report.duration_s:.1f}s)",
            "\033[32m" if report.verdict == "pass" else "\033[31m",
        )
    )

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"json report written to {args.json}")
    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_markdown(), encoding="utf-8")
        print(f"markdown report written to {args.markdown}")
    return 0


def cmd_faults(_args: argparse.Namespace) -> int:
    for name in faults_available():
        cls = fault_class(name)
        print(f"{name:<16} {cls.description}")
    return 0


def cmd_experiments(args: argparse.Namespace) -> int:
    directory = Path(args.dir) if args.dir else (
        Path(__file__).resolve().parent.parent / "examples" / "experiments"
    )
    if not directory.is_dir():
        print(f"error: no experiments directory at {directory}", file=sys.stderr)
        return 2
    for path in sorted(directory.glob("*.yml")):
        try:
            spec = load_experiment(path)
        except ExperimentLoadError as exc:
            print(f"{path.name:<24} INVALID: {exc}")
            continue
        faults = ", ".join(f.type for f in spec.faults) or "-"
        print(f"{path.stem:<24} faults=[{faults}]  {spec.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faultline", description=__doc__)
    parser.add_argument("--version", action="version", version=f"faultline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run an experiment YAML file")
    p_run.add_argument("spec", help="path to the experiment YAML file")
    p_run.add_argument("--json", help="also write the report as JSON to this path")
    p_run.add_argument("--markdown", help="also write the report as Markdown to this path")
    p_run.set_defaults(func=cmd_run)

    p_faults = sub.add_parser("faults", help="list registered fault types")
    p_faults.set_defaults(func=cmd_faults)

    p_exp = sub.add_parser("experiments", help="list bundled example experiments")
    p_exp.add_argument("dir", nargs="?", help="directory of experiment YAML files")
    p_exp.set_defaults(func=cmd_experiments)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
