"""Select a manipulator and solve chained IK for complete TCP-pose sequences."""

from __future__ import annotations

import math
import uuid
from typing import Any, Callable

import numpy as np

from kinex import device
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, mount_to_rt, rt_to_pose, xyzq_to_rt


class StageSolveError(ValueError):
    """Preserve the first failed stage for structured candidate diagnostics."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _flat_pose(rt: tuple[Any, Any]) -> list[float]:
    value = rt_to_pose(rt)
    return [*[float(x) for x in value["translation"]], *[float(x) for x in value["rotation"]]]


def _validated_pose(value: Any, label: str) -> list[float]:
    pose = np.asarray(value, dtype=float)
    if pose.shape != (7,) or not np.all(np.isfinite(pose)):
        raise ValueError(f"{label} must contain seven finite [x,y,z,qx,qy,qz,qw] numbers")
    quaternion_norm = float(np.linalg.norm(pose[3:]))
    if quaternion_norm < 1e-8:
        raise ValueError(f"{label} quaternion has zero length")
    pose[3:] /= quaternion_norm
    return [float(item) for item in pose]


def _tcp_in_flange(effector_profile: dict[str, Any], arm: str) -> tuple[Any, Any]:
    mount = effector_profile.get("extrinsics", {}).get("mount")
    if not isinstance(mount, dict) or mount.get("parent") != arm:
        raise ValueError(f"effector must declare an extrinsics.mount on arm {arm!r}")
    tcp = effector_profile.get("intrinsics", {}).get("frames", {}).get("tcp")
    if not isinstance(tcp, dict):
        raise ValueError("effector must declare intrinsics.frames.tcp")
    return compose_rt(mount_to_rt(mount), xyzq_to_rt([*tcp["translation_m"], *tcp["rotation_xyzw"]]))


def _base_distance_xy(pair: dict[str, Any], point: list[float]) -> float:
    translation = pair["arm_profile"].get("extrinsics", {}).get("mount", {}).get("translation_m")
    if not isinstance(translation, list) or len(translation) != 3:
        return math.inf
    return math.hypot(float(translation[0]) - point[0], float(translation[1]) - point[1])


def _validate_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not variants:
        raise ValueError("pose_sequence_variants must contain at least one variant")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for variant_index, variant in enumerate(variants):
        variant_id = variant.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id.strip() or variant_id in seen_ids:
            raise ValueError("every variant_id must be unique and non-empty")
        seen_ids.add(variant_id)
        waypoints = variant.get("waypoints")
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError(f"variant {variant_id!r} must contain waypoints")
        seen_stages: set[str] = set()
        normalized_waypoints = []
        for waypoint_index, waypoint in enumerate(waypoints):
            stage = waypoint.get("stage")
            if not isinstance(stage, str) or not stage.strip() or stage in seen_stages:
                raise ValueError(f"variant {variant_id!r} stages must be unique non-empty strings")
            seen_stages.add(stage)
            normalized_waypoints.append({
                "stage": stage,
                "tcp_pose_world": _validated_pose(
                    waypoint.get("tcp_pose_world"),
                    f"pose_sequence_variants[{variant_index}].waypoints[{waypoint_index}].tcp_pose_world",
                ),
            })
        normalized.append({
            "variant_id": variant_id,
            "metadata": dict(variant.get("metadata") or {}),
            "waypoints": normalized_waypoints,
        })
    return normalized


def solve_reachable_pose_sequence(
    *,
    pairs: list[dict[str, Any]],
    pose_sequence_variants: list[dict[str, Any]],
    based_on: list[str],
    observed_at_s: float,
    expires_at_s: float,
    position_uncertainty_m: float,
    device_call: Callable[..., dict[str, Any]] = device,
    frame_pose_call: Callable[..., dict[str, Any]] = frame_pose,
) -> dict[str, Any]:
    """Return the first pair/variant whose entire ordered sequence has chained IK."""
    if not pairs:
        raise ValueError("arm_effector_pairs must contain at least one pair")
    if not based_on or any(not isinstance(item, str) or not item.strip() for item in based_on):
        raise ValueError("based_on must contain non-empty observation IDs")
    if expires_at_s <= observed_at_s:
        raise ValueError("expires_at_s must be greater than observed_at_s")
    if not (0.0 <= position_uncertainty_m <= 0.05):
        raise ValueError("position_uncertainty_m must be in [0, 0.05]")
    variants = _validate_variants(pose_sequence_variants)
    first_point = variants[0]["waypoints"][0]["tcp_pose_world"][:3]
    ranked = sorted(pairs, key=lambda pair: _base_distance_xy(pair, first_point))
    failures: list[dict[str, Any]] = []

    for pair in ranked:
        arm = pair["arm"]
        effector = pair["effector"]
        if pair["arm_profile"].get("type") != "joint":
            failures.append({
                "arm": arm,
                "effector": effector,
                "variant_id": None,
                "failed_stage": "profile_validation",
                "reason": f"arm {arm!r} must be a joint device",
            })
            continue
        try:
            tcp_to_flange = invert_rt(_tcp_in_flange(pair["effector_profile"], arm))
            world_to_arm = xyzq_to_rt([
                *frame_pose_call("world", arm)["translation"],
                *frame_pose_call("world", arm)["rotation"],
            ])
            start = [float(value) for value in device_call(arm, "read")["positions"]]
        except Exception as exc:
            failures.append({
                "arm": arm,
                "effector": effector,
                "variant_id": None,
                "failed_stage": "profile_or_state",
                "reason": str(exc),
            })
            continue

        for variant in variants:
            seed = start
            solved_stages: list[dict[str, Any]] = []
            try:
                for waypoint in variant["waypoints"]:
                    stage = waypoint["stage"]
                    try:
                        world_tcp = xyzq_to_rt(waypoint["tcp_pose_world"])
                        world_flange = compose_rt(world_tcp, tcp_to_flange)
                        arm_flange = compose_rt(world_to_arm, world_flange)
                        result = device_call(arm, "ik", {"pose": _flat_pose(arm_flange), "seed": seed})
                        joints = result.get("joints")
                        if not isinstance(joints, list):
                            raise ValueError("IK returned no joints")
                        seed = [float(value) for value in joints]
                        solved_stages.append({
                            "stage": stage,
                            "tcp_pose_world": [round(value, 7) for value in waypoint["tcp_pose_world"]],
                            "flange_pose_world": [round(value, 7) for value in _flat_pose(world_flange)],
                            "joints": [round(value, 7) for value in seed],
                        })
                    except Exception as exc:
                        raise StageSolveError(stage, str(exc)) from exc
            except StageSolveError as exc:
                failures.append({
                    "arm": arm,
                    "effector": effector,
                    "variant_id": variant["variant_id"],
                    "failed_stage": exc.stage,
                    "reason": str(exc),
                })
                continue

            return {
                "plan_id": f"reachable_pose_sequence_{uuid.uuid4().hex[:12]}",
                "plan_valid": True,
                "frame": "world",
                "based_on": list(based_on),
                "observed_at_s": float(observed_at_s),
                "expires_at_s": float(expires_at_s),
                "position_uncertainty_m": float(position_uncertainty_m),
                "selected_arm": arm,
                "selected_effector": effector,
                "selected_variant_id": variant["variant_id"],
                "selected_variant_metadata": variant["metadata"],
                "joint_stages": solved_stages,
                "joint_targets_by_stage": {item["stage"]: item["joints"] for item in solved_stages},
                "execution_order": [item["stage"] for item in solved_stages],
                "candidate_order": [
                    {"arm": item["arm"], "effector": item["effector"]} for item in ranked
                ],
                "candidates_tested": len(failures) + 1,
                "candidate_failures": failures,
                "warning": "Discrete chained IK is verified; continuous collision, dynamics, and task effect require separate validation.",
            }

    raise ValueError(
        "no arm/effector and pose-sequence variant has complete chained IK: "
        f"{failures}"
    )
