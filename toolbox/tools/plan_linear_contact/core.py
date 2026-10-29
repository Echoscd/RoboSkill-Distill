"""Generic, profile-aware planning for short linear contact motions."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np

from kinex import device
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, mount_to_rt, rt_to_pose, xyzq_to_rt


def _unit(value: list[float], label: str) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{label} must contain three finite numbers")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError(f"{label} has zero length")
    return vector / norm


def _flat_pose(rt: tuple[Any, Any]) -> list[float]:
    value = rt_to_pose(rt)
    return [*[float(x) for x in value["translation"]], *[float(x) for x in value["rotation"]]]


def _tcp_in_flange(effector_profile: dict[str, Any], arm: str) -> tuple[Any, Any]:
    mount = effector_profile.get("extrinsics", {}).get("mount")
    if not isinstance(mount, dict) or mount.get("parent") != arm:
        raise ValueError(f'effector must declare an extrinsics.mount on arm {arm!r}')
    tcp = effector_profile.get("intrinsics", {}).get("frames", {}).get("tcp")
    if not isinstance(tcp, dict):
        raise ValueError("effector must declare intrinsics.frames.tcp")
    return compose_rt(mount_to_rt(mount), xyzq_to_rt([*tcp["translation_m"], *tcp["rotation_xyzw"]]))


def _ik(arm: str, world_flange_rt: tuple[Any, Any], world_to_arm_rt: tuple[Any, Any], seed: list[float]) -> list[float]:
    arm_flange_rt = compose_rt(world_to_arm_rt, world_flange_rt)
    result = device(arm, "ik", {"pose": _flat_pose(arm_flange_rt), "seed": seed})
    joints = result.get("joints")
    if not isinstance(joints, list):
        raise ValueError("IK returned no joints")
    return [float(value) for value in joints]


def plan_linear_contact(
    *,
    arm: str,
    effector: str,
    arm_profile: dict[str, Any],
    effector_profile: dict[str, Any],
    contact_point_world_m: list[float],
    surface_outward_normal_world: list[float],
    tangent_axis_world: list[float],
    approach_distance_m: float,
    press_distance_m: float,
    observation_id: str,
    observed_at_s: float,
    valid_for_s: float,
    position_uncertainty_m: float,
) -> dict[str, Any]:
    if arm_profile.get("type") != "joint":
        raise ValueError(f'arm {arm!r} must be a joint device')
    if not observation_id.strip():
        raise ValueError("observation_id must not be blank")
    if not (0 <= position_uncertainty_m <= 0.05):
        raise ValueError("position_uncertainty_m must be in [0, 0.05]")
    if approach_distance_m <= press_distance_m:
        raise ValueError("approach_distance_m must exceed press_distance_m")

    contact = np.asarray(contact_point_world_m, dtype=float)
    if contact.shape != (3,) or not np.all(np.isfinite(contact)):
        raise ValueError("contact_point_world_m must contain three finite numbers")
    outward_normal = _unit(
        surface_outward_normal_world, "surface_outward_normal_world"
    )
    tangent = _unit(tangent_axis_world, "tangent_axis_world")
    tangent = tangent - outward_normal * float(np.dot(tangent, outward_normal))
    tangent = _unit(tangent.tolist(), "tangent axis projected onto contact plane")
    approach_direction = -outward_normal
    press_direction = -outward_normal
    approach_axis = approach_direction
    second = np.cross(approach_axis, tangent)
    world_tcp_rotation = np.column_stack((approach_axis, tangent, _unit(second.tolist(), "contact basis")))

    tcp_to_flange = invert_rt(_tcp_in_flange(effector_profile, arm))
    world_to_arm = xyzq_to_rt([
        *frame_pose("world", arm)["translation"],
        *frame_pose("world", arm)["rotation"],
    ])
    start = [float(value) for value in device(arm, "read")["positions"]]

    points = {
        "approach": contact + outward_normal * approach_distance_m,
        "contact": contact,
        "press": contact + press_direction * press_distance_m,
        "retreat": contact + outward_normal * approach_distance_m,
    }
    poses: dict[str, list[float]] = {}
    joints: dict[str, list[float]] = {}
    seed = start
    for stage, point in points.items():
        tcp = (world_tcp_rotation.tolist(), point.tolist())
        flange = compose_rt(tcp, tcp_to_flange)
        poses[stage] = [round(value, 7) for value in _flat_pose(flange)]
        seed = _ik(arm, flange, world_to_arm, seed)
        joints[stage] = [round(value, 7) for value in seed]

    return {
        "plan_id": f"linear_contact_{uuid.uuid4().hex[:12]}",
        "plan_valid": True,
        "frame": "world",
        "source_frame": "world",
        "target_frame": "world",
        "arm": arm,
        "effector": effector,
        "based_on": [observation_id],
        "observed_at_s": observed_at_s,
        "expires_at_s": observed_at_s + valid_for_s,
        "position_uncertainty_m": position_uncertainty_m,
        "contact_point_world_m": [round(float(value), 7) for value in contact],
        "surface_outward_normal_world": [
            round(float(value), 7) for value in outward_normal
        ],
        "approach_direction_world": [
            round(float(value), 7) for value in approach_direction
        ],
        "press_direction_world": [
            round(float(value), 7) for value in press_direction
        ],
        "approach_flange_pose_world": poses["approach"],
        "contact_flange_pose_world": poses["contact"],
        "press_flange_pose_world": poses["press"],
        "retreat_flange_pose_world": poses["retreat"],
        "approach_joints": joints["approach"],
        "contact_joints": joints["contact"],
        "press_joints": joints["press"],
        "retreat_joints": joints["retreat"],
        "execution_order": ["approach_joints", "contact_joints", "press_joints", "retreat_joints"],
        "warning": "Discrete IK is verified; continuous collision and force limits require separate validation.",
    }
