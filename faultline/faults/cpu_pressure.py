"""Spawn CPU-burner child processes to pressure the machine.

Each worker is a short Python snippet that spins on math for the fault duration.
Workers are capped by MAX_WORKERS and every one is killed in stop(), so the
fault can never outlive the experiment.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from ..registry import register
from .base import FaultError, FaultPlugin

_BURN_CODE = (
    "import math\n"
    "x = 0.0\n"
    "while True:\n"
    "    for i in range(20000):\n"
    "        x = math.sqrt(x + i) * 0.9999\n"
)


@register
class CpuPressureFault(FaultPlugin):
    name = "cpu_pressure"
    description = "Spawn CPU-burner child processes for the fault duration; all are killed on stop."

    MAX_WORKERS = 16

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> dict[str, int]:
        try:
            workers = int(params.get("workers", 2))
        except (TypeError, ValueError) as exc:
            raise FaultError("cpu_pressure: workers must be an integer") from exc
        if not 1 <= workers <= cls.MAX_WORKERS:
            raise FaultError(f"cpu_pressure: workers must be within [1, {cls.MAX_WORKERS}]")
        return {"workers": workers}

    def __init__(self) -> None:
        self._procs: list[subprocess.Popen[bytes]] = []

    async def start(self, target: Any, params: dict[str, int]) -> None:
        for _ in range(params["workers"]):
            self._procs.append(
                subprocess.Popen(
                    [sys.executable, "-c", _BURN_CODE],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )

    async def stop(self, target: Any, params: dict[str, int]) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.kill()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                pass
        self._procs = []
