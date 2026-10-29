#!/usr/bin/env python3
"""Audit a retained Pi/Kinex session without replaying robot motion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from ..contracts import ExecutionReceipt
from ..policies import evaluate_task


CLAIM_PATTERN = re.compile(
    r"\b(task (?:is|appears to be) complete|completed the task|successfully .*task|"
    r"fulfilled the requirement)\b",
    re.IGNORECASE,
)
CAMERA_HINTS = ("camera", "rgb", "rgbd")
SEMANTIC_TOOL_HINTS = ("grounding", "semantic", "detect_object", "segment_anything")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
    return rows


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _tool_calls(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for sequence, row in enumerate(rows):
        if row.get("type") != "message":
            continue
        message = row.get("message", {})
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for item in message["content"]:
            if not isinstance(item, dict) or item.get("type") != "toolCall":
                continue
            calls.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "arguments": item.get("arguments", {}),
                    "timestamp": row.get("timestamp") or message.get("timestamp"),
                    "sequence": sequence,
                    "message_id": row.get("id"),
                }
            )
    return calls


def _tool_results(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for sequence, row in enumerate(rows):
        if row.get("type") != "message":
            continue
        message = row.get("message", {})
        if message.get("role") != "toolResult":
            continue
        call_id = message.get("toolCallId")
        if call_id:
            results[call_id] = {
                "message": message,
                "timestamp": row.get("timestamp") or message.get("timestamp"),
                "sequence": sequence,
                "message_id": row.get("id"),
            }
    return results


def _parsed_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}
    text = _message_text(result["message"])
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _native_success(manifest_path: Path | None) -> bool | None:
    if manifest_path is None or not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    value = manifest.get("native_success")
    return value if isinstance(value, bool) else None


def _is_camera_observation(call: dict[str, Any]) -> bool:
    name = str(call.get("name", ""))
    arguments = call.get("arguments", {})
    if name == "device" and arguments.get("action") == "read":
        device_id = str(arguments.get("deviceID", "")).lower()
        return any(hint in device_id for hint in CAMERA_HINTS)
    return name.startswith("locate_") or name.startswith("observe_")


def _agent_claim(rows: Iterable[dict[str, Any]], after_sequence: int | None) -> bool | None:
    texts: list[str] = []
    for sequence, row in enumerate(rows):
        if row.get("type") != "message":
            continue
        message = row.get("message", {})
        if message.get("role") != "assistant":
            continue
        if after_sequence is not None and sequence <= after_sequence:
            continue
        texts.append(_message_text(message))
    return True if any(CLAIM_PATTERN.search(text) for text in texts) else None


def audit_session(
    session_path: Path,
    *,
    manifest_path: Path | None = None,
    semantic_target: str | None = None,
) -> dict[str, Any]:
    rows = _read_jsonl(session_path)
    calls = _tool_calls(rows)
    results = _tool_results(rows)
    session_row = next((row for row in rows if row.get("type") == "session"), {})

    servo_calls = [call for call in calls if call.get("name") == "servo"]
    formal_plan_calls = [
        call for call in calls if str(call.get("name", "")).startswith("plan_")
    ]
    observation_calls = [call for call in calls if _is_camera_observation(call)]
    semantic_calls = [
        call
        for call in calls
        if any(hint in str(call.get("name", "")).lower() for hint in SEMANTIC_TOOL_HINTS)
    ]
    color_only_calls = [
        call for call in calls if call.get("name") == "locate_colored_object_3d"
    ]

    receipts: list[ExecutionReceipt] = []
    normalized_servo: list[dict[str, Any]] = []
    last_motion_sequence: int | None = None
    for index, call in enumerate(servo_calls, 1):
        result = results.get(str(call.get("id")))
        message = result.get("message", {}) if result else {}
        parsed = _parsed_result(result)
        accepted = bool(result) and not bool(message.get("isError"))
        completed = accepted if call.get("arguments", {}).get("block", True) else None
        execution_id = str(parsed.get("execution_id") or call.get("id") or f"servo-{index}")
        receipt = ExecutionReceipt(
            execution_id=execution_id,
            plan_id=None,
            stage=None,
            accepted=accepted,
            completed=completed,
            reached=None,
            error=None if accepted else _message_text(message) or "missing tool result",
            evidence={
                "call_id": call.get("id"),
                "call_message_id": call.get("message_id"),
                "result_message_id": result.get("message_id") if result else None,
            },
        )
        receipts.append(receipt)
        normalized_servo.append(receipt.to_dict())
        last_motion_sequence = (result or call).get("sequence")

    post_action_observations = [
        call
        for call in observation_calls
        if last_motion_sequence is not None
        and call.get("sequence") is not None
        and call["sequence"] > last_motion_sequence
    ]
    agent_claim = _agent_claim(rows, last_motion_sequence)
    native_success = _native_success(manifest_path)
    verdict = evaluate_task(
        receipts,
        agent_claim=agent_claim,
        post_action_observation=None,
        visual_effect=None,
        native_success=native_success,
    )

    issues = list(verdict.issues)
    if servo_calls and not formal_plan_calls:
        issues.append("motion_without_plan_contract")
    if semantic_target and color_only_calls and not semantic_calls:
        issues.append("semantic_target_grounded_by_color_only")
    if post_action_observations:
        issues = [issue for issue in issues if issue != "no_post_action_visual_observation"]

    source_sha256 = hashlib.sha256(session_path.read_bytes()).hexdigest()
    return {
        "schema": "kinex/harness-trace-audit/1",
        "source": {
            "session_path": str(session_path),
            "session_sha256": source_sha256,
            "session_id": session_row.get("id"),
            "semantic_target": semantic_target,
        },
        "counts": {
            "tool_calls": len(calls),
            "observations": len(observation_calls),
            "formal_plans": len(formal_plan_calls),
            "servo_calls": len(servo_calls),
            "post_action_observations": len(post_action_observations),
        },
        "execution_receipts": normalized_servo,
        "task_verdict": {
            **verdict.to_dict(),
            "issues": list(dict.fromkeys(issues)),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--semantic-target")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    run_dir = arguments.run_dir.resolve()
    session_path = run_dir / "agent" / "session.jsonl"
    manifest_path = run_dir / "trace-manifest.json"
    report = audit_session(
        session_path,
        manifest_path=manifest_path,
        semantic_target=arguments.semantic_target,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if arguments.output:
        output = arguments.output
        if not output.is_absolute():
            output = run_dir / output
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

