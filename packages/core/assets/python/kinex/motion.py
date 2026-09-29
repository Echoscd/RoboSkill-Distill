"""Position-control math. Physical units: metres, radians, quaternion xyzw.

Joint targets and arrival checks; no device I/O or controller loops.
"""

from kinex.validation import vector

import math

from kinex.geometry import compose_rt, invert_rt, mat_to_quat, xyzq_to_rt


# Four components rounded to three decimals can change the norm by up to 0.001.
QUATERNION_NORM_TOLERANCE = 1e-3


def quaternion(value, name="quaternion"):
    """Return a near-unit [qx, qy, qz, qw] quaternion scaled to unit norm."""
    vector(value, 4, name)
    norm = math.hypot(*value)
    # Compare bounds directly so the endpoints survive floating-point rounding.
    if not 1 - QUATERNION_NORM_TOLERANCE <= norm <= 1 + QUATERNION_NORM_TOLERANCE:
        raise ValueError(f"{name} requires a unit quaternion [qx, qy, qz, qw] (xyzw); got norm {norm!r} "
                         f"(norms within {QUATERNION_NORM_TOLERANCE:g} of 1 are normalized)")
    return [component / norm for component in value]


def pose(value, name="pose"):
    """Return [x, y, z, qx, qy, qz, qw] with a normalized near-unit quaternion."""
    vector(value, 7, name)
    return value[:3] + quaternion(value[3:], name)


def flat(rt):
    return list(rt[1]) + mat_to_quat(rt[0])


def pose_error(goal, current):
    relative = compose_rt(xyzq_to_rt(goal), invert_rt(xyzq_to_rt(current)))
    q = mat_to_quat(relative[0])
    return {"position_m": math.hypot(*(a - b for a, b in zip(goal[:3], current[:3]))),
            "rotation_rad": 2 * math.atan2(math.hypot(*q[:3]), abs(q[3]))}


def joint_target(value, joints, *, check_limits=True):
    if not joints:
        raise ValueError("joint metadata is required")
    vector(value, len(joints), "joint target")
    for position, joint in zip(value, joints):
        limits = joint.get("limits")
        if check_limits and limits is not None and not limits["min"] <= position <= limits["max"]:
            raise ValueError(f"target outside joint limits: {joint['name']}")
    return value
