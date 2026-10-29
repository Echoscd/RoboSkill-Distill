#!/usr/bin/env python3
"""IK-check a safe translation of a bottle that is already held at the TCP."""

from __future__ import annotations

import math

from kinex import args, device, fail, finish, profile
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, mount_to_rt, rt_to_pose, xyzq_to_rt


def flat_pose(rt):
    value = rt_to_pose(rt)
    return [*[float(x) for x in value["translation"]], *[float(x) for x in value["rotation"]]]


def tcp_in_flange(gripper_profile, arm):
    mount = gripper_profile["extrinsics"]["mount"]
    if mount.get("parent") != arm:
        raise ValueError(f'gripper is mounted to {mount.get("parent")!r}, not arm {arm!r}')
    tcp = gripper_profile["intrinsics"]["frames"]["tcp"]
    return compose_rt(
        mount_to_rt(mount),
        xyzq_to_rt([*tcp["translation_m"], *tcp["rotation_xyzw"]]),
    )


def ik(arm, world_flange_rt, world_to_arm_rt, seed):
    arm_flange_rt = compose_rt(world_to_arm_rt, world_flange_rt)
    result = device(arm, "ik", {"pose": flat_pose(arm_flange_rt), "seed": seed})
    joints = result.get("joints")
    if not isinstance(joints, list):
        raise ValueError("IK returned no joints")
    return [float(x) for x in joints]


def main():
    values = args()
    arm, gripper = values["arm"], values["gripper"]
    try:
        target = [float(x) for x in values["target_center_world_m"]]
        if len(target) != 3 or not all(math.isfinite(x) for x in target):
            raise ValueError("target_center_world_m must contain three finite numbers")
        if not (-0.55 <= target[0] <= 0.05 and -0.40 <= target[1] <= 0.20 and 0.85 <= target[2] <= 1.15):
            raise ValueError("target center is outside the conservative left-arm transfer region")

        arm_state = device(arm, "read")
        start = [float(x) for x in arm_state["positions"]]
        grip_state = device(gripper, "read")
        aperture = grip_state.get("aperture_m")
        if not isinstance(aperture, (int, float)) or not math.isfinite(aperture):
            raise ValueError("gripper did not report a finite aperture")
        if float(aperture) < 0.008:
            raise ValueError("gripper is fully closed; there is no evidence of a held object")

        tcp = frame_pose(f"{gripper}:tcp", "world", readings={arm: arm_state})
        current_tcp = [*tcp["translation"], *tcp["rotation"]]
        current_rotation = [float(x) for x in tcp["rotation"]]
        clearance = float(values.get("clearance_m", 0.06))
        safe_z = max(float(tcp["translation"][2]), target[2]) + clearance

        flange_to_tcp = tcp_in_flange(profile(gripper), arm)
        tcp_to_flange = invert_rt(flange_to_tcp)
        world_to_arm = xyzq_to_rt([
            *frame_pose("world", arm)["translation"],
            *frame_pose("world", arm)["rotation"],
        ])
        high_tcp = xyzq_to_rt([
            float(tcp["translation"][0]), float(tcp["translation"][1]), safe_z,
            *current_rotation,
        ])
        target_tcp = xyzq_to_rt([*target, *current_rotation])
        high_flange = compose_rt(high_tcp, tcp_to_flange)
        target_flange = compose_rt(target_tcp, tcp_to_flange)
        high_joints = ik(arm, high_flange, world_to_arm, start)
        target_joints = ik(arm, target_flange, world_to_arm, high_joints)

        finish({
            "plan_valid": True,
            "arm": arm,
            "gripper": gripper,
            "assumption": "verified object center remains coincident with the live gripper TCP",
            "gripper_aperture_m": round(float(aperture), 6),
            "current_tcp_pose_world": [round(float(x), 7) for x in current_tcp],
            "target_center_world_m": [round(x, 6) for x in target],
            "safe_height_world_m": round(safe_z, 6),
            "high_flange_pose_world": [round(x, 7) for x in flat_pose(high_flange)],
            "target_flange_pose_world": [round(x, 7) for x in flat_pose(target_flange)],
            "high_joints": [round(x, 7) for x in high_joints],
            "target_joints": [round(x, 7) for x in target_joints],
            "execution_order": [
                "keep gripper closed",
                "servo high_flange_pose_world at low speed",
                "servo target_flange_pose_world at low speed",
                "keep gripper closed and stop",
            ],
        })
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
