#!/usr/bin/env python3
"""Select a bounded Servo speed using Servo's trajectory implementation."""

from kinex import args, fail, finish, profile
from kinex.control import read
from kinex.joint_control import home_start_tolerance
from kinex.motion import joint_target
from kinex.trajectory import trajectory

from core import select_servo_speed


def main() -> None:
    values = args()
    try:
        arm = values["arm"]
        prof = profile(arm)
        if prof.get("type") != "joint":
            raise ValueError("arm must be a loaded joint device")
        model_joints = prof["resolved_model"]["joints"]
        state = read(arm)
        check_limits = prof["intrinsics"]["control"].get("limit_handling") != "native"
        start = joint_target(state["positions"], model_joints, check_limits=False)
        goal = joint_target(values["target_joints"], model_joints, check_limits=check_limits)
        fractions = [float(value) for value in values.get(
            "candidate_fractions", [0.25, 0.5, 0.75, 1.0]
        )]
        if len(set(fractions)) != len(fractions):
            raise ValueError("candidate_fractions must be unique")
        durations = {}
        for fraction in fractions:
            plan = trajectory(
                model_joints,
                start,
                goal,
                0.01,
                fraction,
                None,
                None,
                check_limits=check_limits,
                start_tolerance=home_start_tolerance(prof, model_joints, goal),
            )
            durations[fraction] = plan.duration_s
        result = select_servo_speed(
            durations_by_fraction=durations,
            max_duration_s=float(values.get("max_duration_s", 15.0)),
        )
        finish({
            "arm": arm,
            "measured_at_s": state.get("timestamp"),
            "measured_start_joints": list(start),
            "target_joints": list(goal),
            **result,
        })
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
