"""Offline-only replay of the archived turn-switch approach, with no device I/O.

Usage: python test_recorded_regression.py --run-dir RECORDED_RUN --urdf PUBLIC_URDF
The table geometry below is an evidence fixture from the native scene source.
It is never installed as live agent geometry or exposed as a prompt example.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

import numpy as np


def replay(run_dir, urdf):
    import yaml
    spec = importlib.util.spec_from_file_location("recorded_collision_core", Path(__file__).with_name("core.py"))
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    native = Path(run_dir) / "roboenv" / "945616f75c9d7b58"
    profile = yaml.safe_load((native / "devices/left_arm/profile.yaml").read_text())
    target = [-.9441592, -2.0372042, -1.3459355, -.7098888, -.9009426, 1.5474096]
    context = {"frame": "world", "provenance": "OFFLINE REGRESSION ONLY: original native table box",
        "based_on": ["recorded_scene_fixture"], "observed_at_s": 0, "expires_at_s": 100,
        "arms": {"left_arm": {"urdf_path": str(Path(urdf).resolve())}},
        "obstacles": [{"id": "recorded_tabletop", "pose_world": [0, 0, .715, 0, 0, 0, 1], "size_m": [1.2, .7, .05]}]}
    with tempfile.TemporaryDirectory() as directory:
        context_path = Path(directory) / "scene.json"
        context_path.write_text(json.dumps(context), encoding="utf-8")
        checker = core.ArmCollisionChecker("left_arm", profile, core.load_context(str(context_path)), margin_m=0)
        home = checker.check([0]*6, [{"stage": "hold", "joints": [0]*6}])
        padded_environment_home = core.ArmCollisionChecker("left_arm", profile, core.load_context(str(context_path)),
            margin_m=.015, robot_pair_margin_m=0).check([0]*6, [{"stage": "hold", "joints": [0]*6}])
        path = checker.check([0]*6, [{"stage": "approach", "joints": target}])
        endpoint = checker.check(target, [{"stage": "hold", "joints": target}])
        assert home["collision_free_at_samples"]
        assert padded_environment_home["collision_free_at_samples"]
        assert not path["collision_free_at_samples"]
        assert not endpoint["collision_free_at_samples"]
        # Independently inspect actual link3 STL vertices (not only its OBB).
        mesh = Path(urdf).parent / "aloha_maniskill_sim/meshes/link3.STL"
        data = mesh.read_bytes()
        vertices = np.frombuffer(data, dtype=np.dtype([
            ("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")
        ]), offset=84)["vertices"].reshape(-1, 3)
        transform = checker.link_transforms(target)[2]
        points = vertices @ transform[:3, :3].T + transform[:3, 3]
        inside = np.all((points >= [-.6, -.35, .69]) & (points <= [.6, .35, .74]), axis=1)
        assert inside.any()
        return {"regression": "recorded_turn_switch_approach", "device_writes": 0,
            "home_clear": home["collision_free_at_samples"], "path": path, "endpoint": endpoint,
            "home_clear_with_environment_padding_0_015_m": padded_environment_home["collision_free_at_samples"],
            "actual_link3_vertices_inside_table": int(inside.sum()),
            "example_vertex_world_m": points[inside][0].tolist(),
            "scope_note": "Offline geometry confirms endpoint penetration; exact first runtime contact pair remains unrecorded."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--urdf", required=True)
    values = parser.parse_args()
    print(json.dumps(replay(values.run_dir, values.urdf), indent=2))
