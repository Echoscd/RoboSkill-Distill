from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from experiment.lib.evaluate_simulator import evaluate
from experiment.lib.prepare_failure_analysis import prepare


class SimulatorEvaluationTest(unittest.TestCase):
    def test_native_failure_is_authoritative_and_ignores_agent_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            evidence = run / "roboenv" / "id" / "evidence"
            evidence.mkdir(parents=True)
            (run / "stop.json").write_text(
                json.dumps({"simulation": {"terminal": True, "success": False}}),
                encoding="utf-8",
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"submitted": True, "native_success": False}), encoding="utf-8"
            )
            result = evaluate(run)
            self.assertIs(result["success"], False)
            self.assertFalse(result["agent_claim_used"])

    def test_conflicting_native_sources_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            evidence = run / "roboenv" / "id" / "evidence"
            evidence.mkdir(parents=True)
            (run / "stop.json").write_text(
                json.dumps({"simulation": {"terminal": True, "success": True}}),
                encoding="utf-8",
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"submitted": True, "native_success": False}), encoding="utf-8"
            )
            result = evaluate(run)
            self.assertIsNone(result["success"])
            self.assertIn("simulator_verdict_conflict", result["issues"])

    def test_native_failure_requests_general_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict = root / "simulator-verdict.json"
            verdict.write_text(
                json.dumps({
                    "schema": "kinex/simulator-verdict/1",
                    "authority": "roboenv_native_evaluator",
                    "success": False,
                    "verdict": "failure",
                    "submitted": True,
                    "submission_observation": {
                        "file": "/evidence/submission.png",
                        "depth_file": "/evidence/submission.pgm",
                    },
                    "native_result": {"completed": False, "reward": 0.0},
                }),
                encoding="utf-8",
            )
            agent = root / "agent"
            agent.mkdir()
            (agent / "prompt.txt").write_text(
                "Task ID: robotwin/press-stapler\nGoal: Press it fully.\n",
                encoding="utf-8",
            )
            (root / "harness-events.jsonl").write_text(
                "\n".join([
                    json.dumps({
                        "kind": "model_tool.start",
                        "name": "plan_linear_contact",
                        "input": {"device": "left_arm"},
                    }),
                    json.dumps({
                        "kind": "plan.created",
                        "contract_status": "complete",
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            decision, prompt = prepare(verdict, root)
            self.assertTrue(decision["required"])
            self.assertIn("competing hypotheses", prompt)
            self.assertIn("/evidence/submission.png", prompt)
            self.assertIn("Press it fully", prompt)
            self.assertIn("called plan_linear_contact", prompt)
            self.assertIn("Optional read-only diagnostic tools", prompt)
            self.assertIn("options, not a checklist", prompt)
            self.assertNotIn("primary-session.jsonl`", prompt)
            self.assertIn("do not move", prompt)

    def test_native_success_skips_failure_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verdict = root / "simulator-verdict.json"
            verdict.write_text(
                json.dumps({
                    "schema": "kinex/simulator-verdict/1",
                    "authority": "roboenv_native_evaluator",
                    "success": True,
                }),
                encoding="utf-8",
            )
            decision, prompt = prepare(verdict, root)
            self.assertFalse(decision["required"])
            self.assertIsNone(prompt)

    def test_native_failure_requires_video_overview_when_recording_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recording = root / "roboenv" / "episode" / "evidence" / "recording"
            recording.mkdir(parents=True)
            video = recording / "third_person.mp4"
            video.write_bytes(b"synthetic-presence-marker")
            verdict = root / "simulator-verdict.json"
            verdict.write_text(json.dumps({
                "schema": "kinex/simulator-verdict/1", "authority": "roboenv_native_evaluator",
                "success": False, "submitted": True,
            }), encoding="utf-8")
            decision, prompt = prepare(verdict, root)
            self.assertTrue(decision["video_inspection_required"])
            self.assertEqual(decision["video_catalog"][0]["video_path"], str(video.resolve()))
            self.assertIn("Start by calling inspect_episode_video", prompt)
            self.assertIn("max_frames=12", prompt)
            self.assertNotIn("Read the submission-time RGB frame first", prompt)
            self.assertIn("Final retreat positions", prompt)


if __name__ == "__main__":
    unittest.main()
