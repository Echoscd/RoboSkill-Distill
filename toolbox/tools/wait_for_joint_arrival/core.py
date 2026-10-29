"""Arrival-poll state transitions composed from verify_joint_arrival."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


VERIFY_CORE_PATH = Path(__file__).resolve().parents[1] / "verify_joint_arrival" / "core.py"
_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "kinex_toolbox_verify_joint_arrival_core", VERIFY_CORE_PATH
)
if _VERIFY_SPEC is None or _VERIFY_SPEC.loader is None:
    raise ImportError(f"cannot load verify_joint_arrival core from {VERIFY_CORE_PATH}")
_VERIFY_MODULE = importlib.util.module_from_spec(_VERIFY_SPEC)
sys.modules[_VERIFY_SPEC.name] = _VERIFY_MODULE
_VERIFY_SPEC.loader.exec_module(_VERIFY_MODULE)
verify_joint_arrival = _VERIFY_MODULE.verify_joint_arrival


def evaluate_sample(
    *,
    measured_joints: list[float],
    target_joints: list[float],
    tolerance_rad: float,
    faults: list[Any],
    consecutive_reached: int,
    stable_samples: int,
) -> dict[str, Any]:
    if not isinstance(stable_samples, int) or not 1 <= stable_samples <= 5:
        raise ValueError("stable_samples must be an integer from 1 through 5")
    metrics = verify_joint_arrival(
        measured_joints=measured_joints,
        target_joints=target_joints,
        tolerance_rad=tolerance_rad,
    )
    next_count = consecutive_reached + 1 if metrics["reached"] and not faults else 0
    return {
        **metrics,
        "sample_reached": metrics["reached"],
        "reached": next_count >= stable_samples and not faults,
        "consecutive_reached": next_count,
        "stable_samples": stable_samples,
        "faults": list(faults),
    }
