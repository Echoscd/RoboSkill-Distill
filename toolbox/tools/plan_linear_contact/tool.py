#!/usr/bin/env python3
"""Build an IK-checked linear contact plan from measured world geometry."""

from kinex import args, fail, finish, profile

from core import plan_linear_contact


def main() -> None:
    values = args()
    try:
        finish(plan_linear_contact(
            arm=values["arm"],
            effector=values["effector"],
            arm_profile=profile(values["arm"]),
            effector_profile=profile(values["effector"]),
            contact_point_world_m=values["contact_point_world_m"],
            surface_outward_normal_world=values["surface_outward_normal_world"],
            tangent_axis_world=values.get("tangent_axis_world", [1.0, 0.0, 0.0]),
            approach_distance_m=float(values.get("approach_distance_m", 0.10)),
            press_distance_m=float(values.get("press_distance_m", 0.03)),
            observation_id=values["observation_id"],
            observed_at_s=float(values["observed_at_s"]),
            valid_for_s=float(values.get("valid_for_s", 5.0)),
            position_uncertainty_m=float(values["position_uncertainty_m"]),
        ))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
