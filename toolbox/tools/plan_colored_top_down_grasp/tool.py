#!/usr/bin/env python3
"""Compose color geometry estimation with generic top-down grasp planning."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import cv2

from kinex import args, device, fail, finish, profile


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load toolbox component {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = _load_module(
    "kinex_toolbox_colored_geometry_core",
    ROOT / "estimate_colored_object_geometry_3d" / "core.py",
)
GRASP = _load_module(
    "kinex_toolbox_top_down_grasp_core",
    ROOT / "plan_top_down_parallel_grasp" / "core.py",
)


def main() -> None:
    values = args()
    camera, arm, gripper = values["camera"], values["arm"], values["gripper"]
    try:
        camera_profile = profile(camera)
        if camera_profile.get("type") != "rgbd":
            raise ValueError(f'camera "{camera}" must be RGB-D')
        if camera_profile["extrinsics"]["mount"].get("parent_frame") != "world":
            raise ValueError(f'camera "{camera}" mount must be expressed in world frame')
        frame = device(camera, args={"output": "file"})
        color = cv2.imread(frame["file"], cv2.IMREAD_COLOR)
        depth = cv2.imread(frame["depth_file"], cv2.IMREAD_UNCHANGED)
        if color is None or depth is None:
            raise ValueError("camera returned unreadable RGB-D files")

        geometry, annotated = GEOMETRY.estimate_geometry(
            color,
            depth,
            camera_profile,
            values["color"],
            int(values.get("min_area_px", 80)),
        )
        footprint = geometry["footprint"]
        plan = GRASP.plan_top_down_grasp(
            arm=arm,
            gripper=gripper,
            arm_profile=profile(arm),
            gripper_profile=profile(gripper),
            center_world_m=geometry["center_world_m"],
            major_axis_world_xy=footprint["major_axis_world_xy"],
            major_extent_m=float(footprint["major_extent_m"]),
            minor_extent_m=float(footprint["minor_extent_m"]),
            pregrasp_distance_m=float(values.get("pregrasp_distance_m", 0.10)),
            test_lift_m=float(values.get("test_lift_m", 0.06)),
            clearance_m=float(values.get("clearance_m", 0.01)),
        )
        annotation = Path(frame["file"]).with_name(
            Path(frame["file"]).stem + "_colored_top_grasp.png"
        )
        if not cv2.imwrite(str(annotation), annotated):
            raise ValueError("could not save grasp-plan annotation")
        finish(
            {
                **plan,
                "camera": camera,
                "object": geometry,
                "composition": [
                    "locate_colored_object_3d",
                    "estimate_colored_object_geometry_3d",
                    "read_gripper_contract",
                    "plan_top_down_parallel_grasp",
                ],
                "timestamp": frame.get("timestamp"),
            },
            file=str(annotation),
        )
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
