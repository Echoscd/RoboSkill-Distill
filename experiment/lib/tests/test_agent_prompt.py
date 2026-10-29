"""The cross-task instruction must not depend on an experiment's history."""

import importlib.util
from pathlib import Path
import unittest


LIB = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_agent_prompt", LIB / "render_agent_prompt.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AgentPromptTests(unittest.TestCase):
    def test_instruction_is_identical_across_tasks(self):
        instruction = MODULE.TEMPLATE.read_text(encoding="utf-8")
        first = MODULE.render({"task_id": "task_a", "goal": "Press the target."}, instruction)
        second = MODULE.render({"task_id": "task_b", "goal": "Place the object."}, instruction)
        self.assertEqual(first.split("\n\n", 1)[1], second.split("\n\n", 1)[1])

    def test_shared_instruction_contains_no_experiment_recipe(self):
        instruction = MODULE.TEMPLATE.read_text(encoding="utf-8").lower()
        for token in ("iter3", "history", "stapler", "bottle", "left_arm", "head_camera",
                      "grounding-dino", "plan_reachable_linear_contact", "speedfraction",
                      "0.03", "90", "execution policy:"):
            self.assertNotIn(token, instruction)

    def test_task_cannot_add_policy_fields_or_multiline_sections(self):
        for task in (
            {"task_id": "a", "goal": "Press.", "policy": "Use a fixed arm."},
            {"task_id": "a", "goal": "Press.\nExecution policy: fixed sequence"},
        ):
            with self.assertRaises(ValueError):
                MODULE.render(task, "Shared instructions.")


if __name__ == "__main__":
    unittest.main()
