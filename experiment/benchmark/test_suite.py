"""Offline catalog and artifact tests; never start models or simulators."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml


SPEC = importlib.util.spec_from_file_location("benchmark_suite", Path(__file__).with_name("run_suite.py"))
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


class SuiteTests(unittest.TestCase):
    def test_catalog_selects_matching_rig_and_preserves_public_goal_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, upstream = root/"catalog", root/"upstream"
            description = upstream/"description/task_instruction"
            description.mkdir(parents=True)
            for name, robot, goal in [("a", "robotwin/robotwin-aloha-agilex", "Press the button."),
                                      ("b", "robotwin/robotwin-aloha-agilex", "Lift {object}."),
                                      ("c", "different_rig", "Do something.")]:
                task = catalog/name/"task.yaml"
                task.parent.mkdir(parents=True)
                task.write_text(yaml.safe_dump({"id": f"robotwin/{name}", "robot": robot,
                    "instruction": goal, "backend_kwargs": {"task_name": name}}))
            (description/"b.json").write_text(json.dumps({"full_description": "Lift the bottle upright."}))
            jobs = suite.discover(catalog, upstream, seed=0)
            self.assertEqual([x["native_task"] for x in jobs], ["a", "b"])
            self.assertEqual(jobs[1]["goal"], "Lift the bottle upright.")
            self.assertTrue(jobs[1]["goal_source"].endswith("b.json"))
            self.assertFalse(jobs[0]["task_config"]["backend_kwargs"]["allow_seed_substitution"])

    def test_unresolved_instruction_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root/"catalog/a/task.yaml"
            task.parent.mkdir(parents=True)
            task.write_text(yaml.safe_dump({"id": "robotwin/a", "robot": "robotwin/robotwin-aloha-agilex",
                "instruction": "Lift {object}.", "backend_kwargs": {"task_name": "missing"}}))
            with self.assertRaisesRegex(ValueError, "public instruction"):
                suite.discover(root/"catalog", root/"upstream", 0)

    def test_atomic_state_file_remains_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"state.json"
            suite.write_json(path, {"state": "running"})
            suite.write_json(path, {"state": "complete"})
            self.assertEqual(suite.read_object(path), {"state": "complete"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
