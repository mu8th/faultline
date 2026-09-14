"""Demo API: health, experiment listing, run lifecycle, WebSocket replay."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from api.app import app


def test_health_reports_faults():
    with TestClient(app) as client:
        data = client.get("/api/health").json()
    assert data["status"] == "ok"
    for name in ("cpu_pressure", "memory_pressure", "network_delay", "process_kill"):
        assert name in data["faults"]


def test_experiments_listed():
    with TestClient(app) as client:
        data = client.get("/api/experiments").json()
    names = {e["name"] for e in data}
    assert {"baseline", "cpu-pressure", "kill-restart"} <= names
    by_name = {e["name"]: e for e in data}
    assert by_name["baseline"]["faults"] == []
    assert by_name["cpu-pressure"]["faults"] == ["cpu_pressure"]


def test_run_rejects_bad_names():
    with TestClient(app) as client:
        assert client.post("/api/run", json={"experiment": "nope"}).status_code == 404
        # Path traversal attempts are refused before touching the filesystem.
        assert client.post("/api/run", json={"experiment": "../secret"}).status_code == 400
        assert client.post("/api/run", json={"experiment": ""}).status_code == 400


def test_unknown_run_404():
    with TestClient(app) as client:
        assert client.get("/api/runs/deadbeef").status_code == 404


def test_run_baseline_and_replay_over_websocket():
    with TestClient(app) as client:
        run_id = client.post("/api/run", json={"experiment": "baseline"}).json()["run_id"]

        deadline = time.time() + 120
        state = {"status": "running"}
        while time.time() < deadline and state["status"] == "running":
            time.sleep(1)
            state = client.get(f"/api/runs/{run_id}").json()
        assert state["status"] == "done", f"run did not finish: {state}"
        assert state["report"]["verdict"] == "pass"

        # WebSocket replay: connecting after completion must still deliver the
        # full event history followed by the final report frame.
        with client.websocket_connect(f"/ws/run/{run_id}") as ws:
            frames = []
            while True:
                frame = ws.receive_json()
                frames.append(frame)
                if frame.get("type") == "final":
                    break
            assert len(frames) > 3, "expected buffered event replay before the final frame"
            assert any(f.get("phase") == "done" for f in frames)
            assert frames[-1]["report"]["verdict"] == "pass"
