"""Events emitted while an experiment runs.

Events are plain dicts so the same stream can be printed (CLI), queued for a
WebSocket (API) or asserted on (tests) without shared dependencies. Shape:

    {"ts": 1721460000.123, "phase": "fault", "message": "...", ...extra}

Phases: target | baseline | fault | recovery | evaluate | done | error
"""

from __future__ import annotations

import time
from typing import Any, Literal

Phase = Literal["target", "baseline", "fault", "recovery", "evaluate", "done", "error"]


def make_event(phase: Phase, message: str, **extra: Any) -> dict[str, Any]:
    """Build one event; extra keys are passed through (e.g. ok, latency_ms)."""
    event: dict[str, Any] = {"ts": time.time(), "phase": phase, "message": message}
    event.update(extra)
    return event
