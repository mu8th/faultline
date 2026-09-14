"""Target lifecycle: spawn, health-wait, kill, restart, clean teardown."""

from __future__ import annotations

import socket
import sys
import time

import pytest

from faultline.engine import find_free_port
from faultline.models import TargetSpec
from faultline.targets.base import TargetStartError
from faultline.targets.external_target import ExternalTarget
from faultline.targets.subprocess_target import SubprocessTarget
from tests.conftest import run_async

TINY_SERVER = (
    "import http.server, sys\n"
    "port = int(sys.argv[1])\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        self.send_response(200)\n"
    "        self.end_headers()\n"
    "        self.wfile.write(b'ok')\n"
    "    def log_message(self, *a):\n"
    "        pass\n"
    "http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()\n"
)


def _tiny_server_spec() -> TargetSpec:
    return TargetSpec(
        kind="subprocess",
        command=[sys.executable, "-c", TINY_SERVER, "{port}"],
        health_url="http://127.0.0.1:{port}/",
        wait_timeout_s=15,
    )


def test_subprocess_target_full_lifecycle():
    async def scenario():
        events: list[dict] = []
        target = SubprocessTarget(_tiny_server_spec(), find_free_port(), events.append)
        await target.start()
        assert target.pid is not None
        first_pid = target.pid

        # Kill: process must actually be gone.
        assert target.can_kill()
        await target.kill()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if target._proc.poll() is not None:  # noqa: SLF001 - white-box check
                break
            await asyncio.sleep(0.1)
        assert target._proc.poll() is not None  # noqa: SLF001

        # Restart: new pid, healthy again.
        await target.restart()
        assert target.pid is not None and target.pid != first_pid

        # Stop: idempotent teardown, no orphans.
        await target.stop()
        await target.stop()
        assert target.pid is None

    import asyncio

    run_async(scenario())


def test_subprocess_target_reports_log_on_early_exit():
    async def scenario():
        spec = TargetSpec(
            kind="subprocess",
            command=[sys.executable, "-c", "import sys; print('boom'); sys.exit(3)", "{port}"],
            health_url="http://127.0.0.1:{port}/",
            wait_timeout_s=5,
        )
        target = SubprocessTarget(spec, find_free_port())
        with pytest.raises(TargetStartError, match="exited early"):
            await target.start()
        await target.stop()

    run_async(scenario())


def test_external_target_refuses_dead_port():
    async def scenario():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        spec = TargetSpec(
            kind="external",
            command=[],
            health_url=f"http://127.0.0.1:{dead_port}/health",
            wait_timeout_s=2,
        )
        target = ExternalTarget(spec)
        with pytest.raises(TargetStartError, match="not healthy"):
            await target.start()
        # stop() is a no-op for external targets and must not raise.
        await target.stop()

    run_async(scenario())


def test_external_target_upstream_address():
    spec = TargetSpec(
        kind="external",
        command=[],
        health_url="http://127.0.0.1:9911/health",
    )
    target = ExternalTarget(spec)
    assert target.upstream_address() == ("127.0.0.1", 9911)
