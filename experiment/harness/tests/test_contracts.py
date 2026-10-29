from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiment.harness.contracts import (  # noqa: E402
    ArtifactRef,
    ContractError,
    ExecutionReceipt,
    ObservationRef,
    Plan,
    PlanStage,
)
from experiment.harness.policies import evaluate_task, validate_plan_for_execution  # noqa: E402


def observation(generation_id: str = "generation-1") -> ObservationRef:
    return ObservationRef(
        observation_id="obs-1",
        session_id="session-1",
        generation_id=generation_id,
        camera_id="head_camera",
        acquired_at_s=10.0,
        frame_id="head_camera",
        calibration_id="calibration-1",
        rgb=ArtifactRef("artifacts/rgb.png", "image/png"),
        depth=ArtifactRef("artifacts/depth.pgm", "image/x-portable-graymap"),
    )


def plan(**overrides: object) -> Plan:
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "session_id": "session-1",
        "generation_id": "generation-1",
        "based_on": ("obs-1",),
        "tool_name": "plan_linear_contact",
        "tool_version": "0.1.0",
        "source_frame": "head_camera",
        "target_frame": "world",
        "created_at_s": 11.0,
        "expires_at_s": 15.0,
        "position_uncertainty_m": 0.01,
        "stages": (
            PlanStage("precontact", "precontact", {"pose": [0, 0, 0, 0, 0, 0, 1]}),
        ),
    }
    values.update(overrides)
    return Plan(**values)  # type: ignore[arg-type]


class ContractTests(unittest.TestCase):
    def test_fresh_plan_is_allowed(self) -> None:
        decision = validate_plan_for_execution(
            plan(),
            [observation()],
            current_session_id="session-1",
            current_generation_id="generation-1",
            now_s=12.0,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reasons, ())

    def test_stale_cross_generation_plan_is_rejected(self) -> None:
        decision = validate_plan_for_execution(
            plan(),
            [observation(generation_id="generation-0")],
            current_session_id="session-1",
            current_generation_id="generation-2",
            now_s=20.0,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("plan_generation_mismatch", decision.reasons)
        self.assertIn("plan_expired", decision.reasons)
        self.assertIn("observation_generation_mismatch:obs-1", decision.reasons)

    def test_arrival_cannot_be_inferred_from_unfinished_execution(self) -> None:
        with self.assertRaisesRegex(ContractError, "measured arrival requires"):
            ExecutionReceipt(
                execution_id="exec-1",
                plan_id="plan-1",
                stage="contact",
                accepted=True,
                completed=None,
                reached=True,
                target_error_m=0.001,
            )

    def test_agent_claim_does_not_override_native_failure(self) -> None:
        receipt = ExecutionReceipt(
            execution_id="exec-1",
            plan_id="plan-1",
            stage="contact",
            accepted=True,
            completed=True,
            reached=None,
        )
        verdict = evaluate_task(
            [receipt],
            agent_claim=True,
            post_action_observation=None,
            visual_effect=None,
            native_success=False,
        )
        self.assertEqual(verdict.final_verdict, "failure")
        self.assertIn("no_post_action_visual_observation", verdict.issues)
        self.assertIn("agent_claim_conflicts_native_failure", verdict.issues)


if __name__ == "__main__":
    unittest.main()

