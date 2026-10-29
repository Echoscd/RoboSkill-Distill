#!/usr/bin/env python3
"""Create and manage evidence-backed Kinex tool-formulation requests."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REQUESTS_ROOT = REPO_ROOT / "experiment" / "tool-formulator" / "requests"
TOOLBOX_ROOT = REPO_ROOT / "toolbox"
REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FINAL_DECISIONS = {"no_tool", "create_tool", "update_tool", "blocked"}
FAILURE_TYPES = {"perception", "planning", "execution", "verification", "policy_prompt", "runtime", "unknown"}


class QueueError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QueueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def file_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": relative(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def online_summary(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    devices: Counter[str] = Counter()
    actuator_writes = 0
    if not path.is_file():
        return {"available": False}
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            counts[str(event.get("kind"))] += 1
            if event.get("kind") == "device.dispatch":
                device = event.get("device") if isinstance(event.get("device"), dict) else {}
                devices[f"{device.get('id')}:{event.get('action')}"] += 1
                if event.get("action") == "write" and device.get("type") in {
                    "joint", "velocity", "legged_base", "gripper", "dexterous_hand", "suction"
                }:
                    actuator_writes += 1
    return {
        "available": True,
        "kind_counts": dict(sorted(counts.items())),
        "device_actions": dict(sorted(devices.items())),
        "actuator_writes": actuator_writes,
    }


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:48] or "run"


def request_directory(request_id: str) -> Path:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise QueueError(f"invalid request id: {request_id!r}")
    return REQUESTS_ROOT / request_id


def render_prompt(request: dict[str, Any]) -> str:
    artifacts = "\n".join(f"- `{item['path']}`" for item in request["artifacts"])
    return f"""# Tool formulation request: {request['request_id']}

Task: `{request.get('task') or 'unknown'}`
Experiment: `{request['experiment']}`
Iteration: `{request['iteration']}`
Run status: `{request.get('run_status')}`

Diagnose the first causal failure using the referenced trace. Do not assume a new
tool is needed. If the failure is strategy, prompt, runtime, malformed use of an
existing tool, or failure to verify, return `no_tool` without editing the toolbox.

Artifacts:
{artifacts}

Follow `.cursor/skills/kinex-tool-formulator/SKILL.md` exactly. Return the final
object defined by `experiment/tool-formulator/schemas/result.schema.json`.
"""


def enqueue(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise QueueError(f"run directory does not exist: {run_dir}")
    manifest_path = run_dir / "trace-manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("native_success") is True:
        print(json.dumps({"enqueued": False, "reason": "native_success=true", "run_dir": relative(run_dir)}))
        return 0

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    request_id = args.id or f"{stamp}-{slug(str(manifest.get('task') or run_dir.name))}"
    destination = request_directory(request_id)
    if destination.exists():
        raise QueueError(f"request already exists: {destination}")
    destination.mkdir(parents=True)

    candidates = [
        manifest_path,
        run_dir / "harness-events.jsonl",
        run_dir / "harness-audit.json",
        run_dir / "agent" / "session.jsonl",
        run_dir / "agent" / "events.jsonl",
        run_dir / "agent" / "stderr.log",
        run_dir / "stop.json",
    ]
    artifacts = [record for path in candidates if (record := file_record(path))]
    registry = read_json(TOOLBOX_ROOT / "registry.json")
    request = {
        "schema": "kinex/tool-formulation-request/1",
        "request_id": request_id,
        "created_at": utc_now(),
        "state": "pending",
        "task": manifest.get("task"),
        "experiment": args.experiment,
        "iteration": args.iteration,
        "run_dir": relative(run_dir),
        "run_status": manifest.get("status"),
        "native_success": manifest.get("native_success"),
        "process_exit_code": manifest.get("process_exit_code"),
        "objective": "Diagnose the first causal failure and formulate the smallest reusable tool only if evidence proves a capability gap.",
        "artifacts": artifacts,
        "online_summary": online_summary(run_dir / "harness-events.jsonl"),
        "toolbox_snapshot": {
            "tool_count": registry.get("tool_count"),
            "tools": [
                {key: item.get(key) for key in ("name", "tool_type", "generality", "level", "dependencies", "summary")}
                for item in registry.get("tools", [])
                if isinstance(item, dict)
            ],
        },
    }
    write_json(destination / "request.json", request)
    (destination / "prompt.md").write_text(render_prompt(request), encoding="utf-8")
    write_json(destination / "status.json", {"state": "pending", "updated_at": utc_now()})
    print(json.dumps({"enqueued": True, "request_id": request_id, "path": relative(destination)}))
    return 0


def pending(args: argparse.Namespace) -> int:
    result = []
    if REQUESTS_ROOT.is_dir():
        for directory in sorted(path for path in REQUESTS_ROOT.iterdir() if path.is_dir()):
            try:
                status = read_json(directory / "status.json")
            except QueueError:
                continue
            if status.get("state") == "pending":
                result.append({"request_id": directory.name, "path": relative(directory)})
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for item in result:
            print(item["request_id"])
    return 0


def claim(args: argparse.Namespace) -> int:
    directory = request_directory(args.request_id)
    status_path = directory / "status.json"
    status = read_json(status_path)
    if status.get("state") != "pending":
        raise QueueError(f"request is not pending: {status.get('state')}")
    write_json(status_path, {"state": "running", "worker": args.worker, "updated_at": utc_now()})
    print(json.dumps({"claimed": True, "request_id": args.request_id}))
    return 0


def release(args: argparse.Namespace) -> int:
    directory = request_directory(args.request_id)
    status_path = directory / "status.json"
    status = read_json(status_path)
    if status.get("state") != "running":
        raise QueueError(f"request is not running: {status.get('state')}")
    if status.get("worker") != args.worker:
        raise QueueError(f"request is owned by another worker: {status.get('worker')!r}")
    write_json(status_path, {
        "state": "pending",
        "last_worker": args.worker,
        "last_error": args.reason,
        "updated_at": utc_now(),
    })
    print(json.dumps({"released": True, "request_id": args.request_id}))
    return 0


def validate_result(value: dict[str, Any]) -> None:
    decision = value.get("decision")
    if decision not in FINAL_DECISIONS:
        raise QueueError(f"invalid result decision: {decision!r}")
    diagnosis = value.get("diagnosis")
    if not isinstance(diagnosis, dict) or not isinstance(diagnosis.get("capability_gap"), bool):
        raise QueueError("result diagnosis.capability_gap must be boolean")
    if diagnosis.get("failure_type") not in FAILURE_TYPES:
        raise QueueError(f"invalid diagnosis.failure_type: {diagnosis.get('failure_type')!r}")
    if not isinstance(diagnosis.get("summary"), str) or not diagnosis["summary"].strip():
        raise QueueError("diagnosis.summary must be a non-empty string")
    if not isinstance(diagnosis.get("evidence"), list) or any(
        not isinstance(item, str) or not item.strip() for item in diagnosis["evidence"]
    ):
        raise QueueError("diagnosis.evidence must contain non-empty strings")
    tools = value.get("tools")
    if not isinstance(tools, list):
        raise QueueError("result tools must be an array")
    if decision in {"create_tool", "update_tool"} and not tools:
        raise QueueError(f"{decision} requires at least one tool")
    if decision in {"no_tool", "blocked"} and tools:
        raise QueueError(f"{decision} must not list changed tools")
    if decision == "no_tool" and diagnosis.get("capability_gap"):
        raise QueueError("no_tool cannot set capability_gap=true")
    if decision in {"create_tool", "update_tool"} and not diagnosis.get("capability_gap"):
        raise QueueError(f"{decision} requires capability_gap=true")
    for tool in tools:
        if not isinstance(tool, dict) or not TOOL_NAME_RE.fullmatch(str(tool.get("name", ""))):
            raise QueueError("each changed tool needs a valid snake_case name")
        expected_change = "created" if decision == "create_tool" else "updated"
        if tool.get("change") != expected_change:
            raise QueueError(f"{decision} requires change={expected_change}")
        for score in ("generality", "level"):
            if type(tool.get(score)) is not int or not 1 <= tool[score] <= 10:
                raise QueueError(f"tool {tool['name']} has invalid {score} score")
        for field in ("files", "tests"):
            if not isinstance(tool.get(field), list) or any(
                not isinstance(item, str) or not item.strip() for item in tool[field]
            ):
                raise QueueError(f"tool {tool['name']} has invalid {field}")
        if not (TOOLBOX_ROOT / "tools" / tool["name"]).is_dir():
            raise QueueError(f"reported tool directory is missing: {tool['name']}")
    validation = value.get("validation")
    if not isinstance(validation, dict) or not isinstance(validation.get("passed"), bool):
        raise QueueError("result validation.passed must be boolean")
    if not isinstance(validation.get("commands"), list) or any(
        not isinstance(item, str) or not item.strip() for item in validation["commands"]
    ):
        raise QueueError("result validation.commands must contain non-empty strings")
    if decision != "blocked" and not validation["passed"]:
        raise QueueError(f"{decision} requires validation.passed=true")
    if not isinstance(value.get("notes"), list) or any(
        not isinstance(item, str) for item in value["notes"]
    ):
        raise QueueError("result notes must be an array of strings")


def run_validation() -> tuple[bool, list[dict[str, Any]]]:
    commands = [
        [sys.executable, "toolbox/scripts/toolbox.py", "validate", "--write-registry"],
        [sys.executable, "-m", "unittest", "discover", "-s", "toolbox/tests", "-v"],
    ]
    results = []
    passed = True
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for command in commands:
        completed = subprocess.run(command, cwd=REPO_ROOT, env=environment, text=True, capture_output=True, check=False)
        results.append({
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-8000:],
        })
        passed = passed and completed.returncode == 0
    return passed, results


def complete(args: argparse.Namespace) -> int:
    directory = request_directory(args.request_id)
    status = read_json(directory / "status.json")
    if status.get("state") not in {"running", "pending"}:
        raise QueueError(f"request cannot be completed from state {status.get('state')!r}")
    result = read_json(Path(args.result).resolve())
    validate_result(result)
    passed, validation = run_validation()
    write_json(directory / "result.json", result)
    write_json(directory / "validation.json", {"passed": passed, "checks": validation, "updated_at": utc_now()})
    state = "completed" if passed else "validation_failed"
    write_json(directory / "status.json", {"state": state, "worker": status.get("worker"), "updated_at": utc_now()})
    print(json.dumps({"request_id": args.request_id, "state": state, "validation_passed": passed}))
    return 0 if passed else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("enqueue")
    create.add_argument("--run-dir", required=True)
    create.add_argument("--experiment", required=True)
    create.add_argument("--iteration", required=True)
    create.add_argument("--id")
    create.set_defaults(func=enqueue)
    listing = subparsers.add_parser("pending")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=pending)
    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("request_id")
    claim_parser.add_argument("--worker", required=True)
    claim_parser.set_defaults(func=claim)
    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("request_id")
    release_parser.add_argument("--worker", required=True)
    release_parser.add_argument("--reason", default="workstation invocation failed")
    release_parser.set_defaults(func=release)
    finish = subparsers.add_parser("complete")
    finish.add_argument("request_id")
    finish.add_argument("--result", required=True)
    finish.set_defaults(func=complete)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return int(args.func(args))
    except QueueError as exc:
        print(f"tool-formulator queue error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

