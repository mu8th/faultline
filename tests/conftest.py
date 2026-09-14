"""Shared fixtures and spec factories for the FaultLine test suite."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from faultline.models import (  # noqa: E402
    ExperimentSpec,
    FaultSpec,
    ProbeSpec,
    SloSpec,
    TargetSpec,
    WindowsSpec,
)


def make_spec(
    name: str = "test-experiment",
    faults: list[FaultSpec] | None = None,
    slo: list[SloSpec] | None = None,
    windows: WindowsSpec | None = None,
    probes: list[ProbeSpec] | None = None,
    description: str = "spec built by tests",
) -> ExperimentSpec:
    """Build an in-memory spec targeting the bundled shop demo service."""
    if probes is None:
        probes = [
            ProbeSpec(
                url="http://127.0.0.1:{port}/api/orders",
                method="POST",
                body={"product_id": "sku-001", "quantity": 1},
                interval_s=0.4,
            ),
            ProbeSpec(url="http://127.0.0.1:{port}/health", interval_s=0.4),
        ]
    return ExperimentSpec(
        name=name,
        description=description,
        target=TargetSpec(
            kind="subprocess",
            command=["{python}", "-m", "examples.target.shop", "--port", "{port}"],
            cwd=str(REPO_ROOT),
            health_url="http://127.0.0.1:{port}/health",
            wait_timeout_s=25,
        ),
        probes=probes,
        faults=faults if faults is not None else [],
        windows=windows or WindowsSpec(baseline_s=1.5, recovery_s=1.5),
        slo=slo if slo is not None else [],
    )


def run_async(coro):
    """Run an async experiment/coroutine from a sync test (no pytest-asyncio dep)."""
    import asyncio

    return asyncio.run(coro)
