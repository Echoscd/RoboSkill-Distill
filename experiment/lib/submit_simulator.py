#!/usr/bin/env python3
"""Submit RoboEnv's one-shot evaluator while retaining the frozen scene for diagnosis."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from roboenv.client import Client
from roboenv.environment import _record


class OwnerEvaluationClient(Client):
    """Owner-only client used by the experiment supervisor, never the model."""

    allowed_ops = Client.allowed_ops | {"submit"}


def capture_submission_observation(client: OwnerEvaluationClient) -> dict[str, Any]:
    """Capture the scene immediately before the one-shot native submission."""

    try:
        client.request(
            "devices.call",
            {"device": "head_camera", "action": "load", "args": {}},
            timeout=30,
        )
        reading = client.request(
            "devices.call",
            {"device": "head_camera", "action": "read", "args": {}},
            timeout=30,
        )
    except Exception as error:  # The evaluator must still run if evidence capture fails.
        return {
            "device": "head_camera",
            "available": False,
            "error": f"{type(error).__name__}: {error}",
        }

    data = reading.get("data") if isinstance(reading, dict) else None
    data = data if isinstance(data, dict) else {}
    return {
        "device": "head_camera",
        "available": bool(data.get("file")),
        "file": data.get("file"),
        "depth_file": data.get("depth_file"),
        "timestamp": data.get("timestamp"),
    }


def submit(run_json: Path) -> dict[str, Any]:
    record = _record(run_json, project=None)
    client = OwnerEvaluationClient(
        record["socket"],
        session=record["session"],
        generation=record["generation"],
    )
    submission_observation = capture_submission_observation(client)
    result = client.request("submit", timeout=240)
    success = result.get("completed") if isinstance(result.get("completed"), bool) else None
    issues = [] if success is not None else ["simulator_verdict_missing"]
    if not submission_observation.get("available"):
        issues.append("submission_observation_missing")
    return {
        "schema": "kinex/simulator-verdict/1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "authority": "roboenv_native_evaluator",
        "agent_claim_used": False,
        "success": success,
        "verdict": "success" if success is True else "failure" if success is False else "unknown",
        "terminal": True,
        "submitted": result.get("submitted") is True,
        "conflict": False,
        "sources": {
            "submission": "owner_submit",
            "session": record["session"],
            "generation": record["generation"],
        },
        "submission_observation": submission_observation,
        "native_result": result,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = submit(args.run.resolve())
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
