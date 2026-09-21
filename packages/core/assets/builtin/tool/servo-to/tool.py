#!/usr/bin/env python3
"""Reach a device-owned joint goal; pose conversion belongs to its IK driver."""

from kinex import args, device, finish, loop, profile
from kinex.joint_control import command as joint_command, JointSamples
from kinex.motion import Motion, vector


def run(a):
    name = a["device"]
    prof = profile(name)
    if prof.get("type") != "joint":
        raise ValueError("servo_to requires type joint; dexterous_hand is excluded")
    allowed = {"device", "joints", "pose", "speedFraction", "joint_tolerance", "quiet_velocity", "stable_s", "timeout_s", "max_steps"}
    if set(a) - allowed:
        raise ValueError("unsupported servo_to parameters: " + ", ".join(sorted(set(a) - allowed)))
    if (a.get("joints") is None) == (a.get("pose") is None):
        raise ValueError("provide exactly one of joints or pose")
    settings = {key: a.get(key, default) for key, default in {
        "stable_s": 0.1, "timeout_s": 30.0, "max_steps": 1000,
    }.items()}
    vector(list(settings.values()), len(settings), "servo_to settings")
    if any(v <= 0 for v in settings.values()) or not isinstance(settings["max_steps"], int):
        raise ValueError("settings must be positive; max_steps must be an integer")
    if settings["timeout_s"] > 110:
        raise ValueError("timeout_s must be <= 110 (manifest hard cap is 120s)")
    model = prof.get("resolved_model")
    if not isinstance(model, dict) or not model.get("joints"):
        raise ValueError("resolved joint metadata is required")
    joints = model["joints"]
    def tolerances(key, default):
        value = a.get(key, default)
        values = value if isinstance(value, list) else [value] * len(joints)
        vector(values, len(joints), key)
        if any(v <= 0 for v in values):
            raise ValueError(f"{key} must be positive")
        return values
    tolerance = tolerances("joint_tolerance", 0.01)
    quiet_limits = tolerances("quiet_velocity", 0.005)
    samples = JointSamples(joints, prof["intrinsics"].get("feedback", {}).get("velocities", True))
    goal = a.get("joints")
    if a.get("pose") is not None:
        if not (prof["intrinsics"].get("kinematics") or {}).get("ik"):
            raise ValueError("pose goals require declared IK")
        goal = (device(name, "ik", pose=a["pose"]).get("data") or {}).get("joints")
    motion = Motion(joints, goal)
    command = {"target": motion.goal_joints}
    if "speedFraction" in a:
        command["speedFraction"] = a["speedFraction"]
    joint_command(prof, command, model)
    execution = prof["intrinsics"]["control"].get("execution", {"mode": "realtime", "command_timeout_s": None})
    rate = None
    if execution["mode"] == "realtime":
        timeout = execution["command_timeout_s"]
        rate = max(20, 2 / timeout) if timeout is not None else 20
    progress = {"error": None, "stable_since": None,
                "reason": None, "writes": 0}

    def within(error):
        return all(value <= limit for value, limit in zip(error["joints"], tolerance))

    def step(index):
        state = device(name).get("data") or {}
        if not isinstance(state.get("faults"), list):
            raise ValueError("read.faults must be a list")
        if state["faults"]:
            progress["reason"] = "fault"
            return True
        stamp, velocities, fresh = samples.sample(state)
        error = motion.errors(state)
        progress["error"] = error
        quiet = velocities is not None and all(abs(v) <= limit for v, limit in zip(velocities, quiet_limits))
        if fresh and within(error) and quiet:
            if progress["stable_since"] is None:
                progress["stable_since"] = stamp
            if stamp - progress["stable_since"] >= settings["stable_s"]:
                progress["reason"] = "reached"
                return True
        if not within(error) or not quiet:
            progress["stable_since"] = None
        receipt = device(name, "write", **command).get("data") or {}
        progress["writes"] += 1
        if receipt.get("accepted") is not True:
            raise ValueError("write must acknowledge accepted: true; arrival is established by read")
        return False

    result = loop(step, max_steps=settings["max_steps"], timeout_s=settings["timeout_s"],
                  rate_hz=rate,
                  on_stop=lambda: device(name, "stop"))
    final = device(name).get("data") or {}
    if not isinstance(final.get("faults"), list):
        raise ValueError("final read.faults must be a list")
    reason = progress["reason"] or result["terminated_by"]
    error = progress["error"]
    if reason != "fault":
        error = motion.errors(final)
    if final.get("faults"):
        reason = "fault"
    if reason == "reached" and not within(error):
        reason = "disturbed"
    if reason == "reached":
        _, velocities, _ = samples.sample(final)
        if not within(error) or velocities is None or any(abs(v) > limit for v, limit in zip(velocities, quiet_limits)):
            reason = "disturbed"
    return {"reached": reason == "reached", "terminated_by": reason, "steps": result["steps"],
            "writes": progress["writes"], "error": error, "state": final}


if __name__ == "__main__":
    finish(run(args()))
