"""Experiment YAML loading and validation."""

from __future__ import annotations

import pytest

from faultline.models import ExperimentLoadError, load_experiment

VALID = """
name: demo
description: valid spec
target:
  kind: subprocess
  command: [python, -m, examples.target.shop, "--port", "{port}"]
  health_url: "http://127.0.0.1:{port}/health"
probes:
  - url: "http://127.0.0.1:{port}/health"
faults:
  - type: cpu_pressure
    duration_s: 5
    params: {workers: 2}
windows:
  baseline_s: 2
  recovery_s: 2
slo:
  - name: healthy
    window: baseline
    error_rate_max: 0.1
"""


def test_valid_spec_loads(tmp_path):
    p = tmp_path / "exp.yml"
    p.write_text(VALID, encoding="utf-8")
    spec = load_experiment(p)
    assert spec.name == "demo"
    assert spec.target.kind == "subprocess"
    assert spec.faults[0].type == "cpu_pressure"
    assert spec.slo[0].window == "baseline"


def test_subprocess_requires_command(tmp_path):
    p = tmp_path / "exp.yml"
    p.write_text("name: x\ntarget:\n  kind: subprocess\n", encoding="utf-8")
    with pytest.raises(ExperimentLoadError, match="command"):
        load_experiment(p)


def test_invalid_window_rejected(tmp_path):
    text = VALID.replace('window: baseline', 'window: lunchbreak')
    p = tmp_path / "exp.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ExperimentLoadError):
        load_experiment(p)


def test_non_mapping_yaml_rejected(tmp_path):
    p = tmp_path / "exp.yml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ExperimentLoadError, match="mapping"):
        load_experiment(p)


def test_malformed_yaml_rejected(tmp_path):
    p = tmp_path / "exp.yml"
    p.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ExperimentLoadError, match="YAML"):
        load_experiment(p)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ExperimentLoadError, match="cannot read"):
        load_experiment(tmp_path / "nope.yml")


def test_probe_url_must_be_http(tmp_path):
    text = VALID.replace('url: "http://127.0.0.1:{port}/health"', 'url: "ftp://nope"')
    p = tmp_path / "exp.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ExperimentLoadError):
        load_experiment(p)


def test_negative_probe_index_rejected(tmp_path):
    text = VALID.replace("window: baseline", "window: baseline\n    probe: -1")
    p = tmp_path / "exp.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ExperimentLoadError):
        load_experiment(p)
