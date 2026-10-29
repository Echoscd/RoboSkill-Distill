"""Deterministic interval selection for recorded-video visual evidence."""

from __future__ import annotations

import math
from pathlib import Path


def scoped_video_path(video_path: str, run_dir: str) -> Path:
    root = Path(run_dir).resolve(strict=True)
    video = Path(video_path).resolve(strict=True)
    if not root.is_dir() or not video.is_file() or not video.is_relative_to(root):
        raise ValueError("video_path must resolve to a file inside the supervisor-provided diagnostic run")
    if video.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise ValueError("video_path must name a supported recorded video")
    return video


def choose_frame_indices(
    timestamps: list[float], *, start_s: float = 0.0,
    end_s: float | None = None, max_frames: int = 12,
) -> list[int]:
    if type(max_frames) is not int or not 2 <= max_frames <= 16:
        raise ValueError("max_frames must be an integer in [2,16]")
    if not timestamps or any(not math.isfinite(x) or x < 0 for x in timestamps):
        raise ValueError("video timestamps must be non-empty, finite and non-negative")
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("video timestamps must be ordered")
    if not math.isfinite(start_s) or start_s < 0:
        raise ValueError("start_s must be finite and non-negative")
    stop = timestamps[-1] if end_s is None else end_s
    if not math.isfinite(stop) or stop < start_s:
        raise ValueError("end_s must be finite and at least start_s")
    eligible = [index for index, timestamp in enumerate(timestamps) if start_s <= timestamp <= stop]
    if not eligible:
        raise ValueError("requested interval contains no recorded frames")
    if len(eligible) <= max_frames:
        return eligible
    return [eligible[round(index * (len(eligible) - 1) / (max_frames - 1))] for index in range(max_frames)]
