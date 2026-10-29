"""Tests for generic complete pose-sequence reachability selection."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent


def load_core():
    kinex = types.ModuleType("kinex")
    kinex.device = lambda *args, **kwargs: {}
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
    geometry.mount_to_rt = lambda value: (np.eye(3).tolist(), list(value.get("translation_m", [0, 0, 0])))
    geometry.xyzq_to_rt = lambda value: (np.eye(3).tolist(), list(value[:3]))
    geometry.rt_to_pose = lambda value: {"translation": value[1], "rotation": [0, 0, 0, 1]}
    sys.modules.update({"kinex": kinex, "kinex.frames": frames, "kinex.geometry": geometry})
    spec = importlib.util.spec_from_file_location("reachable_pose_sequence_core", HERE / "core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def pair(name: str, x: float):
    return {
        "arm": f"{name}_arm",
        "effector": f"{name}_gripper",
        "arm_profile": {"type": "joint", "extrinsics": {"mount": {"translation_m": [x, 0, 0]}}},
        "effector_profile": {
            "extrinsics": {"mount": {"parent": f"{name}_arm", "translation_m": [0, 0, 0]}},
            "intrinsics": {"frames": {"tcp": {"translation_m": [0, 0, 0], "rotation_xyzw": [0, 0, 0, 1]}}},
        },
    }


def variants():
    return [
        {
            "variant_id": "a",
            "metadata": {"yaw": 0},
            "waypoints": [
                {"stage": "approach", "tcp_pose_world": [-0.2, 0, 1, 0, 0, 0, 1]},
                {"stage": "action", "tcp_pose_world": [-0.2, 0, 0.9, 0, 0, 0, 1]},
                {"stage": "retreat", "tcp_pose_world": [-0.2, 0, 1, 0, 0, 0, 1]},
            ],
        },
        {
            "variant_id": "b",
            "metadata": {"yaw": 90},
            "waypoints": [
                {"stage": "approach", "tcp_pose_world": [-0.2, 0, 1, 0, 0, 0, 1]},
                {"stage": "action", "tcp_pose_world": [-0.2, 0, 0.9, 0, 0, 0, 1]},
                {"stage": "retreat", "tcp_pose_world": [-0.2, 0, 1, 0, 0, 0, 1]},
            ],
        },
    ]


def test_rejects_partial_sequences_and_switches_arm():
    core = load_core()
    ik_counts = {"left_arm": 0, "right_arm": 0}

    def device_call(name, action, values=None):
        if action == "read":
            return {"positions": [0.0] * 6}
        ik_counts[name] += 1
        if name == "left_arm" and abs(float(values["pose"][2]) - 0.9) < 1e-9:
            raise ValueError("middle stage IK failed")
        return {"joints": [float(ik_counts[name])] * 6}

    result = core.solve_reachable_pose_sequence(
        pairs=[pair("right", 0.3), pair("left", -0.3)],
        pose_sequence_variants=variants(),
        based_on=["obs_current"],
        observed_at_s=1,
        expires_at_s=6,
        position_uncertainty_m=0.01,
        device_call=device_call,
        frame_pose_call=lambda parent, child: {"translation": [0, 0, 0], "rotation": [0, 0, 0, 1]},
    )
    assert result["candidate_order"][0]["arm"] == "left_arm"
    assert result["selected_arm"] == "right_arm"
    assert result["execution_order"] == ["approach", "action", "retreat"]
    assert result["joint_stages"][1]["joints"] == [2.0] * 6
    assert all(item["failed_stage"] == "action" for item in result["candidate_failures"])


def test_validates_complete_contract_without_motion():
    core = load_core()
    common = dict(
        pairs=[pair("left", -0.3)],
        pose_sequence_variants=variants(),
        based_on=["obs"],
        observed_at_s=1,
        expires_at_s=6,
        position_uncertainty_m=0.01,
    )
    for patch in (
        {"pairs": []},
        {"based_on": []},
        {"expires_at_s": 1},
        {"pose_sequence_variants": []},
    ):
        try:
            core.solve_reachable_pose_sequence(**{**common, **patch})
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {patch}")
