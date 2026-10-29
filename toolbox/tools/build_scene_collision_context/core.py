"""Build partial surface occupancy from measured registered RGB-D frames.

Only sensor returns are occupied. Occluded/invalid/filtered space stays unknown;
this is not a watertight object reconstruction or a free-space certificate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


_spec = importlib.util.spec_from_file_location(
    "scene_collision_geometry", Path(__file__).resolve().parents[1] / "check_joint_path_collision/core.py")
geometry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(geometry)


def _positive(value, low, high, label):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be in [{low},{high}]")
    return value


def depth_points(raw_depth, camera_profile, camera_pose_world, depth_range_m):
    """Pinhole optical +Z depth -> world points, without guessed calibration."""
    color = camera_profile["intrinsics"]["color"]
    depth_meta = camera_profile["intrinsics"]["depth"]
    p = color["projection"]
    if (p.get("model") != "pinhole" or color["distortion"].get("model") != "none"
            or depth_meta.get("quantity") != "z" or depth_meta.get("registration") != "color"):
        raise ValueError("requires undistorted pinhole, color-registered optical-Z depth")
    height, width = depth_meta["height"], depth_meta["width"]
    values = np.asarray(raw_depth)
    if (color["height"], color["width"]) != (height, width) or values.shape != (height, width):
        raise ValueError("depth image dimensions must match registered camera calibration")
    projection = geometry.vector([p.get(k) for k in ("fx", "fy", "cx", "cy", "skew")], 5, "projection")
    fx, fy, cx, cy, skew = projection
    if fx <= 0 or fy <= 0:
        raise ValueError("camera focal lengths must be positive")
    scale = _positive(depth_meta["scale_m_per_unit"], 1e-9, 1, "depth scale")
    minimum, maximum = geometry.vector(depth_range_m, 2, "depth_range_m")
    if not 0 < minimum < maximum:
        raise ValueError("depth_range_m requires 0 < minimum < maximum")
    z = values.astype(float)*scale
    mask = np.isfinite(z) & (values != depth_meta["invalid_value"]) & (z >= minimum) & (z <= maximum)
    v, u = np.nonzero(mask)
    yy = (v-cy)*z[mask]/fy
    xx = ((u-cx)*z[mask]-skew*yy)/fx
    points = np.column_stack((xx, yy, z[mask]))
    transform = geometry.pose_matrix(camera_pose_world)
    return points @ transform[:3, :3].T + transform[:3, 3], {
        "pixels_total": int(values.size), "valid_points": len(points),
        "invalid_or_range_filtered_pixels": int(values.size-len(points)),
        "reliable_range_m": depth_meta.get("reliable_range_m"),
        "camera_calibration_sha256": hashlib.sha256(json.dumps(camera_profile, sort_keys=True).encode()).hexdigest(),
    }


def remove_robot_returns(points, boxes):
    keep = np.ones(len(points), dtype=bool)
    for _, _, (center, rotation, half) in boxes:
        local = (points-center) @ rotation
        keep &= ~np.all(np.abs(local) <= half + 1e-10, axis=1)
    return points[keep], int((~keep).sum())


def voxel_obstacles(points, voxel_size_m, surface_uncertainty_m):
    if len(points) == 0:
        raise ValueError("no occupied surface points remain; empty map cannot establish clearance")
    grid = np.floor(points/voxel_size_m).astype(np.int64)
    cells, counts = np.unique(grid, axis=0, return_counts=True)
    if len(cells) > 12000:
        raise ValueError("map exceeds 12000 occupied cells; use a justified larger voxel size or bounded ROI")
    size = [float(voxel_size_m + 2*surface_uncertainty_m)]*3
    return [{"id": f"surface_voxel_{index}",
        "pose_world": [*((cell+.5)*voxel_size_m).tolist(), 0, 0, 0, 1],
        "size_m": size, "sensor_returns": int(count)}
        for index, (cell, count) in enumerate(zip(cells, counts))]


def build_context(*, observations, arm_models, arm_profiles, valid_for_s,
                  voxel_size_m, surface_uncertainty_m, depth_range_m,
                  max_snapshot_skew_s=0.1, roi_world_m=None):
    """Pure builder. Callers decode depth through the Kinex camera API."""
    voxel_size_m = _positive(voxel_size_m, .005, .1, "voxel_size_m")
    uncertainty = _positive(surface_uncertainty_m, 0, .05, "surface_uncertainty_m")
    valid_for_s = _positive(valid_for_s, .001, 30, "valid_for_s")
    skew_limit = _positive(max_snapshot_skew_s, 0, 1, "max_snapshot_skew_s")
    if not 1 <= len(observations) <= 8 or not 1 <= len(arm_models) <= 4:
        raise ValueError("requires 1-8 observations and 1-4 measured arm models")
    times = geometry.vector([item["observed_at_s"] for item in observations], len(observations), "observation times")
    if np.any(times < 0) or times.max()-times.min() > skew_limit:
        raise ValueError("camera snapshots exceed max_snapshot_skew_s or have negative times")
    ids = [item["observation_id"] for item in observations]
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("observation IDs must be unique non-empty strings")
    context = {"frame": "world", "provenance": "registered RGB-D measured surface voxels; public robot model self-filter",
        "based_on": ids, "observed_at_s": float(times.max()),
        "expires_at_s": float(times.min()+valid_for_s), "arms": {}, "obstacles": [],
        "_directory": str(Path.cwd()), "_sha256": "builder_in_memory"}
    if context["expires_at_s"] <= context["observed_at_s"]:
        raise ValueError("observation span exceeds scene validity")
    boxes = []
    for arm, model in arm_models.items():
        timestamp = float(model["measured_at_s"])
        if not math.isfinite(timestamp) or timestamp < 0 or max(abs(times-timestamp)) > skew_limit:
            raise ValueError(f"{arm} joint snapshot is not synchronized with camera frames")
        context["arms"][arm] = {"urdf_path": str(Path(model["urdf_path"]).expanduser().resolve()),
            "measured_joints": model["measured_joints"], "measured_at_s": timestamp}
    for arm, model in arm_models.items():
        checker = geometry.ArmCollisionChecker(arm, arm_profiles[arm], context,
            margin_m=uncertainty, check_self_collision=False)
        boxes.extend(checker.body_boxes(model["measured_joints"]))
    if roi_world_m is not None:
        low = geometry.vector(roi_world_m["min"], 3, "ROI min")
        high = geometry.vector(roi_world_m["max"], 3, "ROI max")
        if np.any(high <= low):
            raise ValueError("ROI max must exceed min on every axis")
    cloud, evidence = [], []
    for observation in observations:
        points, report = depth_points(observation["raw_depth"], observation["camera_profile"],
            observation["camera_pose_world"], depth_range_m)
        points, removed = remove_robot_returns(points, boxes)
        if roi_world_m is not None:
            keep = np.all((points >= low) & (points <= high), axis=1)
            roi_filtered = int((~keep).sum())
            points = points[keep]
        else:
            roi_filtered = 0
        cloud.append(points)
        evidence.append({**report, "camera": observation["camera"],
            "observation_id": observation["observation_id"], "observed_at_s": observation["observed_at_s"],
            "camera_pose_world": observation["camera_pose_world"],
            "depth_sha256": observation.get("depth_sha256"),
            "robot_filtered_points": removed, "roi_filtered_points": roi_filtered})
    context["obstacles"] = voxel_obstacles(np.concatenate(cloud), voxel_size_m, uncertainty)
    context["coverage"] = {"kind": "partial_observed_surfaces", "unobserved_space": "unknown",
        "occluded_space": "unknown", "robot_filtered_space": "unknown", "object_interiors": "unknown",
        "roi_world_m": roi_world_m, "voxel_size_m": voxel_size_m,
        "surface_uncertainty_m": uncertainty, "depth_range_m": depth_range_m,
        "ray_free_space_certified": False, "scene_complete": False,
        "warning": "Only measured surfaces are occupied; a clear sampled path can still traverse unobserved space. Robot bounds may also filter nearby object returns. Reobserve after scene-changing motion."}
    context["observations"] = evidence
    for key in ("_directory", "_sha256"):
        context.pop(key)
    return context
