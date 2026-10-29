"""Profile-aware placement planning with bounded top-down wrist-yaw search."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from kinex import device
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, xyzq_to_rt


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load toolbox component {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
GRASP = _load_module(
    "kinex_toolbox_top_down_grasp_for_place",
    ROOT / "plan_top_down_parallel_grasp" / "core.py",
)


def plan_top_down_place(
    *,
    arm: str,
    gripper: str,
    arm_profile: dict[str, Any],
    gripper_profile: dict[str, Any],
    target_object_center_world_m: list[float],
    preplace_distance_m: float = 0.08,
    retreat_distance_m: float = 0.08,
) -> dict[str, Any]:
    """Plan pre-place, release, and retreat from the live top-down TCP rotation."""
    if arm_profile.get("type") != "joint":
        raise ValueError(f'arm "{arm}" must be a joint device')
    contract = GRASP.gripper_contract(gripper_profile, arm)
    target = np.asarray(target_object_center_world_m, dtype=float)
    if target.shape != (3,) or not np.all(np.isfinite(target)):
        raise ValueError("target_object_center_world_m must contain three finite numbers")

    current_tcp_pose = frame_pose(f"{gripper}:tcp", "world")
    current_tcp = xyzq_to_rt([
        *current_tcp_pose["translation"],
        *current_tcp_pose["rotation"],
    ])
    gripper_pose = frame_pose(gripper, "world")
    world_gripper = xyzq_to_rt([
        *gripper_pose["translation"],
        *gripper_pose["rotation"],
    ])
    local_approach = np.asarray(
        contract["geometry"]["approach_axis_local"], dtype=float
    )
    approach_world = np.asarray(world_gripper[0], dtype=float) @ local_approach
    approach_world = approach_world / np.linalg.norm(approach_world)
    downward_alignment = float(np.dot(approach_world, np.array([0.0, 0.0, -1.0])))
    if downward_alignment < 0.80:
        raise ValueError(
            "live gripper is not in a top-down orientation; use a reorientation planner first"
        )

    flange_to_tcp = GRASP._tcp_in_flange(gripper_profile, arm)
    tcp_to_flange = invert_rt(flange_to_tcp)
    world_to_arm = xyzq_to_rt([
        *frame_pose("world", arm)["translation"],
        *frame_pose("world", arm)["rotation"],
    ])
    start = [float(x) for x in device(arm, "read")["positions"]]

    selected = None
    failures: list[dict[str, Any]] = []
    current_rotation = np.asarray(current_tcp[0], dtype=float)
    for yaw_offset_deg in (0.0, 45.0, -45.0, 90.0, -90.0, 180.0):
        yaw = math.radians(yaw_offset_deg)
        rotation_z = np.array([
            [math.cos(yaw), -math.sin(yaw), 0.0],
            [math.sin(yaw), math.cos(yaw), 0.0],
            [0.0, 0.0, 1.0],
        ])
        candidate_rotation = rotation_z @ current_rotation
        candidate_approach = rotation_z @ approach_world
        place_tcp = (candidate_rotation.tolist(), target.tolist())
        preplace_tcp = (
            candidate_rotation.tolist(),
            (target - candidate_approach * float(preplace_distance_m)).tolist(),
        )
        retreat_tcp = (
            candidate_rotation.tolist(),
            (target - candidate_approach * float(retreat_distance_m)).tolist(),
        )
        preplace_flange = compose_rt(preplace_tcp, tcp_to_flange)
        place_flange = compose_rt(place_tcp, tcp_to_flange)
        retreat_flange = compose_rt(retreat_tcp, tcp_to_flange)
        try:
            preplace_joints = GRASP._ik(arm, preplace_flange, world_to_arm, start)
            place_joints = GRASP._ik(arm, place_flange, world_to_arm, preplace_joints)
            retreat_joints = GRASP._ik(arm, retreat_flange, world_to_arm, place_joints)
        except Exception as exc:
            failures.append({
                "yaw_offset_deg": yaw_offset_deg,
                "reason": str(exc),
            })
            continue
        selected = {
            "yaw_offset_deg": yaw_offset_deg,
            "rotation": candidate_rotation,
            "approach": candidate_approach,
            "preplace_flange": preplace_flange,
            "place_flange": place_flange,
            "retreat_flange": retreat_flange,
            "preplace_joints": preplace_joints,
            "place_joints": place_joints,
            "retreat_joints": retreat_joints,
        }
        break
    if selected is None:
        raise ValueError(f"no IK-feasible top-down placement candidate: {failures}")

    return {
        "plan_valid": True,
        "frame": "world",
        "arm": arm,
        "gripper": gripper,
        "target_object_center_world_m": [round(float(x), 7) for x in target],
        "starting_tcp_rotation_xyzw": [round(float(x), 7) for x in current_tcp_pose["rotation"]],
        "selected_yaw_offset_deg": selected["yaw_offset_deg"],
        "approach_axis_world": [round(float(x), 7) for x in selected["approach"]],
        "downward_alignment": round(downward_alignment, 7),
        "preplace_flange_pose_world": [
            round(x, 7) for x in GRASP._flat_pose(selected["preplace_flange"])
        ],
        "place_flange_pose_world": [
            round(x, 7) for x in GRASP._flat_pose(selected["place_flange"])
        ],
        "retreat_flange_pose_world": [
            round(x, 7) for x in GRASP._flat_pose(selected["retreat_flange"])
        ],
        "preplace_joints": [round(x, 7) for x in selected["preplace_joints"]],
        "place_joints": [round(x, 7) for x in selected["place_joints"]],
        "retreat_joints": [round(x, 7) for x in selected["retreat_joints"]],
        "candidate_failures": failures,
        "gripper_hold_target": contract["control"]["close_target"],
        "gripper_release_target": contract["control"]["open_target"],
        "gripper_control_bounds": contract["control"]["bounds"],
        "tcp_offset_flange_m": [round(float(x), 7) for x in flange_to_tcp[1]],
        "execution_order": [
            "confirm the object remains held before moving",
            "servo preplace_flange_pose_world with frame=world",
            "servo place_flange_pose_world with frame=world at low speed",
            "open gripper to gripper_release_target",
            "servo retreat_flange_pose_world with frame=world at low speed",
            "re-observe the support and released object",
        ],
        "warning": (
            "This assumes the held object's center coincides with the TCP because it was "
            "grasped through its estimated center. A nonzero selected_yaw_offset_deg rotates "
            "the held object about vertical for reachability. Continuous collision safety and "
            "release stability are not checked."
        ),
    }
