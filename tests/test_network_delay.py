"""NetworkDelayFault measured over real loopback TCP against an echo server."""

from __future__ import annotations

import asyncio
import time

from faultline.faults.network_delay import NetworkDelayFault
from tests.conftest import run_async


async def _start_echo_server():
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        if data:
            writer.write(data)
            await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError):
            pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server


class _EchoTarget:
    def __init__(self, port: int) -> None:
        self._port = port

    def upstream_address(self):
        return ("127.0.0.1", self._port)


async def _rtt_through(port: int) -> tuple[bytes, float]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    started = time.perf_counter()
    writer.write(b"ping\n")
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    writer.close()
    return data, elapsed_ms


def test_proxy_adds_latency_and_forwards_payload():
    async def scenario():
        server = await _start_echo_server()
        port = server.sockets[0].getsockname()[1]
        target = _EchoTarget(port)
        plugin = NetworkDelayFault()
        params = plugin.validate_params({"latency_ms": 120, "jitter_ms": 0})
        await plugin.start(target, params)
        proxy_port = plugin.proxy_port(target, params)
        assert proxy_port is not None

        direct_data, direct_ms = await _rtt_through(port)
        proxy_data, proxy_ms = await _rtt_through(proxy_port)
        assert direct_data == b"ping\n"
        assert proxy_data == b"ping\n", "payload must survive the proxy intact"

        added = proxy_ms - direct_ms
        # Two hops x 120ms expected; generous bounds keep CI from flaking.
        assert 150 <= added <= 800, f"expected ~240ms of injected delay, got {added:.0f}ms"

        await plugin.stop(target, params)
        server.close()
        await server.wait_closed()

    run_async(scenario())


def test_drop_rate_drops_most_connections():
    async def scenario():
        server = await _start_echo_server()
        port = server.sockets[0].getsockname()[1]
        target = _EchoTarget(port)
        plugin = NetworkDelayFault()
        params = plugin.validate_params({"latency_ms": 0, "jitter_ms": 0, "drop_rate": 0.9})
        await plugin.start(target, params)
        proxy_port = plugin.proxy_port(target, params)

        failures = 0
        for _ in range(12):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                writer.write(b"ping\n")
                await writer.drain()
                data = await asyncio.wait_for(reader.read(1), timeout=2.0)
                if not data:
                    failures += 1
                writer.close()
            except (TimeoutError, OSError):
                failures += 1
        # p(drop)=0.9 over 12 connections: P(<6 failures) is ~1e-5.
        assert failures >= 6, f"drop_rate=0.9 should drop most of 12 connections, got {failures}"

        await plugin.stop(target, params)
        server.close()
        await server.wait_closed()

    run_async(scenario())


def test_stop_closes_listener():
    async def scenario():
        server = await _start_echo_server()
        port = server.sockets[0].getsockname()[1]
        target = _EchoTarget(port)
        plugin = NetworkDelayFault()
        params = plugin.validate_params({"latency_ms": 10})
        await plugin.start(target, params)
        proxy_port = plugin.proxy_port(target, params)
        await plugin.stop(target, params)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.close()
            raised = False
        except OSError:
            raised = True
        assert raised, "proxy listener should be closed after stop()"

        server.close()
        await server.wait_closed()

    run_async(scenario())
