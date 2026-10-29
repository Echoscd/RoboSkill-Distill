#!/usr/bin/env python3
"""Locate a color-described object from calibrated RGB-D without a learned detector."""

from pathlib import Path

import cv2

from kinex import args, device, fail, finish, profile

from color_geometry import locate_colored_object


def main() -> None:
    values = args()
    camera = values["camera"]
    camera_profile = profile(camera)
    if camera_profile.get("type") != "rgbd":
        fail(f'camera "{camera}" must be RGB-D')
    try:
        mount = camera_profile["extrinsics"]["mount"]
        if mount.get("parent_frame") != "world":
            fail(f'camera "{camera}" mount must be expressed in world frame')
        frame = device(camera, args={"output": "file"})
        color_path = frame.get("file")
        depth_path = frame.get("depth_file")
        if not color_path or not depth_path:
            fail(f'camera "{camera}" did not return paired RGB-D files')
        color = cv2.imread(color_path, cv2.IMREAD_COLOR)
        depth = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
        if color is None or depth is None:
            fail(f'camera "{camera}" returned unreadable RGB-D files')
        result, annotated = locate_colored_object(
            color,
            depth,
            camera_profile,
            values["color"],
            int(values.get("min_area_px", 80)),
        )
        annotation = Path(color_path).with_name(Path(color_path).stem + "_color_grounding.png")
        if not cv2.imwrite(str(annotation), annotated):
            fail("could not save color-grounding annotation")
        finish({**result, "camera": camera, "frame": "world", "timestamp": frame.get("timestamp")}, file=str(annotation))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
