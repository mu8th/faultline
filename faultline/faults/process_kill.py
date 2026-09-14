"""Terminate the target process; optionally restart it after a delay.

The classic chaos question: "does the system come back when something dies?"
With restart_after_s > 0 the target is killed, then FaultLine restarts it after
the delay so the recovery window measures a clean return to health.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..registry import register
from .base import FaultError, FaultPlugin


@register
class ProcessKillFault(FaultPlugin):
    name = "process_kill"
    description = (
        "Terminate the target process; optionally restart it after a delay so the "
        "recovery window measures a clean return to health."
    )

    MAX_RESTART_DELAY_S = 300.0

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> dict[str, float]:
        try:
            restart_after_s = float(params.get("restart_after_s", 0.0))
        except (TypeError, ValueError) as exc:
            raise FaultError("process_kill: restart_after_s must be a number") from exc
        if not 0.0 <= restart_after_s <= cls.MAX_RESTART_DELAY_S:
            raise FaultError(
                f"process_kill: restart_after_s must be within [0, {cls.MAX_RESTART_DELAY_S}]"
            )
        return {"restart_after_s": restart_after_s}

    def __init__(self) -> None:
        self._restart_task: asyncio.Task[None] | None = None
        self.restart_error: Exception | None = None

    async def start(self, target: Any, params: dict[str, float]) -> None:
        if not target.can_kill():
            raise FaultError(
                "process_kill requires a subprocess target (external targets are "
                "not owned by FaultLine)"
            )
        await target.kill()
        if params["restart_after_s"] > 0:
            self._restart_task = asyncio.create_task(
                self._restart_later(target, params["restart_after_s"])
            )

    async def _restart_later(self, target: Any, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await target.restart()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # surfaced by the engine after stop()
            self.restart_error = exc

    async def stop(self, target: Any, params: dict[str, float]) -> None:
        if self._restart_task is not None and not self._restart_task.done():
            self._restart_task.cancel()
            try:
                await self._restart_task
            except (asyncio.CancelledError, Exception):
                pass
        self._restart_task = None
