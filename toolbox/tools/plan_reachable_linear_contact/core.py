"""Compatibility composition for reachable linear contact planning."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable


TOOLS_DIR = Path(__file__).resolve().parents[1]


def _load_sibling(tool_name: str, module_name: str):
    path = TOOLS_DIR / tool_name / "core.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {tool_name} core from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BUILDER_MODULE = _load_sibling(
    "build_linear_contact_waypoints", "kinex_toolbox_build_linear_contact_waypoints_core"
)
_SOLVER_MODULE = _load_sibling(
    "solve_reachable_pose_sequence", "kinex_toolbox_solve_reachable_pose_sequence_core"
)
build_linear_contact_waypoints = _BUILDER_MODULE.build_linear_contact_waypoints
solve_reachable_pose_sequence = _SOLVER_MODULE.solve_reachable_pose_sequence


def plan_reachable_linear_contact(
    *,
    pairs: list[dict[str, Any]],
    contact_point_world_m: list[float],
    surface_outward_normal_world: list[float],
    preferred_tangent_axis_world: list[float],
    approach_distance_m: float,
    press_distance_m: float,
    observation_id: str,
    observed_at_s: float,
    valid_for_s: float,
    position_uncertainty_m: float,
    waypoint_builder: Callable[..., dict[str, Any]] = build_linear_contact_waypoints,
    sequence_solver: Callable[..., dict[str, Any]] = solve_reachable_pose_sequence,
) -> dict[str, Any]:
    """Compose contact-specific TCP geometry with task-independent reachability."""
    waypoint_set = waypoint_builder(
        contact_point_world_m=contact_point_world_m,
        surface_outward_normal_world=surface_outward_normal_world,
        preferred_tangent_axis_world=preferred_tangent_axis_world,
        approach_distance_m=approach_distance_m,
        press_distance_m=press_distance_m,
        observation_id=observation_id,
        observed_at_s=observed_at_s,
        valid_for_s=valid_for_s,
        position_uncertainty_m=position_uncertainty_m,
    )
    solved = sequence_solver(
        pairs=pairs,
        pose_sequence_variants=waypoint_set["waypoint_variants"],
        based_on=waypoint_set["based_on"],
        observed_at_s=waypoint_set["observed_at_s"],
        expires_at_s=waypoint_set["expires_at_s"],
        position_uncertainty_m=waypoint_set["position_uncertainty_m"],
    )
    stages = {item["stage"]: item for item in solved["joint_stages"]}
    required = ("approach", "contact", "press", "retreat")
    missing = [name for name in required if name not in stages]
    if missing:
        raise ValueError(f"sequence solver omitted required linear-contact stages: {missing}")
    tangent = solved.get("selected_variant_metadata", {}).get("tangent_axis_world")

    return {
        **solved,
        "planner": "plan_reachable_linear_contact",
        "waypoint_builder": "build_linear_contact_waypoints",
        "reachability_solver": "solve_reachable_pose_sequence",
        "waypoint_set_id": waypoint_set["waypoint_set_id"],
        "motion_semantics": waypoint_set["motion_semantics"],
        "contact_model": waypoint_set["contact_model"],
        "warning": "Discrete IK only. The contact stage places the TCP origin at the supplied point; no physical finger/pad contact feature or aperture geometry is modeled. IK success does not establish contact, collision clearance, force, or task effect.",
        "contact_point_world_m": waypoint_set["contact_point_world_m"],
        "surface_outward_normal_world": waypoint_set["surface_outward_normal_world"],
        "approach_direction_world": waypoint_set["approach_direction_world"],
        "press_direction_world": waypoint_set["press_direction_world"],
        "selected_tangent_axis_world": tangent,
        "approach_flange_pose_world": stages["approach"]["flange_pose_world"],
        "contact_flange_pose_world": stages["contact"]["flange_pose_world"],
        "press_flange_pose_world": stages["press"]["flange_pose_world"],
        "retreat_flange_pose_world": stages["retreat"]["flange_pose_world"],
        "approach_joints": stages["approach"]["joints"],
        "contact_joints": stages["contact"]["joints"],
        "press_joints": stages["press"]["joints"],
        "retreat_joints": stages["retreat"]["joints"],
        "execution_order": [
            "approach_joints", "contact_joints", "press_joints", "retreat_joints"
        ],
    }
