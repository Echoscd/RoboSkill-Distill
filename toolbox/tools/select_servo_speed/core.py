"""Pure selection over precomputed Servo trajectory durations."""

from __future__ import annotations

import math
from typing import Any


def select_servo_speed(
    *,
    durations_by_fraction: dict[float, float],
    max_duration_s: float,
) -> dict[str, Any]:
    if not math.isfinite(max_duration_s) or max_duration_s <= 0:
        raise ValueError("max_duration_s must be a positive finite number")
    if not durations_by_fraction:
        raise ValueError("at least one candidate fraction is required")
    evaluated = []
    for fraction, duration in sorted(durations_by_fraction.items()):
        fraction = float(fraction)
        duration = float(duration)
        if not math.isfinite(fraction) or not 0 < fraction <= 1:
            raise ValueError("candidate fractions must be finite values in (0, 1]")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("computed durations must be positive finite values")
        evaluated.append({"speedFraction": fraction, "duration_s": duration})
    feasible = [item for item in evaluated if item["duration_s"] <= max_duration_s]
    selected = feasible[0] if feasible else None
    return {
        "feasible": selected is not None,
        "speedFraction": selected["speedFraction"] if selected else None,
        "expected_duration_s": selected["duration_s"] if selected else None,
        "max_duration_s": float(max_duration_s),
        "evaluated": evaluated,
    }
