#!/usr/bin/env python3
"""Select an arm/effector and solve a complete ordered TCP-pose sequence."""

from kinex import args, fail, finish, profile

from core import solve_reachable_pose_sequence


def main() -> None:
    values = args()
    try:
        pairs = [
            {
                "arm": item["arm"],
                "effector": item["effector"],
                "arm_profile": profile(item["arm"]),
                "effector_profile": profile(item["effector"]),
            }
            for item in values["arm_effector_pairs"]
        ]
        finish(solve_reachable_pose_sequence(
            pairs=pairs,
            pose_sequence_variants=values["pose_sequence_variants"],
            based_on=values["based_on"],
            observed_at_s=float(values["observed_at_s"]),
            expires_at_s=float(values["expires_at_s"]),
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
