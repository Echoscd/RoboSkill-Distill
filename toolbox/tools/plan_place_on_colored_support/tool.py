#!/usr/bin/env python3
"""Compose support perception with live-orientation top-down placement planning."""

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
    "kinex_toolbox_support_geometry_core",
    ROOT / "estimate_colored_object_geometry_3d" / "core.py",
)
PLACE = _load_module(
    "kinex_toolbox_top_down_place_core",
    ROOT / "plan_top_down_parallel_place" / "core.py",
)


def main() -> None:
    values = args()
    camera, arm, gripper = values["camera"], values["arm"], values["gripper"]
    try:
        held_height = float(values["held_object_height_m"])
        if not 0.008 <= held_height <= 0.25:
            raise ValueError("held_object_height_m must be between 0.008 and 0.25 m")
        clearance = float(values.get("placement_clearance_m", 0.001))
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
        support, annotated = GEOMETRY.estimate_geometry(
            color,
            depth,
            camera_profile,
            values["support_color"],
            int(values.get("min_area_px", 80)),
        )
        target_center = [
            float(support["center_world_m"][0]),
            float(support["center_world_m"][1]),
            float(support["visible_top_z_world_m"]) + held_height / 2.0 + clearance,
        ]
        plan = PLACE.plan_top_down_place(
            arm=arm,
            gripper=gripper,
            arm_profile=profile(arm),
            gripper_profile=profile(gripper),
            target_object_center_world_m=target_center,
            preplace_distance_m=float(values.get("preplace_distance_m", 0.08)),
            retreat_distance_m=float(values.get("retreat_distance_m", 0.08)),
        )
        annotation = Path(frame["file"]).with_name(
            Path(frame["file"]).stem + "_place_on_support.png"
        )
        if not cv2.imwrite(str(annotation), annotated):
            raise ValueError("could not save support annotation")
        finish(
            {
                **plan,
                "camera": camera,
                "support": support,
                "held_object_height_m": held_height,
                "placement_clearance_m": clearance,
                "composition": [
                    "locate_colored_object_3d",
                    "estimate_colored_object_geometry_3d",
                    "read_gripper_contract",
                    "plan_top_down_parallel_grasp",
                    "plan_top_down_parallel_place",
                ],
                "timestamp": frame.get("timestamp"),
            },
            file=str(annotation),
        )
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
