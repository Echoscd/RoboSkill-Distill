#!/usr/bin/env python3
"""Materialize the simulator's terminal verdict as the sole task-success label."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


SCHEMA = "kinex/simulator-verdict/1"


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def first_file(root: Path, pattern: str) -> Path | None:
    return next((path for path in root.glob(pattern) if path.is_file()), None)


def bool_value(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def evaluate(run_dir: Path) -> dict[str, Any]:
    native_path = first_file(run_dir, "**/evidence/native-episode.json")
    stop_path = run_dir / "stop.json"
    native = read_json(native_path)
    stop = read_json(stop_path)
    simulation = stop.get("simulation") if isinstance(stop.get("simulation"), dict) else {}

    candidates = {
        "stop.simulation.success": bool_value(simulation.get("success")),
        "native_episode.native_success": bool_value(native.get("native_success")),
        "native_episode.success_latched": bool_value(native.get("success_latched")),
    }
    observed = {name: value for name, value in candidates.items() if value is not None}
    conflicts = len(set(observed.values())) > 1
    terminal = bool_value(simulation.get("terminal"))
    submitted = bool_value(native.get("submitted"))

    if conflicts or not observed:
        success = None
    elif terminal is not True and submitted is not True:
        success = None
    else:
        success = next(iter(observed.values()))

    return {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "authority": "roboenv_native_evaluator",
        "agent_claim_used": False,
        "success": success,
        "verdict": "success" if success is True else "failure" if success is False else "unknown",
        "terminal": terminal,
        "submitted": submitted,
        "conflict": conflicts,
        "sources": {
            "stop_receipt": str(stop_path.relative_to(run_dir)) if stop_path.is_file() else None,
            "native_episode": str(native_path.relative_to(run_dir)) if native_path else None,
            "candidates": candidates,
        },
        "issues": [
            *(["simulator_verdict_conflict"] if conflicts else []),
            *(["simulator_verdict_missing"] if not observed else []),
            *(
                ["simulator_not_terminal_or_submitted"]
                if terminal is not True and submitted is not True
                else []
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    output = args.output.resolve() if args.output else run_dir / "simulator-verdict.json"
    result = evaluate(run_dir)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
