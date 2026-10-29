#!/usr/bin/env python3
"""Validate a read-only online-recorder smoke-test event stream."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ACTUATED_TYPES = {
    "joint",
    "velocity",
    "legged_base",
    "gripper",
    "dexterous_hand",
    "suction",
}


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        events.append(value)
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    args = parser.parse_args()

    events = load_events(args.events)
    counts = Counter(event.get("kind") for event in events)
    dispatches = [event for event in events if event.get("kind") == "device.dispatch"]
    observations = [event for event in events if event.get("kind") == "observation.created"]
    actuator_writes = [
        event
        for event in dispatches
        if event.get("action") == "write"
        and isinstance(event.get("device"), dict)
        and event["device"].get("type") in ACTUATED_TYPES
    ]
    camera_reads = [
        event
        for event in dispatches
        if event.get("action") == "read"
        and isinstance(event.get("device"), dict)
        and event["device"].get("type") in {"rgb", "rgbd"}
    ]
    sequences = [event.get("seq") for event in events]
    errors: list[str] = []
    if not events:
        errors.append("event stream is empty")
    if counts["harness.started"] != 1:
        errors.append(f"expected one harness.started event, got {counts['harness.started']}")
    if counts["harness.finished"] != 1:
        errors.append(f"expected one harness.finished event, got {counts['harness.finished']}")
    if not camera_reads:
        errors.append("no RGB/RGB-D device read was recorded")
    if not observations:
        errors.append("no observation.created event was recorded")
    if actuator_writes:
        errors.append(f"read-only test recorded {len(actuator_writes)} actuator write(s)")
    if counts["execution.receipt"]:
        errors.append(f"read-only test produced {counts['execution.receipt']} execution receipt(s)")
    if sequences != list(range(1, len(events) + 1)):
        errors.append("event sequence is not contiguous and monotonic")
    if any(event.get("mode") != "observe" for event in events):
        errors.append("one or more events were not recorded in observe mode")

    result = {
        "ok": not errors,
        "events": len(events),
        "kind_counts": dict(sorted(counts.items())),
        "camera_reads": len(camera_reads),
        "observations": len(observations),
        "actuator_writes": len(actuator_writes),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

