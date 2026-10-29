"""Tests for timeout-aware Servo speed selection."""

from __future__ import annotations

import importlib.util
import pathlib


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    spec = importlib.util.spec_from_file_location("select_servo_speed_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_selects_slowest_feasible_candidate():
    result = load_core().select_servo_speed(
        durations_by_fraction={1.0: 6.2, 0.25: 24.8, 0.5: 12.4, 0.75: 8.3},
        max_duration_s=15.0,
    )
    assert result["feasible"] is True
    assert result["speedFraction"] == 0.5
    assert result["expected_duration_s"] == 12.4


def test_reports_no_feasible_candidate():
    result = load_core().select_servo_speed(
        durations_by_fraction={0.5: 12.0, 1.0: 6.0},
        max_duration_s=5.0,
    )
    assert result["feasible"] is False
    assert result["speedFraction"] is None


def test_rejects_invalid_contracts():
    core = load_core()
    for durations, maximum in (({}, 1), ({0: 1}, 2), ({0.5: -1}, 2), ({0.5: 1}, 0)):
        try:
            core.select_servo_speed(
                durations_by_fraction=durations,
                max_duration_s=maximum,
            )
        except ValueError:
            continue
        raise AssertionError("expected ValueError")
