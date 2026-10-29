from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiment.harness.tracing.audit_pi_session import audit_session  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class PressStaplerAuditTests(unittest.TestCase):
    def test_retained_failure_is_not_promoted_to_success(self) -> None:
        report = audit_session(
            FIXTURES / "press_stapler_seed0.jsonl",
            manifest_path=FIXTURES / "press_stapler_manifest.json",
            semantic_target="stapler",
        )

        self.assertEqual(report["counts"]["servo_calls"], 3)
        self.assertEqual(report["counts"]["formal_plans"], 0)
        self.assertEqual(report["counts"]["post_action_observations"], 0)
        self.assertTrue(all(item["accepted"] for item in report["execution_receipts"]))
        self.assertTrue(all(item["completed"] for item in report["execution_receipts"]))
        self.assertTrue(all(item["reached"] is None for item in report["execution_receipts"]))

        verdict = report["task_verdict"]
        self.assertEqual(verdict["final_verdict"], "failure")
        self.assertIs(verdict["agent_claim"], True)
        self.assertIs(verdict["visual_effect"], None)
        self.assertIs(verdict["native_success"], False)
        self.assertIn("motion_without_plan_contract", verdict["issues"])
        self.assertIn("semantic_target_grounded_by_color_only", verdict["issues"])
        self.assertIn("no_post_action_visual_observation", verdict["issues"])
        self.assertIn("agent_claim_conflicts_native_failure", verdict["issues"])


if __name__ == "__main__":
    unittest.main()

