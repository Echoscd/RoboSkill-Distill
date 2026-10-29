"""Deterministic geometry tests; temporary inputs never enter agent prompts."""

import importlib.util
import json
from pathlib import Path
import struct
import tempfile

import numpy as np


SPEC = importlib.util.spec_from_file_location("collision_test_core", Path(__file__).with_name("core.py"))
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def fixture(directory):
    path = Path(directory)
    # A thin radial bar with center x=1; its sweep intersects the obstacle at pi/2.
    (path / "robot.urdf").write_text('''<robot name="test"><link name="base"/>
      <link name="bar"><collision><origin xyz="1 0 0"/>
        <geometry><box size="0.6 0.1 0.1"/></geometry></collision></link>
      <joint name="hinge" type="revolute"><parent link="base"/><child link="bar"/>
        <origin xyz="0 0 0"/><axis xyz="0 0 1"/></joint></robot>''', encoding="utf-8")
    profile = {"intrinsics": {"model": {"format": "serial_chain",
        "joints": [{"name": "hinge", "type": "revolute", "limits": {"min": -4, "max": 4}}],
        "chain": [{"joint": 0, "origin": [0, 0, 0, 0, 0, 0, 1],
            "axis": [0, 0, 1], "anchor": [0, 0, 0], "reference": 0}]}},
        "extrinsics": {"mount": {"parent": "world", "translation_m": [0, 0, 0], "rotation_xyzw": [0, 0, 0, 1]}}}
    context = {"frame": "world", "provenance": "synthetic regression", "based_on": ["fixture"],
        "observed_at_s": 0, "expires_at_s": 100, "arms": {"arm": {"urdf_path": "robot.urdf"}},
        "obstacles": [{"id": "block", "pose_world": [0, 1, 0, 0, 0, 0, 1], "size_m": [.1, .1, .2]}]}
    (path / "scene.json").write_text(json.dumps(context), encoding="utf-8")
    return profile, core.load_context(str(path / "scene.json"))


def test_rotated_separating_axis_and_touching():
    rotation = core.pose_matrix([0, 0, 0, 0, 0, np.sin(np.pi/8), np.cos(np.pi/8)])[:3, :3]
    a = (np.zeros(3), rotation, np.array([1, .1, .1]))
    assert core.boxes_overlap(a, (np.array([.5, .5, 0]), np.eye(3), np.array([.1]*3)))
    assert not core.boxes_overlap(a, (np.array([0, .8, 0]), np.eye(3), np.array([.1]*3)))
    assert core.boxes_overlap((np.zeros(3), np.eye(3), np.ones(3)), (np.array([2, 0, 0]), np.eye(3), np.ones(3)))


def test_convex_narrow_phase_separates_overlapping_bounds():
    triangle = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    other = np.array([[.8, .8, 0], [1.8, .8, 0], [.8, 1.8, 0]])
    assert not core.convex_overlap(triangle, other, 0, 0)
    assert core.convex_overlap(triangle, triangle, 0, 0)
    assert core.convex_overlap(triangle, other, .4, .4)


def test_segment_collision_with_clear_endpoints_and_no_motion():
    with tempfile.TemporaryDirectory() as directory:
        profile, context = fixture(directory)
        checker = core.ArmCollisionChecker("arm", profile, context, margin_m=0)
        assert checker.check([0], [{"stage": "same", "joints": [0]}])["collision_free_at_samples"]
        assert checker.check([np.pi], [{"stage": "same", "joints": [np.pi]}])["collision_free_at_samples"]
        result = checker.check([0], [{"stage": "sweep", "joints": [np.pi]}])
        assert not result["collision_free_at_samples"]
        assert result["first_overlap"]["stage"] == "sweep"
        assert result["first_overlap"]["obstacle_id"] == "block"
        assert 0 < result["first_overlap"]["segment_fraction"] < 1
        assert result["execution_validated"] is None


def test_bad_inputs_never_become_clear():
    with tempfile.TemporaryDirectory() as directory:
        profile, context = fixture(directory)
        checker = core.ArmCollisionChecker("arm", profile, context)
        for q in ([float("nan")], [5], [0, 0]):
            try:
                checker.check(q, [{"stage": "action", "joints": [0]}])
            except ValueError:
                continue
            raise AssertionError("malformed joint positions accepted")
        for patch in ({"obstacles": []}, {"frame": "camera"}, {"expires_at_s": -1}, {"provenance": ""}):
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({**context, **patch}), encoding="utf-8")
            try:
                core.load_context(str(path))
            except ValueError:
                continue
            raise AssertionError("malformed scene accepted")
        profile["intrinsics"]["model"]["chain"][0]["origin"][0] = 1
        try:
            core.ArmCollisionChecker("arm", profile, context)
        except ValueError as exc:
            assert "mismatch" in str(exc)
        else:
            raise AssertionError("mismatched URDF/profile accepted")


def test_binary_and_ascii_stl_bounds():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "mesh.stl"
        vertices = [0, 0, 0, 2, 0, 0, 0, 3, 1]
        path.write_bytes(b"fixture".ljust(80, b"\0") + struct.pack("<I", 1)
            + struct.pack("<12fH", 0, 0, 1, *vertices, 0))
        low, high = core.stl_bounds(path)
        assert np.allclose(low, [0, 0, 0]) and np.allclose(high, [2, 3, 1])
        path.write_text("solid\n vertex 0 0 0\n vertex 2 0 0\n vertex 0 3 1\nendsolid", encoding="ascii")
        assert np.allclose(core.stl_bounds(path)[1], high)


def test_padding_increases_conservative_rejection():
    with tempfile.TemporaryDirectory() as directory:
        profile, context = fixture(directory)
        context["obstacles"][0]["pose_world"] = [1, .12, 0, 0, 0, 0, 1]
        clear = core.ArmCollisionChecker("arm", profile, context, margin_m=0).check([0], [{"stage": "hold", "joints": [0]}])
        padded = core.ArmCollisionChecker("arm", profile, context, margin_m=.03).check([0], [{"stage": "hold", "joints": [0]}])
        assert clear["collision_free_at_samples"] and not padded["collision_free_at_samples"]


def test_inter_arm_static_snapshot_collisions_and_separation():
    import copy
    with tempfile.TemporaryDirectory() as directory:
        profile, context = fixture(directory)
        context["arms"]["other"] = {"urdf_path": "robot.urdf"}
        states = {"other": {"positions": [0], "timestamp": 1}}
        checker = core.ArmCollisionChecker("arm", profile, context, other_arm_profiles={"other": profile}, other_arm_states=states)
        hit = checker.check([0], [{"stage": "hold", "joints": [0]}])
        assert hit["first_overlap"]["collision_type"] == "inter_arm"
        assert hit["first_overlap"]["other_arm"] == "other"
        other_profile = copy.deepcopy(profile)
        other_profile["extrinsics"]["mount"]["translation_m"] = [5, 0, 0]
        clear = core.ArmCollisionChecker("arm", profile, context, other_arm_profiles={"other": other_profile}, other_arm_states=states).check([0], [{"stage": "hold", "joints": [0]}])
        assert clear["collision_free_at_samples"] and clear["inter_arm_collision_checked"]
        assert clear["unmodeled_arms"] == []


def test_self_collision_nonadjacent_links_and_adjacent_exclusion():
    import copy
    with tempfile.TemporaryDirectory() as directory:
        profile, context = fixture(directory)
        context["obstacles"][0]["pose_world"][1] = 10
        links = ''.join(f'<link name="bar{i}"><collision><origin xyz="1 0 0"/><geometry><box size=".6 .1 .1"/></geometry></collision></link>' for i in range(3))
        joints = ''.join(f'<joint name="hinge{i}" type="revolute"><parent link="{("base" if i == 0 else "bar"+str(i-1))}"/><child link="bar{i}"/><origin xyz="0 0 0"/><axis xyz="0 0 1"/></joint>' for i in range(3))
        (Path(directory)/"robot.urdf").write_text('<robot name="self"><link name="base"/>'+links+joints+'</robot>', encoding="utf-8")
        joint = profile["intrinsics"]["model"]["joints"][0]
        chain = profile["intrinsics"]["model"]["chain"][0]
        profile["intrinsics"]["model"]["joints"] = [{**copy.deepcopy(joint), "name": f"hinge{i}"} for i in range(3)]
        profile["intrinsics"]["model"]["chain"] = [{**copy.deepcopy(chain), "joint": i} for i in range(3)]
        hit = core.ArmCollisionChecker("arm", profile, context).check([0]*3, [{"stage": "hold", "joints": [0]*3}])
        assert hit["first_overlap"]["collision_type"] == "self"
        assert {hit["first_overlap"]["link"], hit["first_overlap"]["other_link"]} == {"bar0", "bar2"}
        profile["intrinsics"]["model"]["joints"] = profile["intrinsics"]["model"]["joints"][:2]
        profile["intrinsics"]["model"]["chain"] = profile["intrinsics"]["model"]["chain"][:2]
        assert core.ArmCollisionChecker("arm", profile, context).check([0]*2, [{"stage": "hold", "joints": [0]*2}])["collision_free_at_samples"]
