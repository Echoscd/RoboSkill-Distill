"""Pure gates that can run before Kinex dispatch or during offline replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..contracts import ExecutionReceipt, ObservationRef, Plan, TaskVerdict


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def validate_plan_for_execution(
    plan: Plan,
    observations: Iterable[ObservationRef],
    *,
    current_session_id: str,
    current_generation_id: str,
    now_s: float,
    max_position_uncertainty_m: float | None = None,
) -> GateDecision:
    """Reject stale, cross-session or weakly grounded plans before motion."""

    indexed = {observation.observation_id: observation for observation in observations}
    reasons: list[str] = []
    warnings: list[str] = []

    if plan.session_id != current_session_id:
        reasons.append("plan_session_mismatch")
    if plan.generation_id != current_generation_id:
        reasons.append("plan_generation_mismatch")
    if now_s > plan.expires_at_s:
        reasons.append("plan_expired")

    for observation_id in plan.based_on:
        observation = indexed.get(observation_id)
        if observation is None:
            reasons.append(f"missing_observation:{observation_id}")
            continue
        if observation.session_id != plan.session_id:
            reasons.append(f"observation_session_mismatch:{observation_id}")
        if observation.generation_id != plan.generation_id:
            reasons.append(f"observation_generation_mismatch:{observation_id}")
        if observation.acquired_at_s > plan.created_at_s:
            reasons.append(f"observation_newer_than_plan:{observation_id}")

    if (
        max_position_uncertainty_m is not None
        and plan.position_uncertainty_m > max_position_uncertainty_m
    ):
        warnings.append("position_uncertainty_above_policy")

    return GateDecision(not reasons, tuple(dict.fromkeys(reasons)), tuple(warnings))


def evaluate_task(
    receipts: Iterable[ExecutionReceipt],
    *,
    agent_claim: bool | None,
    post_action_observation: ObservationRef | None,
    visual_effect: bool | None,
    native_success: bool | None,
) -> TaskVerdict:
    """Combine independent evidence without promoting motion success to task success."""

    materialized = tuple(receipts)
    issues: list[str] = []
    if materialized and any(receipt.reached is None for receipt in materialized):
        issues.append("measured_arrival_unknown")
    if materialized and post_action_observation is None:
        issues.append("no_post_action_visual_observation")
    if post_action_observation is None and visual_effect is not None:
        issues.append("visual_effect_without_observation")
        visual_effect = None
    if agent_claim is True and native_success is not True:
        issues.append("agent_claim_without_native_success")
    if agent_claim is True and native_success is False:
        issues.append("agent_claim_conflicts_native_failure")

    return TaskVerdict(
        agent_claim=agent_claim,
        visual_effect=visual_effect,
        native_success=native_success,
        issues=tuple(dict.fromkeys(issues)),
    )

