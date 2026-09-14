"""Probe loop: hit every probe endpoint on its interval and record samples.

A sample is "ok" when the HTTP exchange succeeds with a 2xx/3xx status;
connection errors time out as failures. Latency is measured client-side around
the full request/response cycle, so proxy-injected delay shows up in it directly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..events import make_event


@dataclass
class ProbeSample:
    probe_index: int
    url: str
    ok: bool
    status: int  # 0 when the connection itself failed
    latency_ms: float | None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_index": self.probe_index,
            "url": self.url,
            "ok": self.ok,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "ts": self.ts,
        }


async def _probe_once(
    client: httpx.AsyncClient, index: int, probe: Any
) -> ProbeSample:
    started = time.perf_counter()
    try:
        if probe.method == "GET":
            resp = await client.get(probe.url, timeout=probe.timeout_s)
        else:
            resp = await client.post(probe.url, json=probe.body, timeout=probe.timeout_s)
        latency = (time.perf_counter() - started) * 1000.0
        ok = 200 <= resp.status_code < 400
        return ProbeSample(index, probe.url, ok, resp.status_code, round(latency, 2))
    except httpx.HTTPError:
        return ProbeSample(index, probe.url, False, 0, None)


async def probe_window(
    client: httpx.AsyncClient,
    probes: list[Any],
    duration_s: float,
    phase: str,
    on_event: Callable[[dict[str, Any]], None],
) -> list[ProbeSample]:
    """Probe all endpoints until the window elapses; return every sample taken."""
    samples: list[ProbeSample] = []
    loop = asyncio.get_running_loop()
    end = loop.time() + duration_s
    next_due = {i: 0.0 for i in range(len(probes))}

    while loop.time() < end:
        now = loop.time()
        for i, probe in enumerate(probes):
            if now >= next_due[i]:
                sample = await _probe_once(client, i, probe)
                samples.append(sample)
                detail = (
                    f" {sample.latency_ms:.1f}ms" if sample.latency_ms is not None else ""
                )
                on_event(
                    make_event(
                        phase,
                        f"{probe.method} {sample.url} -> {sample.status or 'ERR'}{detail}",
                        ok=sample.ok,
                        latency_ms=sample.latency_ms,
                    )
                )
                next_due[i] = now + probe.interval_s
        wake = min(next_due.values())
        await asyncio.sleep(max(0.01, min(wake, end) - loop.time()))

    return samples
