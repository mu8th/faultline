"""Spawn a child process that allocates and holds bounded memory.

The allocation is capped by MAX_MB (a developer machine should never be pushed
into swap by a demo tool) and the child is killed in stop().
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from ..registry import register
from .base import FaultError, FaultPlugin

_ALLOC_TEMPLATE = (
    "import time\n"
    "chunks = []\n"
    "target = {mb} * 1024 * 1024\n"
    "while sum(map(len, chunks)) < target:\n"
    "    chunks.append(bytearray(1024 * 1024))\n"
    "time.sleep(3600)\n"
)


@register
class MemoryPressureFault(FaultPlugin):
    name = "memory_pressure"
    description = "Spawn a child process that allocates and holds bounded memory until stopped."

    MAX_MB = 2048

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> dict[str, int]:
        try:
            mb = int(params.get("mb", 256))
        except (TypeError, ValueError) as exc:
            raise FaultError("memory_pressure: mb must be an integer") from exc
        if not 16 <= mb <= cls.MAX_MB:
            raise FaultError(f"memory_pressure: mb must be within [16, {cls.MAX_MB}]")
        return {"mb": mb}

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None

    async def start(self, target: Any, params: dict[str, int]) -> None:
        code = _ALLOC_TEMPLATE.format(mb=params["mb"])
        self._proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def stop(self, target: Any, params: dict[str, int]) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                pass
            self._proc = None
