"""Position-control math. Physical units: metres, radians, quaternion xyzw.

Joint targets and arrival checks; no device I/O or controller loops.
"""

from kinex.validation import vector

import math

from kinex.geometry import compose_rt, invert_rt, mat_to_quat, xyzq_to_rt


def pose(value, name="pose"):
    vector(value, 7, name)
    if abs(sum(v * v for v in value[3:]) - 1) > 1e-5:
        raise ValueError(f"{name} requires a unit quaternion xyzw")
    return value


def flat(rt):
    return list(rt[1]) + mat_to_quat(rt[0])


def pose_error(goal, current):
    relative = compose_rt(xyzq_to_rt(goal), invert_rt(xyzq_to_rt(current)))
    q = mat_to_quat(relative[0])
    return {"position_m": math.hypot(*(a - b for a, b in zip(goal[:3], current[:3]))),
            "rotation_rad": 2 * math.atan2(math.hypot(*q[:3]), abs(q[3]))}


def joint_target(value, joints):
    if not joints:
        raise ValueError("joint metadata is required")
    vector(value, len(joints), "joint target")
    for position, joint in zip(value, joints):
        limits = joint.get("limits")
        if limits is not None and not limits["min"] <= position <= limits["max"]:
            raise ValueError(f"target outside joint limits: {joint['name']}")
    return value


class Motion:
    """A fixed joint goal, independent of the device pose representation."""

    def __init__(self, joints, goal_joints):
        self.joints = joints
        self.goal_joints = joint_target(goal_joints, joints)

    def errors(self, state):
        positions = vector(state.get("positions"), len(self.joints), "read.positions")
        delta = [math.atan2(math.sin(a - b), math.cos(a - b)) if j.get("type") == "continuous" else a - b
                 for a, b, j in zip(self.goal_joints, positions, self.joints)]
        error = {"joint": max(map(abs, delta)), "joints": list(map(abs, delta))}
        return error
