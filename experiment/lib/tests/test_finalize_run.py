from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


LIB = Path(__file__).resolve().parents[1]
FINALIZER = LIB / "finalize_run.py"
RENDERER = LIB / "render_trace.py"


class FinalizeRunTest(unittest.TestCase):
    def run_finalizer(self, run_dir: Path, exit_code: int = 0) -> dict:
        completed = subprocess.run(
            [
                sys.executable,
                str(FINALIZER),
                "--run-dir",
                str(run_dir),
                "--process-exit-code",
                str(exit_code),
                "--renderer",
                str(RENDERER),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_complete_failed_run_keeps_trace_and_renders_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            agent = run_dir / "agent"
            evidence = run_dir / "roboenv" / "id" / "evidence"
            agent.mkdir(parents=True)
            evidence.mkdir(parents=True)
            events = [
                {"type": "message", "message": {"role": "user", "content": "press the stapler"}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect it."}]}},
            ]
            (agent / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            (agent / "run-state.txt").write_text(
                "exit_code=0\nmodel=test-model\niteration=iter_0\ntask=robotwin/test\n",
                encoding="utf-8",
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"task": "robotwin/test", "submitted": True, "success_latched": False}),
                encoding="utf-8",
            )

            result = self.run_finalizer(run_dir)
            manifest = json.loads((run_dir / "trace-manifest.json").read_text(encoding="utf-8"))
            report = (run_dir / "trace.html").read_text(encoding="utf-8")

            self.assertIs(result["native_success"], False)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["raw_artifacts"]["events"]["lines"], 2)
            self.assertIn("press the stapler", report)
            self.assertTrue(manifest["raw_artifacts"]["events"]["sha256"])

    def test_prelaunch_failure_still_has_manifest_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            result = self.run_finalizer(run_dir, exit_code=2)
            manifest = json.loads((run_dir / "trace-manifest.json").read_text(encoding="utf-8"))

            self.assertIsNone(result["trace"])
            self.assertEqual(manifest["status"], "incomplete")
            self.assertIn("No Kinex session", (run_dir / "trace.html").read_text(encoding="utf-8"))

    def test_invalid_canonical_verdict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            agent = run_dir / "agent"
            evidence = run_dir / "roboenv" / "id" / "evidence"
            agent.mkdir(parents=True)
            evidence.mkdir(parents=True)
            (agent / "events.jsonl").write_text(
                json.dumps({"type": "session", "id": "fail-closed"}) + "\n",
                encoding="utf-8",
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"native_success": True, "submitted": True}), encoding="utf-8"
            )
            (run_dir / "simulator-verdict.json").write_text(
                json.dumps({
                    "schema": "kinex/simulator-verdict/1",
                    "authority": "roboenv_native_evaluator",
                    "agent_claim_used": False,
                    "success": None,
                    "conflict": True,
                }),
                encoding="utf-8",
            )

            result = self.run_finalizer(run_dir)
            manifest = json.loads((run_dir / "trace-manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(result["native_success"])
            self.assertEqual(manifest["status"], "incomplete")

    def test_session_run_adds_read_only_harness_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            agent = run_dir / "agent"
            evidence = run_dir / "roboenv" / "id" / "evidence"
            agent.mkdir(parents=True)
            evidence.mkdir(parents=True)
            rows = [
                {"type": "session", "id": "session-1"},
                {
                    "type": "message",
                    "id": "call-message",
                    "timestamp": "2026-10-27T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{
                            "type": "toolCall",
                            "id": "servo-1",
                            "name": "servo",
                            "arguments": {"device": "right_arm", "block": True},
                        }],
                    },
                },
                {
                    "type": "message",
                    "id": "result-message",
                    "timestamp": "2026-10-27T00:00:01Z",
                    "message": {
                        "role": "toolResult",
                        "toolCallId": "servo-1",
                        "toolName": "servo",
                        "content": [{"type": "text", "text": '{"execution_id":"exec-1"}'}],
                        "isError": False,
                    },
                },
                {
                    "type": "message",
                    "id": "claim-message",
                    "timestamp": "2026-10-27T00:00:02Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I completed the task."}],
                    },
                },
            ]
            (agent / "session.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            (agent / "run-state.txt").write_text(
                "exit_code=0\ntask=robotwin/test\n", encoding="utf-8"
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"task": "robotwin/test", "native_success": False}),
                encoding="utf-8",
            )

            self.run_finalizer(run_dir)
            manifest = json.loads((run_dir / "trace-manifest.json").read_text(encoding="utf-8"))
            audit = json.loads((run_dir / "harness-audit.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["harness_audit"]["status"], "complete")
            self.assertEqual(audit["counts"]["servo_calls"], 1)
            self.assertEqual(audit["task_verdict"]["final_verdict"], "failure")
            self.assertIn("no_post_action_visual_observation", audit["task_verdict"]["issues"])

    def test_execution_recording_is_embedded_with_frame_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            agent = run_dir / "agent"
            evidence = run_dir / "roboenv" / "id" / "evidence"
            recording = evidence / "recording"
            agent.mkdir(parents=True)
            recording.mkdir(parents=True)
            (agent / "session.jsonl").write_text(
                json.dumps({"type": "session", "id": "session-video"}) + "\n",
                encoding="utf-8",
            )
            (agent / "run-state.txt").write_text(
                "exit_code=0\ntask=robotwin/test\n", encoding="utf-8"
            )
            (evidence / "native-episode.json").write_text(
                json.dumps({"task": "robotwin/test", "native_success": True}),
                encoding="utf-8",
            )
            (recording / "manifest.json").write_text(
                json.dumps({
                    "status": "complete",
                    "fps": 25,
                    "encoded_frames": 3,
                    "captured_samples": 3,
                    "dropped_samples": 0,
                }),
                encoding="utf-8",
            )
            (recording / "frames.jsonl").write_text(
                "".join([
                    json.dumps({"source_time_s": 0.0, "frame_start": 0, "frame_stop": 1}) + "\n",
                    json.dumps({"source_time_s": 0.04, "frame_start": 1, "frame_stop": 2}) + "\n",
                    json.dumps({"source_time_s": 0.08, "frame_start": 2, "frame_stop": 3}) + "\n",
                ]),
                encoding="utf-8",
            )
            (recording / "main.mp4").write_bytes(b"fake-mp4-for-renderer-test")

            self.run_finalizer(run_dir)
            manifest = json.loads((run_dir / "trace-manifest.json").read_text(encoding="utf-8"))
            report = (run_dir / "trace.html").read_text(encoding="utf-8")

            self.assertEqual(manifest["native_evidence"]["recording"]["videos"][0]["bytes"], 26)
            self.assertIn("Execution video", report)
            self.assertIn("data:video/mp4;base64,", report)
            self.assertIn('data-frames="3"', report)
            self.assertIn("Previous frame", report)


if __name__ == "__main__":
    unittest.main()
