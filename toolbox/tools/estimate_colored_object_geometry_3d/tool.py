#!/usr/bin/env python3
"""Estimate support-relative 3-D geometry for a colored tabletop object."""

from pathlib import Path

import cv2

from kinex import args, device, fail, finish, profile

from core import estimate_geometry


def main() -> None:
    values = args()
    camera = values["camera"]
    try:
        camera_profile = profile(camera)
        if camera_profile.get("type") != "rgbd":
            raise ValueError(f'camera "{camera}" must be RGB-D')
        mount = camera_profile["extrinsics"]["mount"]
        if mount.get("parent_frame") != "world":
            raise ValueError(f'camera "{camera}" mount must be expressed in world frame')
        frame = device(camera, args={"output": "file"})
        color = cv2.imread(frame["file"], cv2.IMREAD_COLOR)
        depth = cv2.imread(frame["depth_file"], cv2.IMREAD_UNCHANGED)
        if color is None or depth is None:
            raise ValueError("camera returned unreadable RGB-D files")
        result, annotated = estimate_geometry(
            color,
            depth,
            camera_profile,
            values["color"],
            int(values.get("min_area_px", 80)),
        )
        annotation = Path(frame["file"]).with_name(
            Path(frame["file"]).stem + "_object_geometry.png"
        )
        if not cv2.imwrite(str(annotation), annotated):
            raise ValueError("could not save geometry annotation")
        finish(
            {**result, "camera": camera, "timestamp": frame.get("timestamp")},
            file=str(annotation),
        )
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
