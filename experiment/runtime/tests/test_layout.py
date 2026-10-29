"""Protect the shared entry point and task-independent transfer setup."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOLBOX_SPEC = importlib.util.spec_from_file_location(
    "layout_toolbox", ROOT / "toolbox/scripts/toolbox.py"
)
TOOLBOX = importlib.util.module_from_spec(TOOLBOX_SPEC)
sys.modules[TOOLBOX_SPEC.name] = TOOLBOX
TOOLBOX_SPEC.loader.exec_module(TOOLBOX)


class LayoutTests(unittest.TestCase):
    def test_active_catalog_matches_shared_toolset_dependency_closure(self):
        records = TOOLBOX.load_records()
        requested = [
            line.strip() for line in (ROOT / "experiment/toolset.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        resolved = set()

        def visit(name):
            if name in resolved:
                return
            resolved.add(name)
            for dependency in records[name].dependencies:
                visit(dependency)

        for name in requested:
            visit(name)
        self.assertEqual(resolved, set(records))

    def test_each_task_renders_through_same_launcher_without_credentials(self):
        suffixes = []
        for task in ("press-stapler", "click-bell", "turn-switch"):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as run:
                result = subprocess.run(
                    ["bash", str(ROOT / "experiment/runtime/start-task.sh"),
                     str(ROOT / "experiment" / task), run],
                    env={**os.environ, "KINEX_DRY_RUN": "1"},
                    capture_output=True, text=True, check=True,
                )
                self.assertIn("experiment/toolset.txt", result.stdout)
                prompt = (Path(run) / "input-prompt.txt").read_text()
                suffixes.append(prompt.split("\n\n", 1)[1])
                self.assertFalse((Path(run) / "private-config").exists())
                task_json = json.loads((ROOT / "experiment" / task / "task.json").read_text())
                self.assertEqual(set(task_json), {"task_id", "goal"})
        self.assertEqual(len(set(suffixes)), 1)

    def test_shell_scripts_parse(self):
        for script in (ROOT / "experiment").rglob("*.sh"):
            with self.subTest(script=script):
                subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
