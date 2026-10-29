"""Reusable RGB-D geometry estimation for a dominant-color tabletop object."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

LOCATE_DIR = Path(__file__).resolve().parents[1] / "locate_colored_object_3d"
sys.path.insert(0, str(LOCATE_DIR))
from color_geometry import (  # noqa: E402
    _largest_component,
    _mask_for_color,
    _quaternion_matrix,
    locate_colored_object,
    visible_world_points,
)


def _support_height(
    depth_raw: np.ndarray,
    component: np.ndarray,
    camera_profile: dict[str, Any],
) -> tuple[float, int, float]:
    """Estimate a horizontal local support plane from a ring around the mask."""
    outer = cv2.dilate(component.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool)
    inner = cv2.dilate(component.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    ring = outer & ~inner
    depth_profile = camera_profile["intrinsics"]["depth"]
    scale = float(depth_profile["scale_m_per_unit"])
    valid = ring & (depth_raw != int(depth_profile["invalid_value"]))
    ys, xs = np.where(valid)
    depths = depth_raw[ys, xs].astype(float) * scale
    limits = depth_profile["valid_range_m"]
    keep = (depths >= float(limits["min"])) & (depths <= float(limits["max"]))
    xs, ys, depths = xs[keep], ys[keep], depths[keep]
    if depths.size < 80:
        raise ValueError(f"only {depths.size} valid support-plane samples around the object")

    projection = camera_profile["intrinsics"]["color"]["projection"]
    camera_points = np.column_stack((
        (xs - float(projection["cx"])) * depths / float(projection["fx"]),
        (ys - float(projection["cy"])) * depths / float(projection["fy"]),
        depths,
    ))
    mount = camera_profile["extrinsics"]["mount"]
    rotation = _quaternion_matrix(mount["rotation_xyzw"])
    world_z = (camera_points @ rotation.T + np.asarray(mount["translation_m"], dtype=float))[:, 2]
    median = float(np.median(world_z))
    mad = float(np.median(np.abs(world_z - median)))
    tolerance = max(0.004, 3.0 * 1.4826 * mad)
    inliers = world_z[np.abs(world_z - median) <= tolerance]
    if inliers.size < 50:
        raise ValueError("support-plane estimate has too few inliers")
    return float(np.median(inliers)), int(inliers.size), mad


def _project_ray_to_z(point_world: np.ndarray, z: float, camera_profile: dict[str, Any]) -> np.ndarray:
    origin = np.asarray(camera_profile["extrinsics"]["mount"]["translation_m"], dtype=float)
    denominator = float(point_world[2] - origin[2])
    if abs(denominator) < 1e-6:
        raise ValueError("camera ray is parallel to the object center plane")
    factor = (float(z) - float(origin[2])) / denominator
    result = origin + factor * (point_world - origin)
    result[2] = float(z)
    return result


def estimate_geometry(
    color_bgr: np.ndarray,
    depth_raw: np.ndarray,
    camera_profile: dict[str, Any],
    color_name: str,
    min_area_px: int = 80,
) -> tuple[dict[str, Any], np.ndarray]:
    """Estimate a compact horizontal bounding prism from a calibrated RGB-D view."""
    located, annotated = locate_colored_object(
        color_bgr, depth_raw, camera_profile, color_name, min_area_px
    )
    component, _, _ = _largest_component(
        _mask_for_color(color_bgr, color_name), min_area_px
    )
    support_z, support_samples, support_mad = _support_height(
        depth_raw, component, camera_profile
    )
    points = visible_world_points(depth_raw, component, camera_profile)
    visible_top_z = float(np.quantile(points[:, 2], 0.99))
    height = visible_top_z - support_z
    if not 0.008 <= height <= 0.25:
        raise ValueError(f"estimated object height {height:.4f} m is implausible")
    center_z = support_z + height / 2.0
    visible_center = np.asarray(located["center"]["world_xyz_m"], dtype=float)
    center = _project_ray_to_z(visible_center, center_z, camera_profile)

    xy = points[:, :2]
    xy_centered = xy - np.median(xy, axis=0)
    _, eigenvectors = np.linalg.eigh(np.cov(xy_centered.T))
    major = eigenvectors[:, 1]
    if major[0] < 0 or (abs(major[0]) < 1e-9 and major[1] < 0):
        major = -major
    minor = np.array([-major[1], major[0]])
    major_projection = xy_centered @ major
    minor_projection = xy_centered @ minor
    major_extent = float(np.quantile(major_projection, 0.95) - np.quantile(major_projection, 0.05))
    minor_extent = float(np.quantile(minor_projection, 0.95) - np.quantile(minor_projection, 0.05))
    if major_extent < minor_extent:
        major, minor = minor, major
        major_extent, minor_extent = minor_extent, major_extent
    if not 0.005 <= minor_extent <= 0.25 or not 0.005 <= major_extent <= 0.40:
        raise ValueError(
            f"estimated footprint extents {major_extent:.4f} x {minor_extent:.4f} m are implausible"
        )

    cv2.putText(
        annotated,
        f"{major_extent:.3f} x {minor_extent:.3f} x {height:.3f} m",
        (8, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 0),
        1,
        cv2.LINE_AA,
    )
    result = {
        "found": True,
        "color": color_name,
        "frame": "world",
        "center_world_m": [round(float(x), 6) for x in center],
        "visible_surface_point_world_m": located["center"]["world_xyz_m"],
        "support_z_world_m": round(support_z, 6),
        "visible_top_z_world_m": round(visible_top_z, 6),
        "height_m": round(height, 6),
        "footprint": {
            "major_extent_m": round(major_extent, 6),
            "minor_extent_m": round(minor_extent, 6),
            "major_axis_world_xy": [round(float(x), 6) for x in major],
            "minor_axis_world_xy": [round(float(x), 6) for x in minor],
        },
        "preferred_closing_axis_world_xy": [round(float(x), 6) for x in minor],
        "support_samples": support_samples,
        "support_mad_m": round(support_mad, 6),
        "depth_samples": int(points.shape[0]),
        "method": "HSV component + calibrated RGB-D + local support ring + horizontal prism",
        "uncertainties": [
            "The footprint is inferred from visible surfaces and may be biased by occlusion.",
            "The center is a camera-ray intersection with the estimated half-height plane.",
        ],
    }
    return result, annotated
