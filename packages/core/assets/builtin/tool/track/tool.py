#!/usr/bin/env python3
"""Observe → policy inference → one absolute joint target, without arrival waits."""

import time

from kinex import args, device, finish, loop, profile
from kinex.joint_control import joint_model
from kinex.motion import joint_target, vector


def run(a):
    model, observe, command = a["model"], a["observe"], a["command"]
    if not isinstance(command, str) or not isinstance(model, str):
        raise ValueError("command and model must each name one device")
    if not isinstance(observe, list) or any(not isinstance(name, str) for name in observe):
        raise ValueError("observe must be a list of device names")
    arm = profile(command)
    if arm.get("type") != "joint":
        raise ValueError("track requires type joint; dexterous_hand is excluded")
    policy = profile(model)
    if policy.get("type") != "model" or "infer" not in [operation["name"] for operation in policy.get("intrinsics", {}).get("operations", [])]:
        raise ValueError("model must be a model device declaring infer")
    joints = joint_model(arm)["joints"]
    if not joints:
        raise ValueError("track requires joint metadata")
    rate = a.get("rate_hz", 20)
    budget, timeout = a.get("max_steps", 50), a.get("timeout_s", 590)
    vector([rate, budget, timeout], 3, "track rate and budgets")
    if rate <= 0 or budget <= 0 or not isinstance(budget, int) or not 0 < timeout <= 590:
        raise ValueError("rate_hz must be positive, max_steps a positive integer, timeout_s in (0, 590]")
    task = a.get("task")
    deadline = time.monotonic() + timeout
    outcome = {"expired": False}

    def step(i):
        if time.monotonic() >= deadline:
            outcome["expired"] = True
            return True
        obs = {}
        for name in dict.fromkeys(observe):
            reading = device(name)
            entry = dict(reading.get("data") or {})
            if reading.get("file"):
                entry["file"] = reading["file"]
            obs[name] = entry
        state = obs.get(command)
        if state is None:
            state = device(command).get("data") or {}
        if not isinstance(state.get("faults"), list):
            raise ValueError("joint read.faults must be a list")
        if state["faults"]:
            raise RuntimeError(f"joint fault: {state['faults']}")
        inference = device(model, "infer", obs=obs, **({"task": task} if task else {}))
        if time.monotonic() >= deadline:
            outcome["expired"] = True
            return True  # A late inference must not command motion after the budget.
        data = inference.get("data") or {}
        action = joint_target(data.get("action"), joints)
        receipt = device(command, "write", target=action).get("data") or {}
        if receipt.get("accepted") is not True:
            raise ValueError("write must acknowledge accepted: true")
        return bool(data.get("done"))

    # kinex.loop paces from each iteration's start. Slow inference simply
    # lowers the achieved rate; there is no queued catch-up or repeated action.
    result = loop(step, max_steps=budget, rate_hz=rate, timeout_s=timeout,
                  until=a.get("until"), on_stop=lambda: device(command, "stop"))
    return {**result, "terminated_by": "timeout" if outcome["expired"] else result["terminated_by"]}


if __name__ == "__main__":
    finish(run(args()))
