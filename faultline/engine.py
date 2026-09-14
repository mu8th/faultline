"""Experiment orchestrator.

Sequence: start target -> baseline window -> (one window per fault) -> recovery
window -> evaluate SLOs -> report. Every step emits events through on_event so
the CLI can print them, the API can stream them over a WebSocket, and tests can
assert on them. The target is always stopped in a finally block, even when a
fault misbehaves.
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .events import make_event
from .models import ExperimentSpec, FaultSpec
from .registry import get as get_fault
from .report import Report
from .targets.base import Target
from .telemetry.probe import ProbeSample, probe_window
from .telemetry.slo import evaluate_slo, summarize

EventSink = Callable[[dict[str, Any]], None]


class ExperimentError(RuntimeError):
    """Raised when an experiment cannot run (bad fault config, target failure...)."""


def find_free_port() -> int:
    """Ask the OS for a free TCP port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def create_target(
    spec: ExperimentSpec, port: int | None, on_event: EventSink
) -> Target:
    if spec.target.kind == "subprocess":
        from .targets.subprocess_target import SubprocessTarget

        return SubprocessTarget(spec.target, port, on_event)
    from .targets.external_target import ExternalTarget

    return ExternalTarget(spec.target, on_event)


def _resolve_probe(spec_probe: Any, port: int | None) -> Any:
    """Return the probe with {port} placeholders replaced (no-op when absent)."""
    if port is None or "{port}" not in spec_probe.url:
        return spec_probe
    return spec_probe.model_copy(update={"url": spec_probe.url.replace("{port}", str(port))})


def _rewrite_proxy_port(url: str, proxy_port: int) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    return urlunsplit(
        (parts.scheme, f"{host}:{proxy_port}", parts.path, parts.query, parts.fragment)
    )


class ExperimentRunner:
    """Runs one validated experiment spec; safe to await directly."""

    def __init__(
        self,
        spec: ExperimentSpec,
        on_event: EventSink | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self._spec = spec
        self._emit = on_event or (lambda e: None)
        self._base_dir = Path(base_dir) if base_dir else Path.cwd()

    def _resolve_cwd(self) -> str | None:
        cwd = self._spec.target.cwd
        if not cwd:
            return None
        p = Path(cwd)
        return str(p if p.is_absolute() else (self._base_dir / p).resolve())

    async def run(self) -> Report:
        started = time.time()
        spec = self._spec
        port = find_free_port() if spec.target.kind == "subprocess" else None

        # Patch a resolved cwd onto the target spec for subprocess spawning.
        target_spec = spec.target.model_copy(deep=True)
        target_spec.cwd = self._resolve_cwd()
        spec = spec.model_copy(update={"target": target_spec})

        target = create_target(spec, port, self._emit)
        try:
            self._emit(make_event("target", f"starting {spec.target.kind} target ..."))
            await target.start()
            self._emit(
                make_event(
                    "target",
                    f"target healthy (port {target.port})",
                    pid=getattr(target, "pid", None),
                )
            )

            probes = [_resolve_probe(p, port) for p in spec.probes]
            windows: dict[str, list[ProbeSample]] = {
                "baseline": [],
                "fault": [],
                "recovery": [],
            }
            fault_windows: list[tuple[FaultSpec, list[ProbeSample]]] = []

            async with httpx.AsyncClient() as client:
                self._emit(
                    make_event("baseline", f"baseline window ({spec.windows.baseline_s:.0f}s)")
                )
                windows["baseline"] = await probe_window(
                    client, probes, spec.windows.baseline_s, "baseline", self._emit
                )

                for fs in spec.faults:
                    plugin_cls = get_fault(fs.type)
                    try:
                        params = plugin_cls.validate_params(fs.params)
                    except Exception as exc:
                        raise ExperimentError(f"fault '{fs.type}' misconfigured: {exc}") from exc
                    plugin = plugin_cls()
                    await plugin.start(target, params)
                    proxy = plugin.proxy_port(target, params)
                    if proxy:
                        fault_probes = [
                            p.model_copy(update={"url": _rewrite_proxy_port(p.url, proxy)})
                            for p in probes
                        ]
                    else:
                        fault_probes = probes
                    self._emit(
                        make_event(
                            "fault",
                            f"injecting {fs.type} for {fs.duration_s:.0f}s",
                            fault=fs.type,
                            proxy_port=proxy,
                        )
                    )
                    samples = await probe_window(
                        client, fault_probes, fs.duration_s, "fault", self._emit
                    )
                    windows["fault"].extend(samples)
                    fault_windows.append((fs, samples))
                    await plugin.stop(target, params)
                    restart_error = getattr(plugin, "restart_error", None)
                    if restart_error is not None:
                        self._emit(make_event("error", f"target restart failed: {restart_error}"))

                self._emit(
                    make_event("recovery", f"recovery window ({spec.windows.recovery_s:.0f}s)")
                )
                windows["recovery"] = await probe_window(
                    client, probes, spec.windows.recovery_s, "recovery", self._emit
                )

            self._emit(make_event("evaluate", "evaluating SLO hypotheses"))
            slo_results = []
            for slo in spec.slo:
                idx = slo.probe if (slo.probe is not None and slo.probe < len(probes)) else 0
                samples = [s for s in windows[slo.window] if s.probe_index == idx]
                result = evaluate_slo(slo, samples)
                slo_results.append(result)
                self._emit(
                    make_event(
                        "evaluate",
                        f"SLO '{result.name}': {'PASS' if result.passed else 'FAIL'}",
                        name=result.name,
                        passed=result.passed,
                    )
                )

            verdict = "fail" if any(not r.passed for r in slo_results) else "pass"
            report = Report(
                experiment=spec.name,
                description=spec.description,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
                duration_s=round(time.time() - started, 2),
                verdict=verdict,
                target_info={
                    "kind": spec.target.kind,
                    "command": spec.target.command,
                    "port": port,
                },
                windows={w: summarize(samples) for w, samples in windows.items()},
                faults=[
                    {
                        "type": fs.type,
                        "duration_s": fs.duration_s,
                        "params": fs.params,
                        **summarize(samples),
                    }
                    for fs, samples in fault_windows
                ],
                slo_results=slo_results,
            )
            self._emit(make_event("done", f"verdict: {verdict.upper()}", verdict=verdict))
            return report
        finally:
            await target.stop()


def run_experiment(
    spec: ExperimentSpec,
    on_event: EventSink | None = None,
    base_dir: str | Path | None = None,
) -> Report:
    """Synchronous entry point (used by the CLI and tests)."""
    return asyncio.run(ExperimentRunner(spec, on_event, base_dir).run())
