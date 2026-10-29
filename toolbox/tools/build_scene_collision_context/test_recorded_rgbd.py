"""Offline real-depth decoding/projection/voxel smoke, with no device I/O.

This checks recorded pixels and static camera calibration only. It does not
fabricate synchronized robot state for a full map-building test.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def replay(repo, run_dir):
    import yaml
    repo, run = Path(repo).resolve(), Path(run_dir).resolve()
    sys.path.insert(0, str(repo / "packages/core/assets/python"))
    from kinex.camera import read_depth
    spec = importlib.util.spec_from_file_location("recorded_scene_builder", Path(__file__).with_name("core.py"))
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    observation = next(value for line in (run / "harness-events.jsonl").read_text().splitlines()
        if (value := json.loads(line)).get("kind") == "observation.created"
        and value.get("device_type") == "rgbd"
        and value.get("payload", {}).get("data", {}).get("depth_file"))
    native = next((run / "roboenv").iterdir())
    camera = observation["device_id"]
    profile = yaml.safe_load((native / "devices" / camera / "profile.yaml").read_text())
    mount = profile["extrinsics"]["mount"]
    assert mount["parent"] == "world"  # No fabricated moving-camera snapshot.
    source = Path(observation["payload"]["data"]["depth_file"])
    path = source if source.is_file() else native / "evidence/captures" / source.name
    meta = profile["intrinsics"]["depth"]
    width, height, raw = read_depth(str(path), meta)
    points, evidence = core.depth_points(np.asarray(raw).reshape(height, width), profile,
        [*mount["translation_m"], *mount["rotation_xyzw"]],
        [meta["valid_range_m"]["min"], meta["valid_range_m"]["max"]])
    # Zero inflation is an arithmetic test, not a claim of exact sensor geometry.
    obstacles = core.voxel_obstacles(points, .02, 0)
    assert points.size and obstacles
    return {"test": "retained_rgbd_projection_smoke", "device_writes": 0,
        "observation_id": observation["observation_id"], "observed_at_s": observation["acquired_at_s"],
        "depth_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "shape": [height, width], "evidence": evidence, "surface_voxel_count": len(obstacles),
        "limitations": "No synchronized retained joint state was supplied; robot filtering and full context composition are tested separately with synthetic synchronized fixtures. Unobserved space stays unknown."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-dir", required=True)
    values = parser.parse_args()
    print(json.dumps(replay(values.repo, values.run_dir), indent=2))
