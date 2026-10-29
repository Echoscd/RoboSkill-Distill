"""Tests for the wall-clock arrival poll state transition."""

from __future__ import annotations

import importlib.util
import pathlib


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    spec = importlib.util.spec_from_file_location("wait_for_joint_arrival_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_requires_consecutive_arrival_samples():
    core = load_core()
    first = core.evaluate_sample(
        measured_joints=[0.01, 0.99], target_joints=[0, 1], tolerance_rad=0.02,
        faults=[], consecutive_reached=0, stable_samples=2,
    )
    assert first["sample_reached"] is True
    assert first["reached"] is False
    second = core.evaluate_sample(
        measured_joints=[0.0, 1.0], target_joints=[0, 1], tolerance_rad=0.02,
        faults=[], consecutive_reached=first["consecutive_reached"], stable_samples=2,
    )
    assert second["reached"] is True


def test_fault_resets_arrival():
    result = load_core().evaluate_sample(
        measured_joints=[0, 1], target_joints=[0, 1], tolerance_rad=0.02,
        faults=["controller_fault"], consecutive_reached=1, stable_samples=2,
    )
    assert result["reached"] is False
    assert result["consecutive_reached"] == 0


def test_out_of_tolerance_resets_counter():
    result = load_core().evaluate_sample(
        measured_joints=[0.1, 1], target_joints=[0, 1], tolerance_rad=0.02,
        faults=[], consecutive_reached=1, stable_samples=2,
    )
    assert result["sample_reached"] is False
    assert result["consecutive_reached"] == 0
