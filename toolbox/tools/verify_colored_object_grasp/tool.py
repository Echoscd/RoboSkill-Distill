#!/usr/bin/env python3
"""Strict sensor-based verification for a colored-object test lift."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

from kinex import args, device, fail, finish
from kinex.frames import pose as frame_pose

LOCATE_DIR = Path(__file__).resolve().parents[1] / "locate_colored_object_3d"
sys.path.insert(0, str(LOCATE_DIR))
from color_geometry import (  # noqa: E402
    _largest_component,
    _mask_for_color,
    locate_colored_object,
    project_endpoints_to_center_plane,
    visible_world_points,
)


def main():
    values = args()
    try:
        initial = np.asarray(values["initial_center_world_m"], dtype=float)
        if initial.shape != (3,) or not np.isfinite(initial).all():
            raise ValueError("initial_center_world_m must contain three finite numbers")

        frame = device(values["camera"], args={"output": "file"})
        color = cv2.imread(frame["file"], cv2.IMREAD_COLOR)
        depth = cv2.imread(frame["depth_file"], cv2.IMREAD_UNCHANGED)
        if color is None or depth is None:
            raise ValueError("camera returned unreadable RGB-D files")
        from kinex import profile
        camera_profile = profile(values["camera"])
        located, annotated = locate_colored_object(
            color, depth, camera_profile, values["color"]
        )
        diameter = float(values["object_diameter_m"])
        if not 0.02 <= diameter <= 0.12:
            raise ValueError("object_diameter_m is outside the supported bottle range")
        initial_axis_length = float(values["initial_axis_length_m"])
        if not 0.05 <= initial_axis_length <= 0.50:
            raise ValueError("initial_axis_length_m is outside the supported bottle range")
        component, _, _ = _largest_component(_mask_for_color(color, values["color"]), 80)
        object_world = visible_world_points(depth, component, camera_profile)
        visible_top_z = float(np.quantile(object_world[:, 2], 0.99))
        observed, end_a, end_b = project_endpoints_to_center_plane(
            located, visible_top_z - diameter / 2.0, camera_profile
        )
        observed_axis_length = float(np.linalg.norm(end_b - end_a))

        arm_state = device(values["arm"], "read")
        tcp = frame_pose(
            f'{values["gripper"]}:tcp', "world",
            readings={values["arm"]: arm_state},
        )
        tcp_position = np.asarray(tcp["translation"], dtype=float)
        gripper_state = device(values["gripper"], "read")
        aperture = gripper_state.get("aperture_m")
        if not isinstance(aperture, (int, float)) or not math.isfinite(aperture):
            raise ValueError("gripper did not report a finite aperture")

        displacement = observed - initial
        object_to_tcp = float(np.linalg.norm(observed - tcp_position))
        xy_displacement = float(np.linalg.norm(displacement[:2]))
        lift = float(displacement[2])
        minimum_lift = float(values.get("minimum_lift_m", 0.03))
        bbox = located["bbox_xyxy"]
        height, width = color.shape[:2]
        fully_visible = bbox[0] > 1 and bbox[1] > 1 and bbox[2] < width - 2 and bbox[3] < height - 2

        # A long object may pivot or slide in the fingers during lift, so its
        # geometric midpoint need not stay at the TCP. Scale tolerances by the
        # observed object length while retaining hard caps that reject a fling.
        # The gripper can hide most of a long bottle after a successful grasp.
        # Never shrink the geometric tolerances from the pre-grasp full length
        # to the post-grasp visible fragment length.
        tolerance_axis_length = max(initial_axis_length, observed_axis_length)
        tcp_tolerance = min(0.14, max(0.065, tolerance_axis_length * 0.5 + 0.025))
        sideways_tolerance = min(0.14, max(0.08, tolerance_axis_length * 0.5 + 0.035))
        checks = {
            "object_lifted": lift >= minimum_lift,
            "object_near_tcp": object_to_tcp <= tcp_tolerance,
            "object_not_flung_sideways": xy_displacement <= sideways_tolerance,
            "gripper_not_fully_closed": float(aperture) >= 0.008,
            "object_fully_visible": fully_visible,
        }
        verified = all(checks.values())
        annotation = Path(frame["file"]).with_name(Path(frame["file"]).stem + "_grasp_verification.png")
        cv2.putText(
            annotated,
            "GRASP VERIFIED" if verified else "GRASP FAILED",
            (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (0, 180, 0) if verified else (0, 0, 255), 2,
        )
        if not cv2.imwrite(str(annotation), annotated):
            raise ValueError("could not save verification annotation")

        finish({
            "grasp_verified": verified,
            "checks": checks,
            "initial_center_world_m": [round(float(x), 6) for x in initial],
            "observed_axis_midpoint_world_m": [round(float(x), 6) for x in observed],
            "visible_top_z_world_m": round(visible_top_z, 6),
            "object_diameter_m": round(diameter, 6),
            "tcp_world_m": [round(float(x), 6) for x in tcp_position],
            "object_displacement_world_m": [round(float(x), 6) for x in displacement],
            "lift_m": round(lift, 6),
            "xy_displacement_m": round(xy_displacement, 6),
            "object_to_tcp_m": round(object_to_tcp, 6),
            "observed_axis_length_m": round(observed_axis_length, 6),
            "initial_axis_length_m": round(initial_axis_length, 6),
            "tcp_tolerance_m": round(tcp_tolerance, 6),
            "sideways_tolerance_m": round(sideways_tolerance, 6),
            "gripper_aperture_m": round(float(aperture), 6),
            "timestamp": frame.get("timestamp"),
        }, file=str(annotation))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
