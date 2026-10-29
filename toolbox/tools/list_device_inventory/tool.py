#!/usr/bin/env python3
"""List registered Kinex devices without recursively scanning the workspace."""

from kinex import fail, finish, profile

from core import device_root, summarize_device_profile


def main() -> None:
    root = device_root(__file__)
    try:
        names = sorted(path.name for path in root.iterdir() if (path / "profile.yaml").is_file())
        devices = [summarize_device_profile(profile(name)) for name in names]
        finish(
            {
                "count": len(devices),
                "devices": devices,
                "usage": (
                    "Select devices by device_id and type. activation_intent describes profile "
                    "startup intent, not proof that a driver is healthy; use device status/read next."
                ),
            }
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()

