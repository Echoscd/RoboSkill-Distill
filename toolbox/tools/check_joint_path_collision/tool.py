#!/usr/bin/env python3
"""Read-only check of explicit arm trajectories against declared obstacles."""

from kinex import args, device, fail, finish, profile

from core import ArmCollisionChecker, load_context


def main():
    values = args()
    try:
        context = load_context(values["collision_context_path"])
        others = [name for name in context["arms"] if name != values["arm"]]
        checker = ArmCollisionChecker(
            values["arm"], profile(values["arm"]), context,
            margin_m=float(values.get("collision_margin_m", 0.005)),
            max_joint_step_rad=float(values.get("max_joint_step_rad", 0.025)),
            other_arm_profiles={name: profile(name) for name in others},
            other_arm_states={name: device(name, "read") for name in others},
            robot_pair_margin_m=float(values.get("robot_pair_margin_m", 0)),
        )
        finish(checker.check(values["start_joints"], values["joint_stages"]))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
