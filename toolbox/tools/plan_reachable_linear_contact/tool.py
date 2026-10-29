#!/usr/bin/env python3
"""Choose an IK-feasible linear contact plan across bounded arm/yaw candidates."""

from kinex import args, fail, finish, profile

from core import plan_reachable_linear_contact


def main() -> None:
    values = args()
    try:
        pairs = []
        for item in values["arm_effector_pairs"]:
            pairs.append({
                "arm": item["arm"],
                "effector": item["effector"],
                "arm_profile": profile(item["arm"]),
                "effector_profile": profile(item["effector"]),
            })
        finish(plan_reachable_linear_contact(
            pairs=pairs,
            contact_point_world_m=values["contact_point_world_m"],
            surface_outward_normal_world=values["surface_outward_normal_world"],
            preferred_tangent_axis_world=values.get("preferred_tangent_axis_world", [1.0, 0.0, 0.0]),
            approach_distance_m=float(values.get("approach_distance_m", 0.10)),
            press_distance_m=float(values.get("press_distance_m", 0.03)),
            observation_id=values["observation_id"],
            observed_at_s=float(values["observed_at_s"]),
            valid_for_s=float(values.get("valid_for_s", 5.0)),
            position_uncertainty_m=float(values["position_uncertainty_m"]),
            collision_context_path=values.get("collision_context_path"),
            collision_margin_m=float(values.get("collision_margin_m", 0.005)),
            max_joint_step_rad=float(values.get("max_joint_step_rad", 0.025)),
            robot_profile_call=profile,
            robot_pair_margin_m=float(values.get("robot_pair_margin_m", 0)),
        ))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
