"""Unit tests for device inventory normalization."""

from core import device_root, summarize_device_profile


def test_resolves_workspace_from_installed_tool_path() -> None:
    result = device_root("/tmp/workspace/.kinex/tools/list_device_inventory/tool.py")
    assert result.name == "devices"
    assert result.parent.name == ".kinex"
    assert result.parent.parent.name == "workspace"


def test_normalizes_bounded_inventory_fields() -> None:
    result = summarize_device_profile(
        {
            "name": "detector",
            "type": "detection",
            "loaded": False,
            "access": {
                "connection": {"kind": "process", "secret": "not exposed"},
                "driver": {"actions": ["detect", "load", "status"]},
            },
            "intrinsics": {"weights": "/private/checkpoint"},
        }
    )
    assert result == {
        "device_id": "detector",
        "type": "detection",
        "activation_intent": False,
        "actions": ["detect", "load", "status"],
        "connection_kind": "process",
    }


def test_rejects_profiles_without_identity() -> None:
    try:
        summarize_device_profile({"type": "rgbd"})
    except ValueError as exc:
        assert "no name" in str(exc)
    else:
        raise AssertionError("missing device name was accepted")

