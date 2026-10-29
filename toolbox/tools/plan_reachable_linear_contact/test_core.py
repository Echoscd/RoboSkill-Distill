"""Contract tests for the reachable linear-contact composition wrapper."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    kinex = types.ModuleType("kinex")
    kinex.device = lambda name, action, args=None: {"positions": [0.0] * 6}
    frames = types.ModuleType("kinex.frames")
    frames.pose = lambda parent, child: {"translation": [0, 0, 0], "rotation": [0, 0, 0, 1]}
    geometry = types.ModuleType("kinex.geometry")
    geometry.compose_rt = lambda left, right: (
        (np.asarray(left[0]) @ np.asarray(right[0])).tolist(),
        (np.asarray(left[0]) @ np.asarray(right[1]) + np.asarray(left[1])).tolist(),
    )
    geometry.invert_rt = lambda value: (
        np.asarray(value[0]).T.tolist(),
        (-np.asarray(value[0]).T @ np.asarray(value[1])).tolist(),
    )
    geometry.mount_to_rt = lambda value: (np.eye(3).tolist(), [0, 0, 0])
    geometry.xyzq_to_rt = lambda value: (np.eye(3).tolist(), list(value[:3]))
    geometry.rt_to_pose = lambda value: {"translation": value[1], "rotation": [0, 0, 0, 1]}
    sys.modules.update({"kinex": kinex, "kinex.frames": frames, "kinex.geometry": geometry})
    spec = importlib.util.spec_from_file_location("reachable_contact_wrapper_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_composes_builder_and_generic_solver_with_legacy_fields():
    core = load_core()
    calls = {}

    def builder(**kwargs):
        calls["builder"] = kwargs
        return {
            "waypoint_set_id": "wps",
            "motion_semantics": "linear_normal_contact",
            "contact_model": {"reference": "tcp_origin", "physical_contact_feature": None, "physical_contact_verified": None},
            "based_on": [kwargs["observation_id"]],
            "observed_at_s": kwargs["observed_at_s"],
            "expires_at_s": kwargs["observed_at_s"] + kwargs["valid_for_s"],
            "position_uncertainty_m": kwargs["position_uncertainty_m"],
            "contact_point_world_m": kwargs["contact_point_world_m"],
            "surface_outward_normal_world": kwargs["surface_outward_normal_world"],
            "approach_direction_world": [0, 0, -1],
            "press_direction_world": [0, 0, -1],
            "waypoint_variants": [{"variant_id": "tangent_0", "waypoints": []}],
        }

    def solver(**kwargs):
        calls["solver"] = kwargs
        return {
            "plan_id": "plan",
            "selected_arm": "left_arm",
            "selected_effector": "left_gripper",
            "selected_variant_id": "tangent_0",
            "selected_variant_metadata": {"tangent_axis_world": [1, 0, 0]},
            "joint_stages": [
                {"stage": name, "flange_pose_world": [index] * 7, "joints": [index] * 6}
                for index, name in enumerate(("approach", "contact", "press", "retreat"), start=1)
            ],
        }

    result = core.plan_reachable_linear_contact(
        pairs=[{"arm": "left_arm", "effector": "left_gripper"}],
        contact_point_world_m=[0, 0, 1],
        surface_outward_normal_world=[0, 0, 1],
        preferred_tangent_axis_world=[1, 0, 0],
        approach_distance_m=0.1,
        press_distance_m=0.03,
        observation_id="obs_current",
        observed_at_s=1,
        valid_for_s=5,
        position_uncertainty_m=0.01,
        waypoint_builder=builder,
        sequence_solver=solver,
    )
    assert calls["solver"]["pairs"][0]["arm"] == "left_arm"
    assert calls["solver"]["pose_sequence_variants"][0]["variant_id"] == "tangent_0"
    assert result["selected_arm"] == "left_arm"
    assert result["press_joints"] == [3] * 6
    assert result["execution_order"] == [
        "approach_joints", "contact_joints", "press_joints", "retreat_joints"
    ]
    assert result["reachability_solver"] == "solve_reachable_pose_sequence"
    assert result["contact_model"]["physical_contact_verified"] is None
    assert "no physical finger/pad" in result["warning"]
