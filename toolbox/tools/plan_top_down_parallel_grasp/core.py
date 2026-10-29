"""Object-agnostic, profile-aware top-down parallel-jaw grasp planning."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from kinex import device
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, mount_to_rt, rt_to_pose, xyzq_to_rt

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "read_gripper_contract"
sys.path.insert(0, str(CONTRACT_DIR))
from gripper_contract import gripper_contract  # noqa: E402


def _normalize(vector: np.ndarray, label: str) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError(f"{label} has zero length")
    return vector / norm


def _orthonormal_basis(first: np.ndarray, second: np.ndarray, label: str) -> np.ndarray:
    x = _normalize(first, f"{label} first axis")
    y = second - x * float(np.dot(second, x))
    y = _normalize(y, f"{label} second axis")
    z = _normalize(np.cross(x, y), f"{label} cross axis")
    return np.column_stack((x, y, z))


def _flat_pose(rt: tuple[Any, Any]) -> list[float]:
    pose = rt_to_pose(rt)
    return [
        *[float(x) for x in pose["translation"]],
        *[float(x) for x in pose["rotation"]],
    ]


def _tcp_in_flange(gripper_profile: dict[str, Any], arm: str) -> tuple[Any, Any]:
    mount = gripper_profile["extrinsics"]["mount"]
    if mount.get("parent") != arm:
        raise ValueError(f'gripper is mounted to {mount.get("parent")!r}, not arm {arm!r}')
    tcp = gripper_profile["intrinsics"]["frames"]["tcp"]
    return compose_rt(
        mount_to_rt(mount),
        xyzq_to_rt([*tcp["translation_m"], *tcp["rotation_xyzw"]]),
    )


def _ik(
    arm: str,
    world_flange_rt: tuple[Any, Any],
    world_to_arm_rt: tuple[Any, Any],
    seed: list[float],
) -> list[float]:
    arm_flange_rt = compose_rt(world_to_arm_rt, world_flange_rt)
    result = device(arm, "ik", {"pose": _flat_pose(arm_flange_rt), "seed": seed})
    joints = result.get("joints")
    if not isinstance(joints, list):
        raise ValueError("IK returned no joints")
    return [float(x) for x in joints]


def _rotate_2d(vector: np.ndarray, radians: float) -> np.ndarray:
    c, s = math.cos(radians), math.sin(radians)
    return np.array([c * vector[0] - s * vector[1], s * vector[0] + c * vector[1]])


def plan_top_down_grasp(
    *,
    arm: str,
    gripper: str,
    arm_profile: dict[str, Any],
    gripper_profile: dict[str, Any],
    center_world_m: list[float],
    major_axis_world_xy: list[float],
    major_extent_m: float,
    minor_extent_m: float,
    pregrasp_distance_m: float = 0.10,
    test_lift_m: float = 0.06,
    clearance_m: float = 0.01,
) -> dict[str, Any]:
    """Return the first IK-feasible top-down plan from a deterministic yaw set."""
    if arm_profile.get("type") != "joint":
        raise ValueError(f'arm "{arm}" must be a joint device')
    contract = gripper_contract(gripper_profile, arm)
    center = np.asarray(center_world_m, dtype=float)
    if center.shape != (3,) or not np.all(np.isfinite(center)):
        raise ValueError("center_world_m must contain three finite numbers")
    major = _normalize(np.asarray(major_axis_world_xy, dtype=float), "major axis")
    if major.shape != (2,):
        raise ValueError("major_axis_world_xy must contain two numbers")
    minor = np.array([-major[1], major[0]])
    major_extent, minor_extent = float(major_extent_m), float(minor_extent_m)
    if major_extent <= 0 or minor_extent <= 0:
        raise ValueError("footprint extents must be positive")
    if major_extent < minor_extent:
        major, minor = minor, major
        major_extent, minor_extent = minor_extent, major_extent

    max_aperture = float(contract["aperture_m"]["max"])
    flange_to_tcp = _tcp_in_flange(gripper_profile, arm)
    tcp_to_flange = invert_rt(flange_to_tcp)
    tcp_profile = gripper_profile["intrinsics"]["frames"]["tcp"]
    mount_to_tcp = xyzq_to_rt([
        *tcp_profile["translation_m"],
        *tcp_profile["rotation_xyzw"],
    ])
    local_approach = np.asarray(contract["geometry"]["approach_axis_local"], dtype=float)
    local_closing = np.asarray(contract["geometry"]["closing_axis_local"], dtype=float)
    local_basis = _orthonormal_basis(local_approach, local_closing, "gripper")

    world_to_arm = xyzq_to_rt([
        *frame_pose("world", arm)["translation"],
        *frame_pose("world", arm)["rotation"],
    ])
    start = [float(x) for x in device(arm, "read")["positions"]]
    approach_world = np.array([0.0, 0.0, -1.0])
    failures: list[dict[str, Any]] = []
    candidates_tested = 0

    # Prefer closing across the minor footprint, then explore nearby yaw angles.
    for yaw_deg in (0.0, 45.0, -45.0, 90.0):
        base = _rotate_2d(minor, math.radians(yaw_deg))
        for sign in (1.0, -1.0):
            closing_xy = base * sign
            projected_width = (
                abs(float(np.dot(closing_xy, major))) * major_extent
                + abs(float(np.dot(closing_xy, minor))) * minor_extent
            )
            required_aperture = projected_width + float(clearance_m)
            candidates_tested += 1
            if required_aperture > max_aperture:
                failures.append({
                    "yaw_offset_deg": yaw_deg,
                    "closing_sign": int(sign),
                    "reason": "required aperture exceeds profile maximum",
                    "required_aperture_m": round(required_aperture, 6),
                    "max_aperture_m": round(max_aperture, 6),
                })
                continue

            closing_world = np.array([closing_xy[0], closing_xy[1], 0.0])
            world_basis = _orthonormal_basis(approach_world, closing_world, "world target")
            world_mount_rotation = world_basis @ local_basis.T
            mount_tcp_rotation = np.asarray(mount_to_tcp[0], dtype=float)
            world_tcp_rotation = world_mount_rotation @ mount_tcp_rotation
            grasp_tcp = (world_tcp_rotation.tolist(), center.tolist())
            pre_tcp = (
                world_tcp_rotation.tolist(),
                (center - approach_world * float(pregrasp_distance_m)).tolist(),
            )
            lift_tcp = (
                world_tcp_rotation.tolist(),
                (center + np.array([0.0, 0.0, float(test_lift_m)])).tolist(),
            )
            pre_flange = compose_rt(pre_tcp, tcp_to_flange)
            grasp_flange = compose_rt(grasp_tcp, tcp_to_flange)
            lift_flange = compose_rt(lift_tcp, tcp_to_flange)
            try:
                pre_joints = _ik(arm, pre_flange, world_to_arm, start)
                grasp_joints = _ik(arm, grasp_flange, world_to_arm, pre_joints)
                lift_joints = _ik(arm, lift_flange, world_to_arm, grasp_joints)
            except Exception as exc:
                failures.append({
                    "yaw_offset_deg": yaw_deg,
                    "closing_sign": int(sign),
                    "reason": f"IK failed: {exc}",
                })
                continue

            return {
                "plan_valid": True,
                "frame": "world",
                "arm": arm,
                "gripper": gripper,
                "object_center_world_m": [round(float(x), 7) for x in center],
                "selected_closing_axis_world_xy": [round(float(x), 7) for x in closing_xy],
                "selected_yaw_offset_deg": yaw_deg,
                "estimated_width_along_closing_axis_m": round(projected_width, 7),
                "required_open_aperture_m": round(required_aperture, 7),
                "pregrasp_flange_pose_world": [round(x, 7) for x in _flat_pose(pre_flange)],
                "grasp_flange_pose_world": [round(x, 7) for x in _flat_pose(grasp_flange)],
                "test_lift_flange_pose_world": [round(x, 7) for x in _flat_pose(lift_flange)],
                "pregrasp_joints": [round(x, 7) for x in pre_joints],
                "grasp_joints": [round(x, 7) for x in grasp_joints],
                "test_lift_joints": [round(x, 7) for x in lift_joints],
                "gripper_open_target": contract["control"]["open_target"],
                "gripper_close_target": contract["control"]["close_target"],
                "gripper_control_bounds": contract["control"]["bounds"],
                "tcp_offset_flange_m": [round(float(x), 7) for x in flange_to_tcp[1]],
                "candidates_tested": candidates_tested,
                "candidate_failures": failures,
                "execution_order": [
                    "open gripper to gripper_open_target",
                    "servo pregrasp_flange_pose_world with frame=world",
                    "servo grasp_flange_pose_world with frame=world at low speed",
                    "close gripper to gripper_close_target",
                    "servo test_lift_flange_pose_world with frame=world at low speed",
                    "re-observe and verify before placement",
                ],
                "warning": (
                    "The returned poses target the arm flange and compensate the TCP offset. "
                    "IK reachability is checked, but continuous-path collision safety is not."
                ),
            }
    raise ValueError(f"no profile-compatible IK-feasible top-down grasp candidate: {failures}")
