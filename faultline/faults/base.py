"""Fault plugin interface.

A fault is a side effect applied to (or in front of) the target for a bounded
duration. Plugins must be safe to run on a developer machine: no destructive
defaults, hard caps on resource use, and a stop() that is idempotent and leaves
no orphan processes or listeners behind.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # pragma: no cover
    from ..targets.base import Target


class FaultError(RuntimeError):
    """Raised when a fault is misconfigured or cannot start."""


class FaultPlugin(ABC):
    """Interface every fault implements. Subclasses set name/description and
    override validate_params/start (and stop when teardown is needed)."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> Any:
        """Validate and normalize plugin parameters; raise FaultError on bad input."""
        return params

    @abstractmethod
    async def start(self, target: Target, params: Any) -> None:
        """Begin injecting the fault. Must not block longer than a moment."""

    async def stop(self, target: Target, params: Any) -> None:
        """Tear down the fault. Idempotent; leaves no orphans."""
        return None

    def proxy_port(self, target: Target, params: Any) -> int | None:
        """Local proxy port that probes should route through while this fault is
        active (None = probe the target directly)."""
        return None
