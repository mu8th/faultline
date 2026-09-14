# FaultLine

**Hypothesis-driven chaos testing for real processes.** Declare what you believe about your service under failure (an SLO hypothesis), let FaultLine inject bounded faults against a live target, watch it probe continuously, and get a pass/fail verdict with the evidence to back it up.

FaultLine is not a load tester. It answers a different question: *when things break in specific, declared ways, does the system do what you said it would?*

## How an experiment works

1. **Target** -- FaultLine spawns your service as a child process (or probes an external one) and waits for its health endpoint.
2. **Baseline window** -- continuous probing with no faults, so every later comparison has a reference.
3. **Fault windows** -- one fault at a time, each bounded by a hard duration and hard resource caps.
4. **Recovery window** -- the fault is torn down; probing continues while the service should heal.
5. **Evaluation** -- each SLO hypothesis (e.g. "p95 stays under 150ms during CPU pressure") is graded against the samples of its window. No data in a window fails the check; it never passes vacuously.

Verdict: **FAIL** if any hypothesis fails, otherwise **PASS**. Every run produces structured events (streamable live), a JSON report, and a Markdown report.

## Faults (v1)

| Fault | What it does | Params (defaults in brackets) |
|-------|--------------|-------------------------------|
| `process_kill` | Kills the target process; optionally restarts it after a delay. Only targets FaultLine owns. | `restart_after_s` [5] (max 300) |
| `cpu_pressure` | Spawns bounded CPU-burner child processes. | `workers` [2] (1-16) |
| `memory_pressure` | Spawns a child that allocates and holds bounded memory. | `mb` [256] (16-2048) |
| `network_delay` | Routes probes through a local TCP proxy adding per-hop latency/jitter and dropping connections at a rate. | `latency_ms` [300], `jitter_ms` [100], `drop_rate` [0] (max 5000/5000/0.9) |

All faults are cross-platform and Windows-safe -- no Docker, no privileges, no network namespaces. Every fault tears itself down when its window ends; the target is always stopped in a `finally`, so a misbehaving fault cannot leave orphans behind.

## Quickstart

Requires Python 3.11+.

```bash
git clone git@github.com:mu8th/faultline.git
cd faultline
python -m venv .venv && .venv\Scripts\activate   # Windows; use .venv/bin/activate elsewhere
pip install -r requirements.txt
```

Run the bundled experiments (each spawns a small demo "shop" service as its target):

```bash
python -m faultline run examples/experiments/baseline.yml       # healthy sanity check -> PASS
python -m faultline run examples/experiments/cpu-pressure.yml   # catches a p95 breach  -> FAIL (by design)
python -m faultline run examples/experiments/kill-restart.yml   # bounded downtime       -> PASS

python -m faultline run examples/experiments/baseline.yml --json out.json --markdown out.md
python -m faultline faults            # list registered fault types
python -m faultline experiments       # list bundled experiments
```

### Writing your own experiment

```yaml
name: my-service-under-pressure
description: What I believe will happen when the box gets hot.

target:
  kind: subprocess                       # or "external" for a service you do not own
  command: ["{python}", "-m", "myservice", "--port", "{port}"]   # argv list, never a shell string
  cwd: ..                                # relative to this file (or absolute)
  health_url: "http://127.0.0.1:{port}/health"
  wait_timeout_s: 20

probes:
  - url: "http://127.0.0.1:{port}/api/orders"
    method: POST
    body: {product_id: sku-001, quantity: 1}
    interval_s: 0.5
  - url: "http://127.0.0.1:{port}/health"

faults:
  - type: cpu_pressure
    duration_s: 8
    params: {workers: 4}

windows:
  baseline_s: 3
  recovery_s: 3

slo:
  - name: orders stay fast under CPU pressure
    window: fault        # baseline | fault | recovery
    probe: 0             # which probe (default 0)
    p95_latency_ms: 150
  - name: recovers cleanly after pressure ends
    window: recovery
    probe: 0
    error_rate_max: 0.05
```

Two placeholders are resolved at run time: `{python}` becomes the interpreter running FaultLine (so targets always see its environment), and `{port}` -- in `command`, `health_url`, and probe URLs -- becomes a free port, so experiments never collide with anything already running.

### Demo API + dashboard

```bash
uvicorn api.app:app --port 8095    # then open http://127.0.0.1:8095
```

The dashboard lists the bundled experiments; RUN starts one and streams every event live over a WebSocket, ending with the verdict and an SLO evidence table. Endpoints: `GET /api/health`, `GET /api/experiments`, `POST /api/run`, `GET /api/runs/{run_id}`, `WS /ws/run/{run_id}`.

## Security model

- **Localhost only by design.** The API binds 127.0.0.1 (override with `FAULTLINE_HOST`/ `FAULTLINE_PORT`) and the demo target binds 127.0.0.1. Nothing here is meant to be exposed.
- **No shell, ever.** Target commands are argv lists; fault processes are spawned directly. No string interpolation into a shell.
- **Strict parsing.** Experiments load through `yaml.safe_load` and every field is validated by pydantic before anything runs -- bad specs fail at load time, not mid-experiment.
- **Hard caps.** Worker counts, memory sizes, restart delays, latency, jitter, and drop rates are all bounded; a hostile or typo'd YAML cannot turn FaultLine into a resource bomb.
- **Ownership discipline.** Only subprocess targets can be killed/restarted; external targets are probe-only.
- **Clean teardown.** `stop()` is idempotent on every plugin and target; the engine always stops the target in a `finally`.

## Development

```bash
pip install -r requirements.txt
ruff check .        # lint (line-length 100, py311)
pytest -q           # full suite: SLO math, plugins, proxy over real TCP, e2e runs, API
```

The end-to-end tests spawn real child processes and probe them over loopback -- no Docker required.
