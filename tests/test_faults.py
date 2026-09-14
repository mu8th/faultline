"""Fault plugin parameter validation and process lifecycle (no target needed)."""

from __future__ import annotations

import time

import pytest

from faultline import faults  # noqa: F401 -- registers built-ins
from faultline.faults.base import FaultError
from faultline.faults.cpu_pressure import CpuPressureFault
from faultline.faults.memory_pressure import MemoryPressureFault
from faultline.faults.network_delay import NetworkDelayFault
from faultline.faults.process_kill import ProcessKillFault
from tests.conftest import run_async


class _FakeTarget:
    """Minimal target stand-in: not killable, no upstream address."""

    def can_kill(self) -> bool:
        return False

    def upstream_address(self):
        raise AssertionError("should not be called")


def test_cpu_pressure_default_params():
    assert CpuPressureFault.validate_params({}) == {"workers": 2}


def test_cpu_pressure_rejects_bad_worker_counts():
    for bad in (0, -1, 99, "four", None):
        with pytest.raises(FaultError):
            CpuPressureFault.validate_params({"workers": bad})


def test_memory_pressure_bounds():
    assert MemoryPressureFault.validate_params({}) == {"mb": 256}
    for bad in (8, -16, 4096, "lots"):
        with pytest.raises(FaultError):
            MemoryPressureFault.validate_params({"mb": bad})


def test_process_kill_bounds():
    # Default is kill-only (no restart); the kill-restart example opts in explicitly.
    assert ProcessKillFault.validate_params({}) == {"restart_after_s": 0.0}
    for bad in (-1, 301, "soon"):
        with pytest.raises(FaultError):
            ProcessKillFault.validate_params({"restart_after_s": bad})


def test_network_delay_bounds():
    ok = NetworkDelayFault.validate_params({})
    assert ok["latency_ms"] == 300.0 and ok["drop_rate"] == 0.0
    for params in (
        {"latency_ms": 99999},
        {"jitter_ms": -5},
        {"drop_rate": 0.95},
        {"drop_rate": "flaky"},
    ):
        with pytest.raises(FaultError):
            NetworkDelayFault.validate_params(params)


def test_process_kill_refuses_external_targets():
    async def scenario():
        plugin = ProcessKillFault()
        params = plugin.validate_params({})
        with pytest.raises(FaultError, match="requires a subprocess target"):
            await plugin.start(_FakeTarget(), params)
        await plugin.stop(_FakeTarget(), params)

    run_async(scenario())


def test_cpu_pressure_start_stop_lifecycle():
    async def scenario():
        plugin = CpuPressureFault()
        params = plugin.validate_params({"workers": 2})
        await plugin.start(_FakeTarget(), params)
        procs = list(plugin._procs)  # noqa: SLF001 - white-box lifecycle check
        assert len(procs) == 2
        assert all(p.poll() is None for p in procs)
        await plugin.stop(_FakeTarget(), params)
        deadline = time.monotonic() + 5
        while any(p.poll() is None for p in procs) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert all(p.poll() is not None for p in procs), "burner processes leaked"

    import asyncio

    run_async(scenario())


def test_stop_is_idempotent():
    async def scenario():
        plugin = CpuPressureFault()
        params = plugin.validate_params({"workers": 1})
        await plugin.start(_FakeTarget(), params)
        await plugin.stop(_FakeTarget(), params)
        await plugin.stop(_FakeTarget(), params)  # second stop must not raise

    run_async(scenario())
