"""Pure joint-target arrival verification."""

from __future__ import annotations

import math
from typing import Any


def verify_joint_arrival(
    *,
    measured_joints: list[float],
    target_joints: list[float],
    tolerance_rad: float,
) -> dict[str, Any]:
    if not measured_joints or len(measured_joints) != len(target_joints):
        raise ValueError("measured_joints and target_joints must have the same nonzero length")
    if not math.isfinite(tolerance_rad) or tolerance_rad <= 0:
        raise ValueError("tolerance_rad must be a positive finite number")
    measured = [float(value) for value in measured_joints]
    target = [float(value) for value in target_joints]
    if not all(math.isfinite(value) for value in measured + target):
        raise ValueError("joint arrays must contain only finite numbers")
    errors = [actual - desired for actual, desired in zip(measured, target, strict=True)]
    absolute = [abs(value) for value in errors]
    return {
        "reached": max(absolute) <= tolerance_rad,
        "tolerance_rad": tolerance_rad,
        "max_abs_error_rad": max(absolute),
        "rms_error_rad": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "per_joint_error_rad": errors,
        "measured_joints": measured,
        "target_joints": target,
    }
