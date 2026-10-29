"""Tests for deterministic joint-arrival verification."""

from __future__ import annotations

import importlib.util
import pathlib


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    spec = importlib.util.spec_from_file_location("verify_joint_arrival_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reached_and_error_metrics():
    core = load_core()
    result = core.verify_joint_arrival(
        measured_joints=[0.01, 0.98, -0.99],
        target_joints=[0.0, 1.0, -1.0],
        tolerance_rad=0.02,
    )
    assert result["reached"] is False
    assert abs(result["max_abs_error_rad"] - 0.02) < 1e-12
    reached = core.verify_joint_arrival(
        measured_joints=[0.01, 0.981, -0.99],
        target_joints=[0.0, 1.0, -1.0],
        tolerance_rad=0.02,
    )
    assert reached["reached"] is True


def test_rejects_bad_contracts():
    core = load_core()
    for measured, target, tolerance in (([], [], 0.1), ([0], [0, 1], 0.1), ([0], [0], 0)):
        try:
            core.verify_joint_arrival(
                measured_joints=measured,
                target_joints=target,
                tolerance_rad=tolerance,
            )
        except ValueError:
            continue
        raise AssertionError("expected ValueError")
