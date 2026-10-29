#!/usr/bin/env python3
"""Return time-indexed image attachments from a scoped episode-video interval."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

from kinex import args, fail, finish

from core import choose_frame_indices, scoped_video_path


def main() -> None:
    values = args()
    try:
        run_dir = os.environ.get("KINEX_DIAGNOSTIC_RUN_DIR")
        if not run_dir:
            raise ValueError("supervisor must set KINEX_DIAGNOSTIC_RUN_DIR for recorded-video diagnosis")
        video = scoped_video_path(values["video_path"], run_dir)
        inspection_id = f"video_inspection_{uuid.uuid4().hex[:12]}"
        destination = Path(run_dir).resolve() / "video-inspections" / inspection_id
        destination.mkdir(parents=True, exist_ok=False)
        raw = video.read_bytes()
        snapshot = destination / "source.mp4"
        snapshot.write_bytes(raw)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
             "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(snapshot)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        decoded = json.loads(probe.stdout).get("frames", [])
        timestamps = [float(frame["best_effort_timestamp_time"]) for frame in decoded]
        first_timestamp = timestamps[0] if timestamps else 0.0
        timestamps = [value - first_timestamp for value in timestamps]
        indices = choose_frame_indices(
            timestamps,
            start_s=float(values.get("start_s", 0.0)),
            end_s=float(values["end_s"]) if values.get("end_s") is not None else None,
            max_frames=values.get("max_frames", 12),
        )
        selection = "+".join(f"eq(n\\,{index})" for index in indices)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(snapshot),
             "-vf", f"select={selection}", "-vsync", "vfr", "-q:v", "2", "-start_number", "0",
             str(destination / "%04d.jpg")],
            capture_output=True, text=True, check=True, timeout=30,
        )
        images = sorted(destination.glob("*.jpg"))
        if len(images) != len(indices):
            raise ValueError("decoder output does not match selected frame indices")
        result = {
            "inspection_id": inspection_id,
            "run_id": Path(run_dir).resolve().name,
            "video_path": str(video),
            "video_snapshot_path": str(snapshot),
            "video_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
            "clock": "video_relative_seconds",
            "video_last_frame_s": timestamps[-1],
            "available_source_frames": len(timestamps),
            "selected_count": len(images),
            "requested_interval_s": [values.get("start_s", 0.0), values.get("end_s")],
            "frames": [
                {"image_attachment_index": position,
                 "source_frame_index": source_index,
                 "video_time_s": timestamps[source_index],
                 "image_path": str(image_path)}
                for position, (source_index, image_path) in enumerate(zip(indices, images, strict=True))
            ],
            "limitations": [
                "Sparse frames can miss intermediate events; inspect a shorter interval for denser evidence.",
                "Occluded contact, force, measured arrival and task success are not established by this tool.",
                "Video timestamps are not API wall time and are not automatically aligned to tool-call timestamps.",
            ],
        }
        (destination / "inspection.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        finish(result, file=[str(path) for path in images])
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        fail(str(exc))


main()
