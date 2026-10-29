#!/usr/bin/env python3
"""Prepare a read-only model diagnosis after an authoritative simulator failure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def task_context(run_dir: Path) -> dict[str, str]:
    prompt_path = run_dir / "agent" / "prompt.txt"
    try:
        lines = prompt_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    result = {"task": "unknown", "goal": "unknown"}
    for line in lines:
        if line.startswith("Task ID:"):
            result["task"] = line.partition(":")[2].strip()
        elif line.startswith("Goal:"):
            result["goal"] = line.partition(":")[2].strip()
    return result


def compact_json(value: Any, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def summarize_operations(path: Path, limit: int = 18) -> dict[str, Any]:
    counts = {
        "tool_calls": 0,
        "tool_errors": 0,
        "camera_observations": 0,
        "formal_plans": 0,
        "servo_calls": 0,
        "execution_receipts": 0,
    }
    steps: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("kind")
        if kind == "model_tool.start":
            counts["tool_calls"] += 1
            name = str(event.get("name") or "unknown")
            if name == "servo":
                counts["servo_calls"] += 1
            if len(steps) < limit:
                steps.append(f"called {name} with {compact_json(event.get('input') or {})}")
        elif kind == "model_tool.end" and event.get("is_error") is True:
            counts["tool_errors"] += 1
            if len(steps) < limit:
                steps.append(f"{event.get('name') or 'tool'} returned an error")
        elif kind == "observation.created":
            counts["camera_observations"] += 1
        elif kind == "plan.created" and event.get("contract_status") == "complete":
            counts["formal_plans"] += 1
        elif kind == "execution.receipt":
            counts["execution_receipts"] += 1

    return {"counts": counts, "steps": steps, "truncated": len(steps) == limit}


def native_failure_signal(verdict: dict[str, Any]) -> dict[str, Any]:
    native = verdict.get("native_result")
    native = native if isinstance(native, dict) else {}
    return {
        "native_success": verdict.get("success"),
        "verdict": verdict.get("verdict"),
        "submitted": verdict.get("submitted"),
        "completed": native.get("completed"),
        "reward": native.get("reward"),
        "raw_score": native.get("raw_score"),
        "tier": native.get("tier"),
        "budget": native.get("budget"),
    }


def video_catalog(run_dir: Path) -> list[dict[str, str]]:
    """Expose recorded visual evidence, never evaluator state or implementation."""
    root = run_dir.resolve()
    return [
        {"view": video.stem, "video_path": str(video.resolve()), "clock": "video_relative_seconds"}
        for video in sorted(root.glob("roboenv/*/evidence/recording/*.mp4"))
        if video.resolve().is_relative_to(root) and video.stat().st_size > 0
    ]


def prepare(verdict_path: Path, run_dir: Path) -> tuple[dict[str, Any], str | None]:
    verdict = read_json(verdict_path)
    required = (
        verdict.get("schema") == "kinex/simulator-verdict/1"
        and verdict.get("authority") == "roboenv_native_evaluator"
        and verdict.get("success") is False
    )
    decision = {
        "schema": "kinex/failure-analysis-decision/1",
        "required": required,
        "reason": "native_evaluator_failure" if required else "no_authoritative_failure",
        "native_success": verdict.get("success"),
        "analysis_mode": "terminal_read_only" if required else None,
    }
    if not required:
        return decision, None

    task = task_context(run_dir)
    videos = video_catalog(run_dir)
    decision["video_catalog"] = videos
    decision["video_inspection_required"] = bool(videos)
    operations = summarize_operations(run_dir / "harness-events.jsonl")
    signal = native_failure_signal(verdict)
    observation = verdict.get("submission_observation")
    observation = observation if isinstance(observation, dict) else {}
    frame = observation.get("file") or "unavailable"
    depth = observation.get("depth_file") or "unavailable"
    steps = "\n".join(
        f"{index}. {step}" for index, step in enumerate(operations["steps"], 1)
    ) or "1. No operation summary was recorded."
    if videos:
        video_evidence = "\n".join(
            f"- Recorded view `{item['view']}`: `{item['video_path']}`" for item in videos
        )
        first_inspection = (
            "Start by calling inspect_episode_video with a video_path from the catalog and "
            "max_frames=12, omitting start_s and end_s for a full-recording overview. "
            "The tool attaches actual ordered images, source-frame indices, and video times. "
            "Use shorter start_s/end_s intervals when a suspected event needs closer inspection. "
            "Inspect the motion before diagnosing it; the submission screenshot is supplemental, "
            "not a substitute for the recorded sequence."
        )
    else:
        video_evidence = "- No usable recorded video is available. State this temporal-evidence gap."
        first_inspection = (
            "No recorded video is available. Inspect the submission-time RGB frame as fallback, "
            "and explicitly state that earlier motion cannot be reconstructed from this single frame."
        )
    prompt = f"""## Post-evaluation failure analysis

RoboEnv's one-shot native evaluator has returned `native_success=false`. The
episode is now terminal and frozen. This phase is diagnosis only: do not move an
arm or gripper, do not retry the task, and do not reinterpret the native verdict.

### Bounded evidence packet

- Task: `{task['task']}`
- Goal: {task['goal']}
{video_evidence}
- Submission-time head-camera RGB frame: `{frame}`
- Registered depth paired with that frame: `{depth}`
- Native failure signal: `{compact_json(signal, 600)}`
- Operation counts: `{compact_json(operations['counts'], 600)}`

Operations performed, in order (bounded summary):
{steps}

{first_inspection}

Do not open or ingest the complete
primary-session or harness JSONL files; they are retained only for offline audit.

For every visual claim cite an inspected video interval or returned source-frame
index. Separate visible motion from inferred contact and mechanism actuation.
Occlusion is an unknown, not proof of contact or success. Final retreat positions
do not establish whether an earlier press target was reached. A frozen wrist-camera
read reveals only the final scene, not the earlier contact phase.

Reason across competing hypotheses before selecting any additional observation:
perception/grounding, coordinate transform, plan geometry, IK, execution arrival,
physical contact/effect, occlusion, and evaluator/goal mismatch. Prefer existing
trace evidence first. If another camera read would distinguish hypotheses, choose
the view with the highest information gain.

### Optional read-only diagnostic tools

- `inspect_episode_video(video_path, start_s?, end_s?, max_frames?)`: inspect an
  overview first, then choose a shorter interval or another recorded view.
- `device(head_camera, read)`: refresh the global RGB-D view.
- `device(left_camera, read)` / `device(right_camera, read)`: inspect local contact,
  slip or occlusion from the selected arm's wrist view.
- `device(left_arm, read)` / `device(right_arm, read)`: inspect achieved joint and
  actuator state.
- `device(left_gripper, read)` / `device(right_gripper, read)`: inspect gripper
  aperture/state when grasp or contact retention is relevant.
- Existing operation counts and Plan/ExecutionReceipt facts above: use these without
  a new device call when they already determine the failure.

These are options, not a checklist. Select only the tool that separates plausible
hypotheses after the required video overview when one is available. It is valid
to request no further evidence after that overview. All device calls must be read-only.

Return: the first causal failure, supporting trace evidence, rejected alternatives,
remaining uncertainty, any diagnostic tool used and why, and the smallest reusable
pipeline/tool change. Do not output a new success judgment.
"""
    return decision, prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdict", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--prompt", required=True, type=Path)
    args = parser.parse_args()

    decision, prompt = prepare(args.verdict, args.run_dir.resolve())
    args.decision.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if prompt is None:
        return 10
    args.prompt.write_text(prompt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
