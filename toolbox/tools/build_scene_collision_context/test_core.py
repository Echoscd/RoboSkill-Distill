"""Measured-depth, unknown-coverage and collision-composition regressions."""

import importlib.util
import json
from pathlib import Path
import tempfile

import numpy as np


SPEC = importlib.util.spec_from_file_location("scene_builder_test", Path(__file__).with_name("core.py"))
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def fixture():
    profile = {"intrinsics": {
        "color": {"width": 2, "height": 2, "projection": {"model": "pinhole", "fx": 1, "fy": 1, "cx": 0, "cy": 0, "skew": 0}, "distortion": {"model": "none"}},
        "depth": {"width": 2, "height": 2, "quantity": "z", "registration": "color", "scale_m_per_unit": .001, "invalid_value": 0, "reliable_range_m": "???"}}}
    return profile


def test_projection_scale_invalids_and_camera_transform():
    p, report = core.depth_points(np.array([[1000, 0], [2000, 10000]]), fixture(), [1, 2, 3, 0, 0, 0, 1], [.1, 3])
    assert np.allclose(p, [[1, 2, 4], [1, 4, 5]])
    assert report["invalid_or_range_filtered_pixels"] == 2
    assert report["reliable_range_m"] == "???"
    profile = fixture()
    profile["intrinsics"]["depth"]["registration"] = "unaligned"
    try:
        core.depth_points(np.zeros((2, 2)), profile, [0, 0, 0, 0, 0, 0, 1], [.1, 3])
    except ValueError:
        pass
    else:
        raise AssertionError("unaligned depth accepted")


def test_robot_return_filter_and_boundary_voxels():
    points = np.array([[0, 0, 0], [.3, 0, 0], [-.01, .03, 1]])
    remaining, removed = core.remove_robot_returns(points, [(0, "link", (np.zeros(3), np.eye(3), np.ones(3)*.1))])
    assert removed == 1 and len(remaining) == 2
    voxels = core.voxel_obstacles(remaining, .02, .005)
    assert len(voxels) == 2
    assert all(np.allclose(v["size_m"], [.03]*3) for v in voxels)
    assert min(v["pose_world"][0] for v in voxels) < 0  # floor, not truncation


def test_builder_preserves_unknowns_and_rejects_unsynchronized_inputs():
    geometry_test = Path(__file__).resolve().parents[1] / "check_joint_path_collision/test_core.py"
    spec = importlib.util.spec_from_file_location("scene_fixture", geometry_test)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with tempfile.TemporaryDirectory() as directory:
        arm_profile, _ = helper.fixture(directory)
        observation = {"camera": "camera", "observation_id": "fixture", "observed_at_s": 1,
            "camera_profile": fixture(), "camera_pose_world": [0, 0, 0, 0, 0, 0, 1],
            "raw_depth": np.ones((2, 2))*1000}
        models = {"arm": {"urdf_path": str(Path(directory)/"robot.urdf"), "measured_joints": [0], "measured_at_s": 1}}
        values = dict(observations=[observation], arm_models=models, arm_profiles={"arm": arm_profile},
            valid_for_s=5, voxel_size_m=.02, surface_uncertainty_m=.005, depth_range_m=[.1, 3])
        scene = core.build_context(**values)
        assert scene["coverage"]["scene_complete"] is False
        assert scene["coverage"]["unobserved_space"] == "unknown"
        assert scene["expires_at_s"] == 6 and len(scene["obstacles"]) == 4
        path = Path(directory)/"map.json"
        path.write_text(json.dumps(scene), encoding="utf-8")
        checked = core.geometry.load_context(str(path))
        # Place a declared arm link exactly on a measured voxel, closing builder -> checker.
        arm_profile["extrinsics"]["mount"]["translation_m"] = [-1, 0, 1]
        checker = core.geometry.ArmCollisionChecker("arm", arm_profile, checked, margin_m=0)
        collision = checker.check([0], [{"stage": "hold", "joints": [0]}])
        assert not collision["collision_free_at_samples"]
        assert collision["first_overlap"]["collision_type"] == "environment"
        assert collision["scene_coverage"]["unobserved_space"] == "unknown"
        models["arm"]["measured_at_s"] = 0
        try:
            core.build_context(**values)
        except ValueError as exc:
            assert "synchronized" in str(exc)
        else:
            raise AssertionError("unsynchronized arm data accepted")


def test_empty_surface_does_not_become_free_space():
    for points in (np.empty((0, 3)),):
        try:
            core.voxel_obstacles(points, .02, .005)
        except ValueError:
            pass
        else:
            raise AssertionError("empty surface certified")


def test_entrypoint_decodes_pgm_and_preserves_existing_artifacts():
    import runpy
    import sys
    import types
    spec = importlib.util.spec_from_file_location("entry_fixture", Path(__file__).resolve().parents[1]/"check_joint_path_collision/test_core.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    camera_spec = importlib.util.spec_from_file_location("kinex.camera", Path(__file__).resolve().parents[3]/"packages/core/assets/python/kinex/camera.py")
    camera = importlib.util.module_from_spec(camera_spec)
    camera_spec.loader.exec_module(camera)
    with tempfile.TemporaryDirectory() as directory:
        arm_profile, _ = helper.fixture(directory)
        camera_profile = fixture()
        camera_profile["intrinsics"]["depth"].update({"pixel_format": "uint16", "image_format": "pgm16_be"})
        depth = Path(directory)/"frame.pgm"
        depth.write_bytes(b"P5\n2 2\n65535\n"+np.full((2, 2), 1000, dtype=">u2").tobytes())
        target = Path(directory)/"context.json"
        values = {"observations": [{"camera": "cam", "depth_path": str(depth), "observation_id": "fixture",
            "observed_at_s": 1, "camera_pose_world": [0, 0, 0, 0, 0, 0, 1]}],
            "arm_models": {"arm": {"urdf_path": str(Path(directory)/"robot.urdf"), "measured_joints": [0], "measured_at_s": 1}},
            "output_path": str(target), "valid_for_s": 5, "surface_uncertainty_m": 0, "depth_range_m": [.1, 3]}
        kinex = types.ModuleType("kinex")
        kinex.args = lambda: values
        kinex.profile = lambda name: camera_profile if name == "cam" else arm_profile
        results = []
        kinex.finish = results.append
        def fail(message):
            raise ValueError(message)
        kinex.fail = fail
        modules = {name: sys.modules.get(name) for name in ("kinex", "kinex.camera", "core")}
        sys.modules.update({"kinex": kinex, "kinex.camera": camera, "core": core})
        try:
            runpy.run_path(str(Path(__file__).with_name("tool.py")))
            original = target.read_bytes()
            assert results[0]["obstacle_count"] == 4
            assert json.loads(original)["observations"][0]["depth_sha256"]
            try:
                runpy.run_path(str(Path(__file__).with_name("tool.py")))
            except ValueError as exc:
                assert "new file" in str(exc)
            else:
                raise AssertionError("existing map overwritten")
            assert target.read_bytes() == original
        finally:
            for name, previous in modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous
