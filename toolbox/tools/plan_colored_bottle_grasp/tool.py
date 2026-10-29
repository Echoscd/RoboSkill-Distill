#!/usr/bin/env python3
"""Generate and IK-check a top-down bottle grasp while respecting the TCP offset."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

from kinex import args, device, fail, finish, profile
from kinex.frames import pose as frame_pose
from kinex.geometry import compose_rt, invert_rt, mat_to_quat, mount_to_rt, quat_to_mat, rt_to_pose, xyzq_to_rt

LOCATE_DIR = Path(__file__).resolve().parents[1] / "locate_colored_object_3d"
sys.path.insert(0, str(LOCATE_DIR))
from color_geometry import (  # noqa: E402
    _largest_component,
    _mask_for_color,
    _quaternion_matrix,
    locate_colored_object,
    project_endpoints_to_center_plane,
    visible_world_points,
)


def flat_pose(rt):
    value = rt_to_pose(rt)
    return [*[float(x) for x in value["translation"]], *[float(x) for x in value["rotation"]]]


def support_height(depth_raw, component, camera_profile):
    kernel_outer = np.ones((31, 31), np.uint8)
    kernel_inner = np.ones((7, 7), np.uint8)
    outer = cv2.dilate(component.astype(np.uint8), kernel_outer).astype(bool)
    inner = cv2.dilate(component.astype(np.uint8), kernel_inner).astype(bool)
    ring = outer & ~inner

    depth_profile = camera_profile["intrinsics"]["depth"]
    scale = float(depth_profile["scale_m_per_unit"])
    limits = depth_profile["valid_range_m"]
    valid = ring & (depth_raw != int(depth_profile["invalid_value"]))
    ys, xs = np.where(valid)
    depths = depth_raw[ys, xs].astype(float) * scale
    keep = (depths >= float(limits["min"])) & (depths <= float(limits["max"]))
    xs, ys, depths = xs[keep], ys[keep], depths[keep]
    if depths.size < 80:
        raise ValueError(f"only {depths.size} valid support-plane samples around the bottle")

    projection = camera_profile["intrinsics"]["color"]["projection"]
    camera_points = np.column_stack((
        (xs - float(projection["cx"])) * depths / float(projection["fx"]),
        (ys - float(projection["cy"])) * depths / float(projection["fy"]),
        depths,
    ))
    mount = camera_profile["extrinsics"]["mount"]
    rotation = _quaternion_matrix(mount["rotation_xyzw"])
    translation = np.asarray(mount["translation_m"], dtype=float)
    world_z = (camera_points @ rotation.T + translation)[:, 2]
    median = float(np.median(world_z))
    mad = float(np.median(np.abs(world_z - median)))
    tolerance = max(0.004, 3.0 * 1.4826 * mad)
    inliers = world_z[np.abs(world_z - median) <= tolerance]
    if inliers.size < 50:
        raise ValueError("support-plane estimate has too few inliers")
    return float(np.median(inliers)), int(inliers.size), mad


def tcp_in_flange(gripper_profile, arm):
    mount = gripper_profile["extrinsics"]["mount"]
    if mount.get("parent") != arm:
        raise ValueError(f'gripper is mounted to {mount.get("parent")!r}, not arm {arm!r}')
    tcp = gripper_profile["intrinsics"]["frames"]["tcp"]
    mount_rt = mount_to_rt(mount)
    tcp_rt = xyzq_to_rt([*tcp["translation_m"], *tcp["rotation_xyzw"]])
    return compose_rt(mount_rt, tcp_rt)


def desired_tcp_rt(point, bottle_axis_xy, flip):
    bottle = np.asarray([bottle_axis_xy[0], bottle_axis_xy[1], 0.0], dtype=float)
    bottle /= np.linalg.norm(bottle)
    closing = np.asarray([-bottle[1], bottle[0], 0.0], dtype=float) * float(flip)
    local_x = np.asarray([0.0, 0.0, -1.0])
    local_y = -closing  # profile closing axis is local -Y
    local_z = np.cross(local_x, local_y)
    rotation = np.column_stack((local_x, local_y, local_z))
    return rotation.tolist(), [float(x) for x in point]


def offset_tcp(rt, delta_world):
    rotation, translation = rt
    return rotation, [float(translation[i] + delta_world[i]) for i in range(3)]


def ik(arm, world_flange_rt, world_to_arm_rt, seed):
    arm_flange_rt = compose_rt(world_to_arm_rt, world_flange_rt)
    result = device(arm, "ik", {"pose": flat_pose(arm_flange_rt), "seed": seed})
    joints = result.get("joints")
    if not isinstance(joints, list):
        raise ValueError("IK returned no joints")
    return [float(x) for x in joints]


def main():
    values = args()
    camera, arm, gripper = values["camera"], values["arm"], values["gripper"]
    camera_profile, arm_profile, gripper_profile = profile(camera), profile(arm), profile(gripper)
    if camera_profile.get("type") != "rgbd":
        fail(f'camera "{camera}" must be RGB-D')
    if arm_profile.get("type") != "joint":
        fail(f'arm "{arm}" must be a joint device')
    if gripper_profile.get("type") != "gripper":
        fail(f'gripper "{gripper}" must be a gripper device')

    try:
        frame = device(camera, args={"output": "file"})
        color = cv2.imread(frame["file"], cv2.IMREAD_COLOR)
        depth = cv2.imread(frame["depth_file"], cv2.IMREAD_UNCHANGED)
        if color is None or depth is None:
            raise ValueError("camera returned unreadable RGB-D files")
        located, annotated = locate_colored_object(color, depth, camera_profile, values["color"])
        component, _, _ = _largest_component(_mask_for_color(color, values["color"]), 80)
        table_z, support_samples, support_mad = support_height(depth, component, camera_profile)

        # RGB-D sees the near/top surface, not the cylinder centerline.  Estimate
        # the top from a high depth-cloud quantile, then intersect the endpoint
        # camera rays with the resulting center plane.  Keeping the surface x/y
        # while merely replacing z biases this oblique view by more than 1 cm.
        object_world = visible_world_points(depth, component, camera_profile)
        visible_top_z = float(np.quantile(object_world[:, 2], 0.99))
        diameter = visible_top_z - table_z
        if not 0.02 <= diameter <= 0.12:
            raise ValueError(f"estimated bottle diameter {diameter:.4f} m is implausible")
        radius = diameter / 2.0
        center, end_a, end_b = project_endpoints_to_center_plane(
            located, table_z + radius, camera_profile
        )
        bottle_axis = end_b[:2] - end_a[:2]
        estimated_axis_length = float(np.linalg.norm(end_b - end_a))
        if estimated_axis_length < 0.04:
            raise ValueError("bottle axis estimate is too short")
        bottle_axis /= np.linalg.norm(bottle_axis)

        flange_to_tcp = tcp_in_flange(gripper_profile, arm)
        tcp_to_flange = invert_rt(flange_to_tcp)
        # pose(child, parent) returns the child frame expressed in parent, so
        # this is T_arm_world and directly converts world targets for arm IK.
        world_to_arm = xyzq_to_rt([
            *frame_pose("world", arm)["translation"],
            *frame_pose("world", arm)["rotation"],
        ])
        start = [float(x) for x in device(arm, "read")["positions"]]
        pregrasp_distance = float(values.get("pregrasp_distance_m", 0.10))
        test_lift = float(values.get("test_lift_m", 0.06))

        # Keep the gripper's local z axis directed from the wide body toward the
        # detected narrow/neck end.  The mirrored top-down wrist pose is also IK
        # feasible, but on ALOHA it presents the asymmetric wrist hardware first
        # and can sweep the bottle away before the fingers close.
        preferred_flip = -1 if located["narrow_end"] == "end_b" else 1
        failures = []
        selected = None
        for flip in (preferred_flip, -preferred_flip):
            rotation, translation = desired_tcp_rt(center, bottle_axis, flip)
            grasp_tcp = (rotation, translation)
            approach_world = np.asarray(rotation)[:, 0]
            pre_tcp = offset_tcp(grasp_tcp, -approach_world * pregrasp_distance)
            lift_tcp = offset_tcp(grasp_tcp, [0.0, 0.0, test_lift])
            pre_flange = compose_rt(pre_tcp, tcp_to_flange)
            grasp_flange = compose_rt(grasp_tcp, tcp_to_flange)
            lift_flange = compose_rt(lift_tcp, tcp_to_flange)
            try:
                pre_joints = ik(arm, pre_flange, world_to_arm, start)
                grasp_joints = ik(arm, grasp_flange, world_to_arm, pre_joints)
                lift_joints = ik(arm, lift_flange, world_to_arm, grasp_joints)
                selected = {
                    "orientation_variant": "narrow_end_forward" if flip == preferred_flip else "narrow_end_forward_fallback_mirror",
                    "pregrasp_flange_pose_world": [round(x, 7) for x in flat_pose(pre_flange)],
                    "grasp_flange_pose_world": [round(x, 7) for x in flat_pose(grasp_flange)],
                    "test_lift_flange_pose_world": [round(x, 7) for x in flat_pose(lift_flange)],
                    "pregrasp_joints": [round(x, 7) for x in pre_joints],
                    "grasp_joints": [round(x, 7) for x in grasp_joints],
                    "test_lift_joints": [round(x, 7) for x in lift_joints],
                }
                break
            except Exception as exc:  # candidate failure is part of the planner result
                failures.append({"flip": flip, "error": str(exc)})
        if selected is None:
            raise ValueError(f"no IK-feasible grasp candidate: {failures}")

        control = gripper_profile["intrinsics"]["control"]
        annotation = Path(frame["file"]).with_name(Path(frame["file"]).stem + "_grasp_plan.png")
        if not cv2.imwrite(str(annotation), annotated):
            raise ValueError("could not save grasp-plan annotation")
        result = {
            "plan_valid": True,
            "camera": camera,
            "arm": arm,
            "gripper": gripper,
            "frame": "world",
            "object": {
                "color": values["color"],
                "surface_point_world_m": located["center"]["world_xyz_m"],
                "estimated_center_world_m": [round(float(x), 6) for x in center],
                "center_method": "camera_ray_intersection_with_estimated_cylinder_center_plane",
                "silhouette_centroid_bias_m": round(float(np.linalg.norm(center[:2] - np.asarray(located["center"]["world_xyz_m"], dtype=float)[:2])), 6),
                "bottle_axis_world_xy": [round(float(x), 6) for x in bottle_axis],
                "estimated_axis_length_m": round(estimated_axis_length, 6),
                "support_z_world_m": round(table_z, 6),
                "visible_top_z_world_m": round(visible_top_z, 6),
                "top_quantile": 0.99,
                "estimated_diameter_m": round(diameter, 6),
                "support_samples": support_samples,
                "support_mad_m": round(support_mad, 6),
            },
            "tcp_offset_flange_m": [round(float(x), 6) for x in flange_to_tcp[1]],
            **selected,
            "gripper_open_target": float(control["open_target"]),
            "gripper_close_target": float(control["close_target"]),
            "execution_order": [
                "open gripper to gripper_open_target",
                "servo pregrasp_flange_pose_world with frame=world",
                "servo grasp_flange_pose_world with frame=world at low speed",
                "close gripper to gripper_close_target",
                "servo test_lift_flange_pose_world with frame=world at low speed",
                "re-observe before any reorientation or placement",
            ],
            "warning": "All poses target the arm flange and already compensate the TCP offset; do not replace them with the object center.",
            "candidate_failures": failures,
            "timestamp": frame.get("timestamp"),
        }
        finish(result, file=str(annotation))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
