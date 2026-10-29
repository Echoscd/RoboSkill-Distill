#!/usr/bin/env python3
"""Combine a shared agent instruction with a goal-only task specification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "prompts" / "robot_agent.txt"


def render(task: dict[str, str], instruction: str) -> str:
    if set(task) != {"task_id", "goal"}:
        raise ValueError("task specification must contain exactly task_id and goal")
    for name, value in task.items():
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            raise ValueError(f"{name} must be a non-empty single-line string")
    return f"Task ID: {task['task_id']}\nGoal: {task['goal']}\n\n{instruction.strip()}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    task = json.loads(args.task.read_text(encoding="utf-8"))
    instruction = TEMPLATE.read_text(encoding="utf-8")
    prompt = render(task, instruction)
    args.output.write_text(prompt, encoding="utf-8")
    args.manifest.write_text(json.dumps({
        "schema": "kinex/prompt-provenance/1",
        "instruction_path": str(TEMPLATE.resolve()),
        "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "task_path": str(args.task.resolve()),
        "task": task,
        "rendered_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "research_notes_included": False,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
