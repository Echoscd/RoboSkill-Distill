"""Tests for toolbox metadata and dependency invariants."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "toolbox.py"
SPEC = importlib.util.spec_from_file_location("kinex_toolbox_cli", SCRIPT)
assert SPEC and SPEC.loader
toolbox = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox
SPEC.loader.exec_module(toolbox)


class ToolboxTests(unittest.TestCase):
    def test_repository_toolbox_is_valid(self) -> None:
        records = toolbox.load_records()
        toolbox.validate_graph(records)
        self.assertGreaterEqual(len(records), 4)

    def test_registry_is_deterministic(self) -> None:
        records = toolbox.load_records()
        first = toolbox.registry_payload(records)
        second = toolbox.registry_payload(records)
        self.assertEqual(first, second)
        self.assertEqual(first["tool_count"], len(records))
        self.assertTrue(all(item["interface"].endswith("/tool.yaml") for item in first["tools"]))
        self.assertTrue(all(item["toolbook"].endswith("/toolbook.yaml") for item in first["tools"]))

    def test_equal_or_higher_dependency_level_is_rejected(self) -> None:
        records = toolbox.load_records()
        changed = dict(records)
        source = records["verify_colored_object_grasp"]
        metadata = deepcopy(source.metadata)
        metadata["level"]["score"] = records["locate_colored_object_3d"].level
        changed[source.name] = toolbox.ToolRecord(source.path, metadata)
        with self.assertRaisesRegex(toolbox.ToolboxError, "dependency level must be lower"):
            toolbox.validate_graph(changed)

    def test_missing_score_is_rejected(self) -> None:
        source = toolbox.load_records()["locate_colored_object_3d"]
        metadata = deepcopy(source.metadata)
        del metadata["generality"]["score"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / source.name
            path.mkdir()
            (path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            (path / "tool.py").write_text("", encoding="utf-8")
            (path / "tool.yaml").write_text(f"name: {source.name}\n", encoding="utf-8")
            record = toolbox.ToolRecord(path, metadata)
            with self.assertRaisesRegex(toolbox.ToolboxError, "missing: score"):
                toolbox.validate_record(record)

    def test_unsupported_runtime_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locate_colored_object_3d"
            shutil.copytree(toolbox.TOOLS_DIR / path.name, path)
            yaml_path = path / "tool.yaml"
            yaml_path.write_text(
                yaml_path.read_text(encoding="utf-8").replace(
                    "kind: perception", "kind: planning"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(toolbox.ToolboxError, "kind must be"):
                toolbox.load_records(Path(directory))

    def test_missing_toolbook_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "read_gripper_contract"
            shutil.copytree(toolbox.TOOLS_DIR / path.name, path)
            (path / "toolbook.yaml").unlink()
            with self.assertRaisesRegex(toolbox.ToolboxError, "missing required file toolbook.yaml"):
                toolbox.load_records(Path(directory))

    def test_change_log_version_must_match_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "read_gripper_contract"
            shutil.copytree(toolbox.TOOLS_DIR / path.name, path)
            with (path / "changes.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps({
                    "timestamp": "2026-10-29T00:00:00Z",
                    "version": "9.9.9",
                    "author": "gpt",
                    "change_type": "fix",
                    "summary": "test mismatch",
                    "reason": "test validator",
                    "failure_ids": [],
                    "files": ["tool.py"],
                }) + "\n")
            with self.assertRaisesRegex(toolbox.ToolboxError, "latest change version"):
                toolbox.load_records(Path(directory))

    def test_failurebox_repository_is_valid(self) -> None:
        failures = toolbox.load_failures()
        self.assertIsInstance(failures, dict)


if __name__ == "__main__":
    unittest.main()

