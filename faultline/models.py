"""Pydantic models for FaultLine experiment definitions.

Every experiment is declared in YAML and validated through these models before
anything runs, so a malformed spec fails fast with a readable error instead of
producing a half-run experiment.

Security notes:
* YAML is parsed with yaml.safe_load only -- never yaml.load.
* Target commands are argv lists, not shell strings; nothing here is ever passed
  to a shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class ExperimentLoadError(ValueError):
    """Raised when an experiment file is missing, unreadable, or invalid."""


class TargetSpec(BaseModel):
    """How the system under test is reached.

    subprocess targets are spawned by FaultLine (and may be killed and restarted
    by faults); external targets are already running somewhere (for example a
    container) and are only probed.
    """

    kind: Literal["subprocess", "external"] = "subprocess"
    # argv list, never a shell string. "{port}" is replaced with a free port
    # chosen at run time (subprocess targets only).
    command: list[str] = Field(default_factory=list)
    health_url: str = "http://127.0.0.1:{port}/health"
    wait_timeout_s: float = Field(default=15.0, gt=0, le=120)
    # Working directory for spawned targets; relative paths resolve against the
    # experiment file's location.
    cwd: str | None = None

    @field_validator("health_url")
    @classmethod
    def _check_health_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("health_url must start with http:// or https://")
        return v


class ProbeSpec(BaseModel):
    """One endpoint probed on a fixed interval during every window."""

    url: str  # "{port}" supported
    method: Literal["GET", "POST"] = "GET"
    body: dict[str, Any] | None = None
    interval_s: float = Field(default=0.5, gt=0.1, le=30)
    timeout_s: float = Field(default=2.0, gt=0, le=30)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("probe url must start with http:// or https://")
        return v


class FaultSpec(BaseModel):
    """One fault to inject during the experiment."""

    type: str  # registry key, e.g. "cpu_pressure"
    duration_s: float = Field(default=10.0, gt=0, le=600)
    params: dict[str, Any] = Field(default_factory=dict)


class SloSpec(BaseModel):
    """A hypothesis about behavior in one window, expressed as SLO checks.

    An SLO passes only if every check it declares passes; a check with no data
    (for example p95 when every probe failed) fails rather than passing vacuously.
    """

    name: str
    window: Literal["baseline", "fault", "recovery"]
    # Index into ExperimentSpec.probes; defaults to the first probe.
    probe: int | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, gt=0)
    error_rate_max: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slo name must be non-empty")
        return v


class WindowsSpec(BaseModel):
    """Durations of the baseline and recovery windows (fault durations come from FaultSpec)."""

    baseline_s: float = Field(default=5.0, gt=0, le=300)
    recovery_s: float = Field(default=4.0, gt=0, le=300)


class ExperimentSpec(BaseModel):
    """A complete, validated experiment definition."""

    name: str
    description: str = ""
    target: TargetSpec
    probes: list[ProbeSpec] = Field(
        default_factory=lambda: [ProbeSpec(url="http://127.0.0.1:{port}/health")]
    )
    faults: list[FaultSpec] = Field(default_factory=list)
    windows: WindowsSpec = Field(default_factory=WindowsSpec)
    slo: list[SloSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_target(self) -> ExperimentSpec:
        if self.target.kind == "subprocess" and not self.target.command:
            raise ValueError("subprocess targets require a non-empty command (argv list)")
        return self


def load_experiment(path: str | Path) -> ExperimentSpec:
    """Load and validate an experiment YAML file.

    Raises:
        ExperimentLoadError: with a human-readable message on any failure.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExperimentLoadError(f"cannot read experiment file {p}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExperimentLoadError(f"invalid YAML in {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExperimentLoadError(f"experiment file {p} must contain a mapping")
    try:
        return ExperimentSpec.model_validate(data)
    except ValidationError as exc:
        raise ExperimentLoadError(f"invalid experiment spec in {p}:\n{exc}") from exc
