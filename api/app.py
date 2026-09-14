"""FaultLine demo API: run experiments on demand and stream them live.

Binds to 127.0.0.1 by design (local-only, same convention as the portfolio
site). Run with:

    uvicorn api.app:app --port 8095

Endpoints
---------
* GET  /api/health           -- liveness + registered fault types.
* GET  /api/experiments      -- bundled example experiments.
* POST /api/run              -- start a run; returns a run_id immediately.
* GET  /api/runs/{run_id}    -- poll status/report for a run.
* WS   /ws/run/{run_id}      -- live event stream, ending with the final report.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from faultline import __version__
from faultline.engine import ExperimentRunner
from faultline.events import make_event
from faultline.models import ExperimentLoadError, load_experiment
from faultline.registry import available as faults_available

BASE_DIR = Path(__file__).resolve().parent.parent  # faultline repo root
EXAMPLES_DIR = BASE_DIR / "examples" / "experiments"
BIND_HOST = os.environ.get("FAULTLINE_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("FAULTLINE_PORT", "8095"))

MAX_RUNS = 32


@dataclass
class RunState:
    run_id: str
    experiment: str
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[Any]] = field(default_factory=set)
    report: dict[str, Any] | None = None
    error: str | None = None

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)


_RUNS: OrderedDict[str, RunState] = OrderedDict()


def _prune_runs() -> None:
    while len(_RUNS) > MAX_RUNS:
        for key, state in _RUNS.items():
            if state.status != "running":
                del _RUNS[key]
                return
        # All runs still active: drop the oldest regardless.
        _RUNS.popitem(last=False)


def _experiment_path(name: str) -> Path:
    # Reject anything that could escape the examples directory (path traversal).
    # chr(92) is the backslash; separators and parent refs must never reach the FS.
    if "/" in name or chr(92) in name or ".." in name or not name.strip():
        raise HTTPException(status_code=400, detail="invalid experiment name")
    path = EXAMPLES_DIR / f"{name}.yml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown experiment '{name}'")
    return path


app = FastAPI(title="FaultLine API", version=__version__)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "faults": faults_available()}


@app.get("/api/experiments")
def experiments() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(EXAMPLES_DIR.glob("*.yml")):
        try:
            spec = load_experiment(path)
        except ExperimentLoadError as exc:
            out.append({"name": path.stem, "description": f"invalid: {exc}", "faults": []})
            continue
        out.append(
            {
                "name": path.stem,
                "description": spec.description,
                "faults": [f.type for f in spec.faults],
            }
        )
    return out


@app.post("/api/run")
async def start_run(body: dict[str, Any]) -> dict[str, str]:
    name = str(body.get("experiment", ""))
    path = _experiment_path(name)
    run_id = uuid.uuid4().hex[:12]
    state = RunState(run_id=run_id, experiment=name)
    _RUNS[run_id] = state
    _prune_runs()
    asyncio.create_task(_execute(state, path))
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return {
        "run_id": state.run_id,
        "experiment": state.experiment,
        "status": state.status,
        "report": state.report,
        "error": state.error,
    }


@app.websocket("/ws/run/{run_id}")
async def ws_run(ws: WebSocket, run_id: str) -> None:
    state = _RUNS.get(run_id)
    if state is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    state.subscribers.add(queue)
    try:
        # Replay buffered events, then stream live ones.
        for event in list(state.events):
            await ws.send_json(event)
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                if state.status != "running":
                    break
                continue
            await ws.send_json(event)
            if state.status != "running":
                break
        await ws.send_json(
            {"type": "final", "report": state.report, "error": state.error}
        )
    except WebSocketDisconnect:
        pass
    finally:
        state.subscribers.discard(queue)
        try:
            await ws.close()
        except Exception:  # pragma: no cover - already disconnected
            pass


async def _execute(state: RunState, path: Path) -> None:
    try:
        spec = load_experiment(path)
    except ExperimentLoadError as exc:
        state.status = "error"
        state.error = str(exc)
        state.publish(make_event("error", str(exc)))
        return
    try:
        # Relative target.cwd is anchored at the experiment file's directory,
        # exactly like the CLI does.
        report = await ExperimentRunner(spec, state.publish, base_dir=path.parent).run()
        state.report = report.to_dict()
        state.status = "done"
    except Exception as exc:  # noqa: BLE001 - run boundary; surfaced to the client
        state.status = "error"
        state.error = str(exc)
        state.publish(make_event("error", f"experiment failed: {exc}"))


# ── Static dashboard (whitelisted, like the portfolio site) ─────────────────
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_ALLOWED_STATIC = {"index.html"}


class _PublicStaticFiles(StaticFiles):
    """Serve only whitelisted files; everything else 404s."""

    async def get_response(self, path: str, scope: dict[str, Any]) -> PlainTextResponse | Any:
        base = path.split("/", 1)[0]
        if base not in _ALLOWED_STATIC:
            return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)


if _STATIC_DIR.is_dir():
    app.mount("/", _PublicStaticFiles(directory=_STATIC_DIR, html=True), name="static")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host=BIND_HOST, port=BIND_PORT)
