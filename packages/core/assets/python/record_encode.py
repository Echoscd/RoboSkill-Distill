#!/usr/bin/env python3
"""Harness camera bridge: JSONL frames in, ready/ack/final facts out.

PNG/JPEG bytes go directly to ffmpeg. Each accepted input is acknowledged so
harness buffering stays bounded. RGBD depth uses the driver's lossless PGM16.
"""
import argparse
import base64
import json
import sys

from kinex.stream import VideoWriter, parse_pgm16
from kinex.video import encoded_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--max-px", type=int)
    parser.add_argument("--depth", action="store_true")
    args = parser.parse_args()
    writer = VideoWriter(args.dir, fps=args.fps, max_px=args.max_px, depth=args.depth)
    print(json.dumps({"ready": True}), flush=True)
    error = None
    try:
        for line in sys.stdin:
            row = json.loads(line)
            if row.get("stop"):
                break
            image = encoded_image(base64.b64decode(row["image"], validate=True))
            depth = parse_pgm16(base64.b64decode(row["depth"], validate=True)) if args.depth else None
            writer.push(image, depth, row["t_ns"])
            print(json.dumps({"ack": True, **writer.facts()}), flush=True)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        facts = writer.close()
    if error:
        facts["error"] = error
    print(json.dumps({"done": True, **facts}), flush=True)


if __name__ == "__main__":
    main()
