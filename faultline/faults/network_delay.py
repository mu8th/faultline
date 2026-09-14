"""Asyncio TCP proxy that injects latency, jitter and connection drops.

While this fault is active the engine points probes at a local proxy port; every
chunk forwarded in either direction waits latency_ms (+/- jitter_ms) before being
handed to the other side, and each new connection is dropped outright with
probability drop_rate. No privileges are required -- it is a plain localhost
listener -- which makes it work on Windows dev machines and in CI alike.

The delay is applied per hop (client->server and server->client), so an HTTP
request/response round trip sees roughly 2 x latency_ms of added delay.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from ..registry import register
from .base import FaultError, FaultPlugin


@register
class NetworkDelayFault(FaultPlugin):
    name = "network_delay"
    description = (
        "Route probes through a local TCP proxy that adds latency/jitter and "
        "drops connections at a configurable rate."
    )

    MAX_LATENCY_MS = 5000.0
    MAX_JITTER_MS = 5000.0
    MAX_DROP_RATE = 0.9

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> dict[str, float]:
        try:
            latency_ms = float(params.get("latency_ms", 300.0))
            jitter_ms = float(params.get("jitter_ms", 100.0))
            drop_rate = float(params.get("drop_rate", 0.0))
        except (TypeError, ValueError) as exc:
            msg = "network_delay: latency_ms/jitter_ms/drop_rate must be numbers"
            raise FaultError(msg) from exc
        if not 0.0 <= latency_ms <= cls.MAX_LATENCY_MS:
            raise FaultError(f"network_delay: latency_ms must be within [0, {cls.MAX_LATENCY_MS}]")
        if not 0.0 <= jitter_ms <= cls.MAX_JITTER_MS:
            raise FaultError(f"network_delay: jitter_ms must be within [0, {cls.MAX_JITTER_MS}]")
        if not 0.0 <= drop_rate <= cls.MAX_DROP_RATE:
            raise FaultError(f"network_delay: drop_rate must be within [0, {cls.MAX_DROP_RATE}]")
        return {"latency_ms": latency_ms, "jitter_ms": jitter_ms, "drop_rate": drop_rate}

    def __init__(self) -> None:
        self._listener: asyncio.Server | None = None
        self._port: int | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._rng = random.Random()

    async def start(self, target: Any, params: dict[str, float]) -> None:
        host, port = target.upstream_address()
        self._listener = await asyncio.start_server(
            lambda r, w: self._spawn(self._handle(r, w, host, port, params)),
            "127.0.0.1",
            0,
        )
        self._port = self._listener.sockets[0].getsockname()[1]

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
        params: dict[str, float],
    ) -> None:
        # Simulated packet loss at connection level.
        if self._rng.random() < params["drop_rate"]:
            writer.close()
            await writer.wait_closed()
            return
        try:
            upstream_r, upstream_w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0
            )
        except (TimeoutError, OSError):
            writer.close()
            await writer.wait_closed()
            return

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await src.read(4096)
                    if not data:
                        break
                    await asyncio.sleep(self._delay(params))
                    dst.write(data)
                    await dst.drain()
            except (ConnectionResetError, BrokenPipeError):
                pass

        t1 = self._spawn(pipe(reader, upstream_w))
        t2 = self._spawn(pipe(upstream_r, writer))
        await asyncio.gather(t1, t2)
        for w in (writer, upstream_w):
            try:
                w.close()
                await w.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError):  # pragma: no cover
                pass

    def _delay(self, params: dict[str, float]) -> float:
        base = params["latency_ms"] + self._rng.uniform(-params["jitter_ms"], params["jitter_ms"])
        return max(0.0, base) / 1000.0

    def proxy_port(self, target: Any, params: dict[str, float]) -> int | None:
        return self._port

    async def stop(self, target: Any, params: dict[str, float]) -> None:
        if self._listener is not None:
            self._listener.close()
            await self._listener.wait_closed()
            self._listener = None
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._port = None
