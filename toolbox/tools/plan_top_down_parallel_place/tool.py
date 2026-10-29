#!/usr/bin/env python3
"""Plan a TCP-preserving top-down placement at an explicit object-center target."""

from kinex import args, fail, finish, profile

from core import plan_top_down_place


def main() -> None:
    values = args()
    try:
        finish(plan_top_down_place(
            arm=values["arm"],
            gripper=values["gripper"],
            arm_profile=profile(values["arm"]),
            gripper_profile=profile(values["gripper"]),
            target_object_center_world_m=values["target_object_center_world_m"],
            preplace_distance_m=float(values.get("preplace_distance_m", 0.08)),
            retreat_distance_m=float(values.get("retreat_distance_m", 0.08)),
        ))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
