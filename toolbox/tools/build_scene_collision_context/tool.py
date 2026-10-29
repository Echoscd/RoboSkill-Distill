#!/usr/bin/env python3
"""Decode recorded RGB-D depth, build a partial map and save a new artifact."""

import hashlib
import json
from pathlib import Path

import numpy as np

from kinex import args, fail, finish, profile
from kinex.camera import read_depth

from core import build_context


def main():
    values = args()
    try:
        destination = Path(values["output_path"]).expanduser().resolve()
        if destination.exists() or not destination.parent.is_dir():
            raise ValueError("output_path must be a new file in an existing directory")
        observations = []
        for item in values["observations"]:
            camera_profile = profile(item["camera"])
            width, height, pixels = read_depth(item["depth_path"], camera_profile["intrinsics"]["depth"])
            observations.append({**item, "camera_profile": camera_profile,
                "raw_depth": np.asarray(pixels).reshape(height, width),
                "depth_sha256": hashlib.sha256(Path(item["depth_path"]).read_bytes()).hexdigest()})
        context = build_context(
            observations=observations, arm_models=values["arm_models"],
            arm_profiles={arm: profile(arm) for arm in values["arm_models"]},
            valid_for_s=values["valid_for_s"], voxel_size_m=values.get("voxel_size_m", .02),
            surface_uncertainty_m=values["surface_uncertainty_m"], depth_range_m=values["depth_range_m"],
            max_snapshot_skew_s=values.get("max_snapshot_skew_s", .1), roi_world_m=values.get("roi_world_m"))
        payload = json.dumps(context, allow_nan=False, separators=(",", ":"))
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        finish({"collision_context_path": str(destination), "obstacle_count": len(context["obstacles"]),
            "based_on": context["based_on"], "observed_at_s": context["observed_at_s"],
            "expires_at_s": context["expires_at_s"], "coverage": context["coverage"],
            "observations": context["observations"], "device_writes": 0})
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
