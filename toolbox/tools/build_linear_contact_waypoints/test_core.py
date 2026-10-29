"""Tests for arm-independent linear-contact waypoint construction."""

from __future__ import annotations

import importlib.util
import pathlib

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    spec = importlib.util.spec_from_file_location("build_contact_waypoints_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_builds_four_complete_arm_independent_variants():
    core = load_core()
    result = core.build_linear_contact_waypoints(
        contact_point_world_m=[0.1, -0.2, 0.8],
        surface_outward_normal_world=[0, 0, 1],
        preferred_tangent_axis_world=[1, 0, 0],
        approach_distance_m=0.1,
        press_distance_m=0.03,
        observation_id="obs_current",
        observed_at_s=2,
        valid_for_s=5,
        position_uncertainty_m=0.01,
    )
    assert len(result["waypoint_variants"]) == 4
    assert [item["stage"] for item in result["waypoint_variants"][0]["waypoints"]] == [
        "approach", "contact", "press", "retreat"
    ]
    points = [item["tcp_pose_world"][:3] for item in result["waypoint_variants"][0]["waypoints"]]
    assert np.allclose(points[0], [0.1, -0.2, 0.9])
    assert np.allclose(points[1], [0.1, -0.2, 0.8])
    assert np.allclose(points[2], [0.1, -0.2, 0.77])
    assert "arm" not in result and "effector" not in result
    assert result["based_on"] == ["obs_current"]
    assert result["contact_model"]["reference"] == "tcp_origin"
    assert result["contact_model"]["physical_contact_feature"] is None
    assert result["contact_model"]["physical_contact_verified"] is None


def test_rejects_degenerate_geometry():
    core = load_core()
    common = dict(
        contact_point_world_m=[0, 0, 1],
        surface_outward_normal_world=[0, 0, 1],
        preferred_tangent_axis_world=[1, 0, 0],
        approach_distance_m=0.1,
        press_distance_m=0.03,
        observation_id="obs",
        observed_at_s=1,
        valid_for_s=5,
        position_uncertainty_m=0.01,
    )
    for patch in (
        {"preferred_tangent_axis_world": [0, 0, 1]},
        {"surface_outward_normal_world": [0, 0, 0]},
        {"approach_distance_m": 0.02, "press_distance_m": 0.03},
    ):
        try:
            core.build_linear_contact_waypoints(**{**common, **patch})
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {patch}")
