#!/usr/bin/env python3
"""Plan an IK-checked top-down parallel-jaw grasp from explicit object geometry."""

from kinex import args, fail, finish, profile

from core import plan_top_down_grasp


def main() -> None:
    values = args()
    try:
        result = plan_top_down_grasp(
            arm=values["arm"],
            gripper=values["gripper"],
            arm_profile=profile(values["arm"]),
            gripper_profile=profile(values["gripper"]),
            center_world_m=values["object_center_world_m"],
            major_axis_world_xy=values["major_axis_world_xy"],
            major_extent_m=float(values["major_extent_m"]),
            minor_extent_m=float(values["minor_extent_m"]),
            pregrasp_distance_m=float(values.get("pregrasp_distance_m", 0.10)),
            test_lift_m=float(values.get("test_lift_m", 0.06)),
            clearance_m=float(values.get("clearance_m", 0.01)),
        )
        finish(result)
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
