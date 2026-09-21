"""Pose math shared by tools, drivers, and calibration scripts.

Pure python + math, no protocol imports, no side effects — safe to import from
any script the harness spawns. Conventions match the profile schema
(see camera DEVICE.md#use): a pose is child-in-parent (p_parent = R·p_child + t), a
quaternion is [x, y, z, w] scalar-LAST, and an (R, t) pair is a 3x3 row-major
rotation with a 3-vector translation.
"""

import math


def quat_to_mat(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def mat_to_quat(R):
    """Stable branch-based conversion; output [qx, qy, qz, qw]."""
    trace = R[0][0] + R[1][1] + R[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q = [(R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s, (R[1][0] - R[0][1]) / s, 0.25 * s]
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2.0
        q = [0.25 * s, (R[0][1] + R[1][0]) / s, (R[0][2] + R[2][0]) / s, (R[2][1] - R[1][2]) / s]
    elif R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2.0
        q = [(R[0][1] + R[1][0]) / s, 0.25 * s, (R[1][2] + R[2][1]) / s, (R[0][2] - R[2][0]) / s]
    else:
        s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2.0
        q = [(R[0][2] + R[2][0]) / s, (R[1][2] + R[2][1]) / s, 0.25 * s, (R[1][0] - R[0][1]) / s]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def apply_rt(rt, point):
    R, t = rt
    return [sum(R[row][col] * point[col] for col in range(3)) + t[row] for row in range(3)]


def compose_rt(a, b):
    """T_a ∘ T_b: apply b first, then a."""
    Ra, ta = a
    Rb, tb = b
    R = [[sum(Ra[i][k] * Rb[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return R, apply_rt(a, tb)


def invert_rt(rt):
    R, t = rt
    Rt = [[R[j][i] for j in range(3)] for i in range(3)]
    return Rt, [-sum(Rt[i][j] * t[j] for j in range(3)) for i in range(3)]


def pose_to_rt(pose):
    """Profile Pose dict {translation, rotation xyzw} -> (R, t)."""
    return quat_to_mat(pose["rotation"]), list(pose["translation"])


def mount_to_rt(mount):
    """Read the rigid transform of a typed device mount."""
    translation, rotation = mount["translation_m"], mount["rotation_xyzw"]
    if not isinstance(translation, list) or not isinstance(rotation, list):
        raise ValueError("mount transform has not been calibrated")
    return pose_to_rt({"translation": translation, "rotation": rotation})


def rt_to_pose(rt):
    R, t = rt
    return {"translation": [float(v) for v in t], "rotation": mat_to_quat(R)}


def xyzq_to_rt(flat):
    """[x, y, z, qx, qy, qz, qw] (named-frame pose) -> (R, t)."""
    return quat_to_mat(flat[3:7]), list(flat[0:3])
