"""Normalize device profiles into a bounded model-facing inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def device_root(tool_file: str) -> Path:
    """Resolve the active .kinex/devices directory from the installed tool path."""
    path = Path(tool_file).resolve()
    try:
        kinex_root = path.parents[2]
    except IndexError as exc:
        raise ValueError(f"tool path is not installed under .kinex/tools: {path}") from exc
    if kinex_root.name != ".kinex":
        raise ValueError(f"tool path is not installed under .kinex/tools: {path}")
    return kinex_root / "devices"


def summarize_device_profile(value: dict[str, Any]) -> dict[str, Any]:
    name = value.get("name")
    device_type = value.get("type")
    if not isinstance(name, str) or not name:
        raise ValueError("device profile has no name")
    if not isinstance(device_type, str) or not device_type:
        raise ValueError(f"device profile {name!r} has no type")
    driver = value.get("access", {}).get("driver", {})
    actions = driver.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    return {
        "device_id": name,
        "type": device_type,
        "activation_intent": bool(value.get("loaded", False)),
        "actions": sorted(str(action) for action in actions if isinstance(action, str)),
        "connection_kind": value.get("access", {}).get("connection", {}).get("kind"),
    }

