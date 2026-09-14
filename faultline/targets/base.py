"""Target interface: a running service FaultLine can probe (and optionally own)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TargetError(RuntimeError):
    """Raised for target operations that are not supported or fail."""


class TargetStartError(TargetError):
    """Raised when a spawned target does not become healthy in time."""


class Target(ABC):
    """A running service.

    Subprocess targets are owned by FaultLine and can be killed/restarted by
    faults; external targets are only probed (FaultLine never touches processes
    it does not own).
    """

    port: int | None = None

    @abstractmethod
    async def start(self) -> None:
        """Bring the target up (spawn if needed) and wait until healthy."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down. Idempotent; leaves no orphan processes."""

    def can_kill(self) -> bool:
        """Whether faults may kill/restart this target's process."""
        return False

    async def kill(self) -> None:
        raise TargetError("this target cannot be killed (not owned by FaultLine)")

    async def restart(self) -> None:
        raise TargetError("this target cannot be restarted")

    def upstream_address(self) -> tuple[str, int]:
        """(host, port) of the real service, for proxy-style faults."""
        raise TargetError("this target exposes no upstream address")
