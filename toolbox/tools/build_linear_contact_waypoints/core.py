"""Build task-specific TCP waypoint variants for straight normal contact."""

from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np


def _unit(value: list[float], label: str) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{label} must contain three finite numbers")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError(f"{label} has zero length")
    return vector / norm


def _quaternion_xyzw(rotation: np.ndarray) -> list[float]:
    """Convert a proper 3x3 rotation matrix to a normalized xyzw quaternion."""
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
        w = 0.25 * scale
    else:
        index = int(np.argmax(np.diag(rotation)))
        if index == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            x = 0.25 * scale
            y = (rotation[0, 1] + rotation[1, 0]) / scale
            z = (rotation[0, 2] + rotation[2, 0]) / scale
            w = (rotation[2, 1] - rotation[1, 2]) / scale
        elif index == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            x = (rotation[0, 1] + rotation[1, 0]) / scale
            y = 0.25 * scale
            z = (rotation[1, 2] + rotation[2, 1]) / scale
            w = (rotation[0, 2] - rotation[2, 0]) / scale
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            x = (rotation[0, 2] + rotation[2, 0]) / scale
            y = (rotation[1, 2] + rotation[2, 1]) / scale
            z = 0.25 * scale
            w = (rotation[1, 0] - rotation[0, 1]) / scale
    quaternion = np.asarray([x, y, z, w], dtype=float)
    quaternion /= np.linalg.norm(quaternion)
    return [round(float(value), 7) for value in quaternion]


def _candidate_tangents(normal: np.ndarray, preferred: np.ndarray) -> list[np.ndarray]:
    tangent = preferred - normal * float(np.dot(preferred, normal))
    tangent = _unit(tangent.tolist(), "preferred tangent projected onto contact plane")
    perpendicular = _unit(np.cross(normal, tangent).tolist(), "perpendicular tangent")
    return [tangent, -tangent, perpendicular, -perpendicular]


def build_linear_contact_waypoints(
    *,
    contact_point_world_m: list[float],
    surface_outward_normal_world: list[float],
    preferred_tangent_axis_world: list[float],
    approach_distance_m: float,
    press_distance_m: float,
    observation_id: str,
    observed_at_s: float,
    valid_for_s: float,
    position_uncertainty_m: float,
) -> dict[str, Any]:
    """Return four deterministic TCP-pose variants without selecting an arm or solving IK."""
    contact = np.asarray(contact_point_world_m, dtype=float)
    if contact.shape != (3,) or not np.all(np.isfinite(contact)):
        raise ValueError("contact_point_world_m must contain three finite numbers")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError("observation_id must not be blank")
    if not (0.0 <= position_uncertainty_m <= 0.05):
        raise ValueError("position_uncertainty_m must be in [0, 0.05]")
    if valid_for_s <= 0.0:
        raise ValueError("valid_for_s must be positive")
    if approach_distance_m <= press_distance_m:
        raise ValueError("approach_distance_m must exceed press_distance_m")

    outward = _unit(surface_outward_normal_world, "surface_outward_normal_world")
    preferred = _unit(preferred_tangent_axis_world, "preferred_tangent_axis_world")
    approach_direction = -outward
    points = {
        "approach": contact + outward * approach_distance_m,
        "contact": contact,
        "press": contact - outward * press_distance_m,
        "retreat": contact + outward * approach_distance_m,
    }
    variants: list[dict[str, Any]] = []
    for index, tangent in enumerate(_candidate_tangents(outward, preferred)):
        third = _unit(np.cross(approach_direction, tangent).tolist(), "contact basis")
        rotation = np.column_stack((approach_direction, tangent, third))
        quaternion = _quaternion_xyzw(rotation)
        variants.append({
            "variant_id": f"tangent_{index}",
            "metadata": {
                "tangent_axis_world": [round(float(value), 7) for value in tangent],
            },
            "waypoints": [
                {
                    "stage": stage,
                    "tcp_pose_world": [
                        *[round(float(value), 7) for value in point],
                        *quaternion,
                    ],
                }
                for stage, point in points.items()
            ],
        })

    return {
        "waypoint_set_id": f"linear_contact_{uuid.uuid4().hex[:12]}",
        "motion_semantics": "linear_normal_contact",
        "contact_model": {
            "reference": "tcp_origin",
            "physical_contact_feature": None,
            "physical_contact_verified": None,
            "limitations": "No finger/pad contact offset, aperture-dependent geometry, or contact patch is modeled.",
        },
        "frame": "world",
        "based_on": [observation_id],
        "observed_at_s": float(observed_at_s),
        "expires_at_s": float(observed_at_s + valid_for_s),
        "position_uncertainty_m": float(position_uncertainty_m),
        "contact_point_world_m": [round(float(value), 7) for value in contact],
        "surface_outward_normal_world": [round(float(value), 7) for value in outward],
        "approach_direction_world": [round(float(value), 7) for value in approach_direction],
        "press_direction_world": [round(float(value), 7) for value in approach_direction],
        "waypoint_variants": variants,
    }
