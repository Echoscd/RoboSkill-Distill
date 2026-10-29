#!/usr/bin/env python3
"""Expose a gripper profile as a compact, executable planning contract."""

from kinex import args, device, fail, finish, profile

from gripper_contract import gripper_contract


def main() -> None:
    values = args()
    try:
        result = gripper_contract(profile(values["gripper"]), values.get("arm"))
        state = device(values["gripper"], "read")
        result["current_aperture_m"] = state.get("aperture_m")
        result["timestamp"] = state.get("timestamp")
        result["usage"] = (
            "Send only values inside control.bounds to the gripper. Use open_target "
            "before approach and close_target only after reaching a collision-safe grasp pose."
        )
        finish(result)
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
