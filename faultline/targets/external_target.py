"""A target that is already running somewhere (container, another machine on the LAN).

FaultLine only probes it; faults that need process ownership (process_kill) are
refused for external targets.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..events import make_event
from .base import Target, TargetStartError


class ExternalTarget(Target):
    def __init__(
        self,
        spec: Any,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._spec = spec
        self._on_event = on_event or (lambda e: None)
        self._health_url = spec.health_url
        parts = urlsplit(self._health_url)
        self.port = parts.port

    async def start(self) -> None:
        deadline = time.monotonic() + self._spec.wait_timeout_s
        last_error = "unknown"
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(self._health_url, timeout=2.0)
                    if resp.status_code == 200:
                        return
                    last_error = f"HTTP {resp.status_code}"
                except httpx.HTTPError as exc:
                    last_error = type(exc).__name__
                await asyncio.sleep(0.3)
        raise TargetStartError(
            f"external target not healthy within {self._spec.wait_timeout_s}s ({last_error})"
        )

    async def stop(self) -> None:
        # Nothing to tear down: FaultLine does not own this process.
        msg = "external target left running (not owned by FaultLine)"
        self._on_event(make_event("target", msg))

    def upstream_address(self) -> tuple[str, int]:
        parts = urlsplit(self._health_url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port
        if port is None:
            raise TargetStartError(f"health_url {self._health_url} has no explicit port")
        return host, port
