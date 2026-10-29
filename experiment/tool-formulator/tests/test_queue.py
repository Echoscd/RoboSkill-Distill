"""Focused tests for the tool-formulation request queue."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "queue.py"
SPEC = importlib.util.spec_from_file_location("kinex_tool_formulator_queue", SCRIPT)
assert SPEC and SPEC.loader
queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = queue
SPEC.loader.exec_module(queue)


class QueueTests(unittest.TestCase):
    def test_online_summary_counts_semantic_events_and_writes(self) -> None:
        events = [
            {"kind": "device.dispatch", "device": {"id": "head_camera", "type": "rgbd"}, "action": "read"},
            {"kind": "observation.created"},
            {"kind": "device.dispatch", "device": {"id": "right_arm", "type": "joint"}, "action": "write"},
            {"kind": "execution.receipt"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
            summary = queue.online_summary(path)
        self.assertEqual(summary["kind_counts"]["observation.created"], 1)
        self.assertEqual(summary["device_actions"]["head_camera:read"], 1)
        self.assertEqual(summary["actuator_writes"], 1)

    def test_no_tool_result_rejects_capability_gap(self) -> None:
        result = {
            "decision": "no_tool",
            "diagnosis": {
                "failure_type": "planning",
                "capability_gap": True,
                "summary": "The model misused an existing tool.",
                "evidence": ["trace line 10"],
            },
            "tools": [],
            "validation": {"passed": True, "commands": ["test"]},
            "notes": [],
        }
        with self.assertRaisesRegex(queue.QueueError, "capability_gap"):
            queue.validate_result(result)

    def test_create_tool_requires_changed_tool(self) -> None:
        result = {
            "decision": "create_tool",
            "diagnosis": {
                "failure_type": "perception",
                "capability_gap": True,
                "summary": "A reusable measurement is missing.",
                "evidence": ["trace line 12"],
            },
            "tools": [],
            "validation": {"passed": True, "commands": ["test"]},
            "notes": [],
        }
        with self.assertRaisesRegex(queue.QueueError, "at least one tool"):
            queue.validate_result(result)

    def test_request_id_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(queue.QueueError, "invalid request id"):
            queue.request_directory("../escape")

    def test_no_tool_requires_passed_validation(self) -> None:
        result = {
            "decision": "no_tool",
            "diagnosis": {
                "failure_type": "policy_prompt",
                "capability_gap": False,
                "summary": "The model skipped required verification.",
                "evidence": ["no post-action observation"],
            },
            "tools": [],
            "validation": {"passed": False, "commands": []},
            "notes": [],
        }
        with self.assertRaisesRegex(queue.QueueError, "validation.passed=true"):
            queue.validate_result(result)


if __name__ == "__main__":
    unittest.main()

