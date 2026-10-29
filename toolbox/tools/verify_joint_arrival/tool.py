#!/usr/bin/env python3
"""Read an arm and verify its measured joints against one commanded target."""

from kinex import args, device, fail, finish

from core import verify_joint_arrival


def main() -> None:
    values = args()
    try:
        arm = values["arm"]
        reading = device(arm, "read")
        result = verify_joint_arrival(
            measured_joints=reading["positions"],
            target_joints=values["target_joints"],
            tolerance_rad=float(values.get("tolerance_rad", 0.02)),
        )
        finish({
            "arm": arm,
            "measured_at_s": reading.get("timestamp"),
            "faults": reading.get("faults", []),
            **result,
        })
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
