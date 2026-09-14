"""Fault plugin registry behavior."""

from __future__ import annotations

import pytest

from faultline import faults  # noqa: F401 -- registers built-ins
from faultline.registry import UnknownFaultError, available, get


def test_builtin_faults_registered():
    names = available()
    assert "cpu_pressure" in names
    assert "memory_pressure" in names
    assert "network_delay" in names
    assert "process_kill" in names
    assert names == sorted(names)


def test_get_returns_class_with_matching_name():
    cls = get("cpu_pressure")
    assert cls.name == "cpu_pressure"
    assert cls.description  # non-empty for CLI/docs


def test_unknown_fault_lists_options():
    with pytest.raises(UnknownFaultError, match="unknown fault type 'warp_drive'"):
        get("warp_drive")
