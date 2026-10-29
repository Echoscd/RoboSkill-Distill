"""Fast contract tests for the generic linear contact planner."""

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
    spec = importlib.util.spec_from_file_location("linear_contact_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_plan_contract_and_geometry():
    core = load_core()
    seen = []
    core._tcp_in_flange = lambda profile, arm: (np.eye(3).tolist(), [0, 0, 0])

    def fake_ik(arm, world_flange, world_to_arm, seed):
        seen.append(list(world_flange[1]))
        return [float(len(seen))] * 6

    core._ik = fake_ik
    result = core.plan_linear_contact(
        arm="arm",
        effector="gripper",
        arm_profile={"type": "joint"},
        effector_profile={},
        contact_point_world_m=[0.2, -0.1, 1.0],
        surface_outward_normal_world=[0, 0, 2],
        tangent_axis_world=[1, 0, 0],
        approach_distance_m=0.10,
        press_distance_m=0.03,
        observation_id="obs_7",
        observed_at_s=12.0,
        valid_for_s=5.0,
        position_uncertainty_m=0.004,
    )
    assert seen == [
        [0.2, -0.1, 1.1],
        [0.2, -0.1, 1.0],
        [0.2, -0.1, 0.97],
        [0.2, -0.1, 1.1],
    ]
    assert result["based_on"] == ["obs_7"]
    assert result["expires_at_s"] == 17.0
    assert result["position_uncertainty_m"] == 0.004
    assert result["surface_outward_normal_world"] == [0.0, 0.0, 1.0]
    assert result["approach_direction_world"] == [0.0, 0.0, -1.0]
    assert result["press_direction_world"] == [0.0, 0.0, -1.0]
    assert result["execution_order"] == [
        "approach_joints", "contact_joints", "press_joints", "retreat_joints"
    ]
    assert result["press_joints"] == [3.0] * 6


def test_rejects_degenerate_contact_contracts():
    core = load_core()
    common = dict(
        arm="arm", effector="gripper", arm_profile={"type": "joint"}, effector_profile={},
        contact_point_world_m=[0, 0, 1], surface_outward_normal_world=[0, 0, 1],
        tangent_axis_world=[1, 0, 0], approach_distance_m=0.1, press_distance_m=0.03,
        observation_id="obs", observed_at_s=1, valid_for_s=2, position_uncertainty_m=0.01,
    )
    for patch in (
        {"surface_outward_normal_world": [0, 0, 0]},
        {"tangent_axis_world": [0, 0, 1]},
        {"approach_distance_m": 0.02, "press_distance_m": 0.03},
        {"observation_id": ""},
        {"position_uncertainty_m": 0.2},
    ):
        values = {**common, **patch}
        try:
            core.plan_linear_contact(**values)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {patch}")
