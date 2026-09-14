"""A target spawned as a child process by FaultLine.

The command is an argv list (never a shell string). Two placeholders are
resolved at run time: "{python}" becomes the interpreter running FaultLine
(sys.executable), so targets always see the same environment, and "{port}" in
the command and health URL becomes a free port chosen at run time. Child
stdout/stderr go to a temp log file whose tail is included in start errors, so a
broken target command produces a readable failure instead of silence.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..events import make_event
from .base import Target, TargetError, TargetStartError


class SubprocessTarget(Target):
    def __init__(
        self,
        spec: Any,
        port: int | None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._spec = spec
        self.port = port
        self._on_event = on_event or (lambda e: None)
        if port is not None:
            self._command = [
                arg.replace("{python}", sys.executable).replace("{port}", str(port))
                for arg in spec.command
            ]
            self._health_url = spec.health_url.replace("{port}", str(port))
        else:  # pragma: no cover - engine always allocates a port for subprocess
            self._command = list(spec.command)
            self._health_url = spec.health_url
        cwd = spec.cwd
        self._cwd: str | None = cwd if (cwd and Path(cwd).is_absolute()) else None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_path: Path | None = None
        self.pid: int | None = None

    def _emit(self, phase: str, message: str, **extra: Any) -> None:
        self._on_event(make_event(phase, message, **extra))

    async def start(self) -> None:
        self._spawn()
        await self._wait_healthy()

    def _spawn(self) -> None:
        log_file = tempfile.NamedTemporaryFile(
            prefix="faultline-target-", suffix=".log", delete=False
        )
        self._log_path = Path(log_file.name)
        log_file.close()
        with open(self._log_path, "wb") as out:
            self._proc = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        self.pid = self._proc.pid

    async def _wait_healthy(self) -> None:
        deadline = time.monotonic() + self._spec.wait_timeout_s
        last_error = "unknown"
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:
                if self._proc is not None and self._proc.poll() is not None:
                    raise TargetStartError(
                        f"target exited early (code {self._proc.returncode}): {self._log_tail()}"
                    )
                try:
                    resp = await client.get(self._health_url, timeout=2.0)
                    if resp.status_code == 200:
                        return
                    last_error = f"HTTP {resp.status_code}"
                except httpx.HTTPError as exc:
                    last_error = type(exc).__name__
                await asyncio.sleep(0.3)
        raise TargetStartError(
            f"target not healthy within {self._spec.wait_timeout_s}s ({last_error}): "
            f"{self._log_tail()}"
        )

    def _log_tail(self, lines: int = 8) -> str:
        if self._log_path is None or not self._log_path.exists():
            return "(no log)"
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(unreadable log)"
        tail = text.strip().splitlines()[-lines:]
        return " | ".join(tail) if tail else "(empty log)"

    def can_kill(self) -> bool:
        return True

    async def kill(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._emit("fault", f"target process {self.pid} terminated")

    async def restart(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                pass
        self._spawn()
        await self._wait_healthy()
        self._emit("fault", f"target restarted (pid {self.pid})")

    async def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                pass
        self._proc = None
        self.pid = None

    def upstream_address(self) -> tuple[str, int]:
        parts = urlsplit(self._health_url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port
        if port is None:
            raise TargetError(f"health_url {self._health_url} has no explicit port")
        return host, port
