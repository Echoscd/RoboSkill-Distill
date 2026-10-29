"""Deterministic RGB-D color grounding helpers."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


HSV_RANGES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]] | tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "green": ((35, 50, 25), (100, 255, 255)),
    "red": ((0, 70, 40), (12, 255, 255), (168, 70, 40), (179, 255, 255)),
    "blue": ((90, 60, 30), (135, 255, 255)),
    "yellow": ((20, 60, 50), (38, 255, 255)),
    "orange": ((5, 80, 50), (25, 255, 255)),
    "white": ((0, 0, 150), (179, 70, 255)),
    "black": ((0, 0, 0), (179, 255, 70)),
}


def _mask_for_color(bgr: np.ndarray, color: str) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    bounds = HSV_RANGES[color]
    mask = cv2.inRange(hsv, np.array(bounds[0]), np.array(bounds[1]))
    if len(bounds) == 4:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(bounds[2]), np.array(bounds[3])))
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def _largest_component(mask: np.ndarray, min_area_px: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        raise ValueError("no colored component found")
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    selected = {index}

    def rectangle_gap(left: np.ndarray, right: np.ndarray) -> float:
        lx, ly, lw, lh = (float(value) for value in left[:4])
        rx, ry, rw, rh = (float(value) for value in right[:4])
        dx = max(lx - (rx + rw), rx - (lx + lw), 0.0)
        dy = max(ly - (ry + rh), ry - (ly + lh), 0.0)
        return math.hypot(dx, dy)

    # A single object can be split into multiple same-color islands by a label,
    # highlight, or occlusion. Grow from the largest island across only small
    # bounding-box gaps, rather than taking every region of the same color.
    changed = True
    while changed:
        changed = False
        for candidate in range(1, count):
            if candidate in selected or int(stats[candidate, cv2.CC_STAT_AREA]) < max(20, min_area_px // 4):
                continue
            if any(rectangle_gap(stats[candidate], stats[current]) <= 12.0 for current in selected):
                selected.add(candidate)
                changed = True

    component = np.isin(labels, list(selected))
    ys, xs = np.where(component)
    area = int(xs.size)
    if area < min_area_px:
        raise ValueError(f"largest colored component has only {area} pixels; minimum is {min_area_px}")
    merged_stats = np.array([xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, area])
    merged_centroid = np.array([xs.mean(), ys.mean()])
    return component, merged_stats, merged_centroid


def _unproject(pixel: np.ndarray, depth_m: float, projection: dict[str, Any]) -> np.ndarray:
    u, v = (float(pixel[0]), float(pixel[1]))
    return np.array([
        (u - float(projection["cx"])) * depth_m / float(projection["fx"]),
        (v - float(projection["cy"])) * depth_m / float(projection["fy"]),
        depth_m,
    ])


def _quaternion_matrix(q_xyzw: list[float]) -> np.ndarray:
    x, y, z, w = (float(value) for value in q_xyzw)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-12:
        raise ValueError("camera mount quaternion has zero norm")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _world_point(camera_point: np.ndarray, mount: dict[str, Any]) -> np.ndarray:
    rotation = _quaternion_matrix(mount["rotation_xyzw"])
    translation = np.asarray(mount["translation_m"], dtype=float)
    return rotation @ camera_point + translation


def _point_payload(pixel: np.ndarray, depth_m: float, projection: dict[str, Any], mount: dict[str, Any]) -> dict[str, Any]:
    camera = _unproject(pixel, depth_m, projection)
    world = _world_point(camera, mount)
    return {
        "pixel_xy": [round(float(pixel[0]), 3), round(float(pixel[1]), 3)],
        "depth_m": round(float(depth_m), 6),
        "camera_xyz_m": [round(float(value), 6) for value in camera],
        "world_xyz_m": [round(float(value), 6) for value in world],
    }


def visible_world_points(
    depth_raw: np.ndarray,
    component: np.ndarray,
    profile: dict[str, Any],
) -> np.ndarray:
    """Return valid registered depth samples inside a mask in the mount's parent frame."""
    depth_profile = profile["intrinsics"]["depth"]
    scale = float(depth_profile["scale_m_per_unit"])
    valid = component & (depth_raw != int(depth_profile["invalid_value"]))
    ys, xs = np.where(valid)
    depths = depth_raw[ys, xs].astype(float) * scale
    limits = depth_profile["valid_range_m"]
    keep = (depths >= float(limits["min"])) & (depths <= float(limits["max"]))
    xs, ys, depths = xs[keep], ys[keep], depths[keep]
    if depths.size < 20:
        raise ValueError(f"only {depths.size} valid depth samples inside color mask")
    projection = profile["intrinsics"]["color"]["projection"]
    camera = np.column_stack((
        (xs - float(projection["cx"])) * depths / float(projection["fx"]),
        (ys - float(projection["cy"])) * depths / float(projection["fy"]),
        depths,
    ))
    mount = profile["extrinsics"]["mount"]
    rotation = _quaternion_matrix(mount["rotation_xyzw"])
    translation = np.asarray(mount["translation_m"], dtype=float)
    return camera @ rotation.T + translation


def project_endpoints_to_center_plane(
    located: dict[str, Any],
    center_z: float,
    profile: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Move visible-surface endpoints along camera rays to a cylinder center plane."""
    origin = np.asarray(profile["extrinsics"]["mount"]["translation_m"], dtype=float)
    projected = []
    for label in ("end_a", "end_b"):
        endpoint = np.asarray(located[label]["world_xyz_m"], dtype=float)
        denominator = float(endpoint[2] - origin[2])
        if abs(denominator) < 1e-6:
            raise ValueError("camera ray is parallel to the requested center plane")
        factor = (float(center_z) - float(origin[2])) / denominator
        projected.append(origin + factor * (endpoint - origin))
    end_a, end_b = projected
    center = (end_a + end_b) / 2.0
    center[2] = float(center_z)
    return center, end_a, end_b


def locate_colored_object(
    bgr: np.ndarray,
    depth_raw: np.ndarray,
    profile: dict[str, Any],
    color: str,
    min_area_px: int = 80,
) -> tuple[dict[str, Any], np.ndarray]:
    if color not in HSV_RANGES:
        raise ValueError(f"unsupported color: {color}")
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("color image must be BGR8")
    if depth_raw.ndim != 2 or depth_raw.shape != bgr.shape[:2]:
        raise ValueError("depth image must be registered to color")

    component, stats, centroid = _largest_component(_mask_for_color(bgr, color), min_area_px)
    ys, xs = np.where(component)
    points = np.column_stack((xs, ys)).astype(float)
    centered = points - points.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(centered.T))
    axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    if axis[0] < 0 or (abs(axis[0]) < 1e-9 and axis[1] < 0):
        axis = -axis
    projection_on_axis = centered @ axis
    q05, q15, q85, q95 = np.quantile(projection_on_axis, [0.05, 0.15, 0.85, 0.95])
    end_a_pixel = points.mean(axis=0) + axis * q05
    end_b_pixel = points.mean(axis=0) + axis * q95

    depth_profile = profile["intrinsics"]["depth"]
    scale = float(depth_profile["scale_m_per_unit"])
    valid = component & (depth_raw != int(depth_profile["invalid_value"]))
    valid_depths = depth_raw[valid].astype(float) * scale
    limits = depth_profile["valid_range_m"]
    valid_depths = valid_depths[(valid_depths >= float(limits["min"])) & (valid_depths <= float(limits["max"]))]
    if valid_depths.size < max(20, min_area_px // 4):
        raise ValueError(f"only {valid_depths.size} valid depth samples inside color mask")

    def terminal_depth(low: float, high: float) -> float:
        selected = (projection_on_axis >= low) & (projection_on_axis <= high)
        terminal_values = depth_raw[ys[selected], xs[selected]].astype(float) * scale
        terminal_values = terminal_values[(terminal_values >= float(limits["min"])) & (terminal_values <= float(limits["max"]))]
        return float(np.median(terminal_values)) if terminal_values.size else float(np.median(valid_depths))

    perpendicular = np.array([-axis[1], axis[0]])
    side_a = projection_on_axis <= q15
    side_b = projection_on_axis >= q85
    width_a = float(np.ptp(centered[side_a] @ perpendicular)) if np.count_nonzero(side_a) > 1 else math.inf
    width_b = float(np.ptp(centered[side_b] @ perpendicular)) if np.count_nonzero(side_b) > 1 else math.inf
    narrow_label = "end_a" if width_a <= width_b else "end_b"

    color_profile = profile["intrinsics"]["color"]
    expected = (int(color_profile["height"]), int(color_profile["width"]))
    if bgr.shape[:2] != expected:
        raise ValueError(f"color image shape {bgr.shape[:2]} differs from calibrated shape {expected}")
    camera_mount = profile["extrinsics"]["mount"]
    center_depth = float(np.median(valid_depths))
    end_a = _point_payload(end_a_pixel, terminal_depth(q05, q15), color_profile["projection"], camera_mount)
    end_b = _point_payload(end_b_pixel, terminal_depth(q85, q95), color_profile["projection"], camera_mount)
    center = _point_payload(np.asarray(centroid), center_depth, color_profile["projection"], camera_mount)
    x, y, width, height, area = (int(value) for value in stats)

    annotated = bgr.copy()
    cv2.rectangle(annotated, (x, y), (x + width - 1, y + height - 1), (255, 0, 255), 2)
    cv2.line(annotated, tuple(np.rint(end_a_pixel).astype(int)), tuple(np.rint(end_b_pixel).astype(int)), (0, 0, 255), 2)
    cv2.circle(annotated, tuple(np.rint(centroid).astype(int)), 4, (255, 0, 0), -1)
    narrow_pixel = end_a_pixel if narrow_label == "end_a" else end_b_pixel
    cv2.circle(annotated, tuple(np.rint(narrow_pixel).astype(int)), 6, (0, 255, 255), 2)

    result = {
        "found": True,
        "color": color,
        "area_px": area,
        "bbox_xyxy": [x, y, x + width - 1, y + height - 1],
        "center": center,
        "major_axis_image_xy": [round(float(axis[0]), 6), round(float(axis[1]), 6)],
        "major_axis_angle_deg": round(math.degrees(math.atan2(float(axis[1]), float(axis[0]))), 3),
        "end_a": end_a,
        "end_b": end_b,
        "narrow_end": narrow_label,
        "narrow_end_point": end_a if narrow_label == "end_a" else end_b,
        "terminal_width_px": {"end_a": round(width_a, 3), "end_b": round(width_b, 3)},
        "depth_samples": int(valid_depths.size),
        "depth_percentiles_m": {
            key: round(float(value), 6)
            for key, value in zip(("p10", "p25", "p50", "p75", "p90"), np.quantile(valid_depths, [0.1, 0.25, 0.5, 0.75, 0.9]))
        },
        "reference": "visible_colored_surface",
    }
    return result, annotated
