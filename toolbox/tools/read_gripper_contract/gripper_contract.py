"""Profile-only helpers for extracting a gripper's executable contract."""

from __future__ import annotations

from typing import Any


def gripper_contract(profile: dict[str, Any], arm: str | None = None) -> dict[str, Any]:
    """Return normalized limits, geometry axes, mounting, and TCP information."""
    if profile.get("type") != "gripper":
        raise ValueError("device profile must have type=gripper")
    intrinsics = profile["intrinsics"]
    control = intrinsics["control"]
    bounds = control["bounds"]
    aperture = intrinsics["aperture_m"]
    mount = profile["extrinsics"]["mount"]
    if arm is not None and mount.get("parent") != arm:
        raise ValueError(
            f'gripper is mounted to {mount.get("parent")!r}, not requested arm {arm!r}'
        )
    tcp = intrinsics["frames"]["tcp"]
    geometry = intrinsics["geometry"]

    low, high = float(bounds["min"]), float(bounds["max"])
    opened, closed = float(control["open_target"]), float(control["close_target"])
    if not low <= opened <= high or not low <= closed <= high:
        raise ValueError("profile open/close targets fall outside control bounds")
    return {
        "gripper": profile["name"],
        "mounted_arm": mount.get("parent"),
        "mount_parent_frame": mount.get("parent_frame"),
        "control": {
            "mode": control.get("mode"),
            "units": control.get("units"),
            "bounds": {"min": low, "max": high},
            "open_target": opened,
            "close_target": closed,
        },
        "aperture_m": {
            "min": float(aperture["min"]),
            "max": float(aperture["max"]),
        },
        "tcp_in_gripper_mount": {
            "translation_m": [float(x) for x in tcp["translation_m"]],
            "rotation_xyzw": [float(x) for x in tcp["rotation_xyzw"]],
        },
        "geometry": {
            "approach_axis_local": [float(x) for x in geometry["approach_axis"]],
            "closing_axis_local": [float(x) for x in geometry["closing_axis"]],
            "description": geometry.get("description"),
        },
    }
