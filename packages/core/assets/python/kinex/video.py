"""One ffmpeg writer per camera, with a bounded latest-sample mailbox.

Output frames use a fixed clock; slow acquisition holds the previous observation.
frames.jsonl maps every encoded frame to both its playback and acquisition time.
PNG/JPEG input is decoded by ffmpeg, so harness recording needs only Python stdlib.
"""

import functools
import json
import math
import os
import pathlib
import select
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass


PROCESS_TIMEOUT_S = 10


@functools.lru_cache(maxsize=2)
def require_ffmpeg(depth=False):
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise RuntimeError("camera recording requires ffmpeg on PATH")
    result = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, timeout=10)
    encoders = result.stdout.decode(errors="replace")
    for codec in ("libx264", "ffv1") if depth else ("libx264",):
        if result.returncode or codec not in encoders:
            raise RuntimeError(f"ffmpeg at {binary} lacks required encoder {codec}: {result.stderr.decode(errors='replace')}")
    return binary


@dataclass(frozen=True)
class Image:
    data: bytes
    codec: str
    width: int = 0
    height: int = 0


def encoded_image(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return Image(data, "png")
    if data.startswith(b"\xff\xd8"):
        return Image(data, "mjpeg")
    raise ValueError("camera frame must be PNG or JPEG")


def raw_image(frame, depth=False):
    if isinstance(frame, tuple):
        data, width, height = frame
        image = Image(bytes(data), "gray16le" if depth else "rgb24", int(width), int(height))
    elif type(frame).__module__.startswith("PIL.") and not depth:
        rgb = frame.convert("RGB")
        image = Image(rgb.tobytes(), "rgb24", rgb.width, rgb.height)
    else:
        # A numpy array supplied by a driver already implies numpy is installed.
        import numpy as np
        grid = np.ascontiguousarray(np.asarray(frame, dtype="<u2" if depth else np.uint8))
        if grid.ndim != (2 if depth else 3) or (not depth and grid.shape[2] != 3):
            raise ValueError(f"invalid {'depth' if depth else 'RGB'} shape: {grid.shape}")
        image = Image(grid.tobytes(), "gray16le" if depth else "rgb24", int(grid.shape[1]), int(grid.shape[0]))
    expected = image.width * image.height * (2 if depth else 3)
    if image.width <= 0 or image.height <= 0 or len(image.data) != expected:
        raise ValueError("raw frame size does not match its dimensions")
    return image


class Sink:
    def __init__(self, image, path, fps, max_px=None, depth=False):
        binary = require_ffmpeg(depth)
        self.path = path
        self.format = (image.codec, image.width, image.height)
        raw = image.codec in ("rgb24", "gray16le")
        source = ["-f", "image2pipe", "-c:v", image.codec, "-framerate", str(fps)]
        if raw:
            source = ["-f", "rawvideo", "-pixel_format", image.codec, "-video_size", f"{image.width}x{image.height}", "-framerate", str(fps)]
        output = ["-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "gray16le", "-cluster_time_limit", "1000"]
        if not depth:
            scale = f"min(1,{max_px}/max(iw,ih))" if max_px else "1"
            output = ["-vf", f"scale=w='max(2,trunc(iw*({scale})/2)*2)':h='max(2,trunc(ih*({scale})/2)*2)'",
                      "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "23", "-pix_fmt", "yuv420p",
                      "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000"]
        command = [binary, "-y", "-loglevel", "error", "-probesize", "32", "-analyzeduration", "0", *source,
                   "-i", "pipe:0", "-an", *output, "-flush_packets", "1", str(path)]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0)
        os.set_blocking(self.proc.stdin.fileno(), False)
        self.stderr = bytearray()
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self):
        while chunk := self.proc.stderr.read(4096):
            self.stderr.extend(chunk)
            del self.stderr[:-8192]

    def write(self, image):
        if (image.codec, image.width, image.height) != self.format:
            raise ValueError(f"frame format changed while recording {self.path}")
        data = memoryview(image.data)
        deadline = time.monotonic() + PROCESS_TIMEOUT_S
        while data:
            if self.proc.poll() is not None:
                raise RuntimeError(f"ffmpeg exited {self.proc.returncode} writing {self.path}: {self.stderr.decode(errors='replace')}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"ffmpeg input stalled for {self.path}")
            if not select.select([], [self.proc.stdin], [], min(remaining, 0.1))[1]:
                continue
            try:
                data = data[os.write(self.proc.stdin.fileno(), data):]
            except BlockingIOError:
                continue

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=PROCESS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise TimeoutError(f"ffmpeg did not close {self.path}")
        finally:
            self.reader.join(timeout=2)
            self.proc.stderr.close()
        if self.proc.returncode:
            raise RuntimeError(f"ffmpeg exited {self.proc.returncode} finalizing {self.path}: {self.stderr.decode(errors='replace').strip()}")


class VideoWriter:
    def __init__(self, dir, fps=15, max_px=None, depth=False):
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("video fps must be positive and finite")
        require_ffmpeg(depth)
        self.dir = pathlib.Path(dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = str(self.dir / "video.mp4")
        self.depth_file = str(self.dir / "depth.mkv") if depth else None
        self.fps, self.max_px = float(fps), max_px
        self.count = self.samples = self.dropped = self.repeated = 0
        self.started_ns = self.ended_ns = None
        self.error = None
        self._latest = None
        self._stop = False
        self._condition = threading.Condition()
        self._wall, self._mono = time.time_ns(), time.monotonic_ns()
        self._sinks = []
        self._abort = threading.Event()
        self._thread = threading.Thread(target=self._run, name="video-writer", daemon=True)
        self._thread.start()

    def now_ns(self):
        return self._wall + time.monotonic_ns() - self._mono

    def push(self, image, depth=None, t_ns=None):
        color = image if isinstance(image, Image) else raw_image(image)
        if self.depth_file and depth is None:
            raise ValueError("RGBD frame lacks depth")
        depth_image = raw_image(depth, True) if self.depth_file else None
        stamp = int(t_ns if t_ns is not None else self.now_ns())
        with self._condition:
            if self._stop or self.error:
                raise RuntimeError(self.error or "video writer is closed")
            if self._latest is not None:
                if stamp < self._latest[2]:
                    raise ValueError("camera acquisition timestamps went backwards")
                self.dropped += 1
            self._latest = (color, depth_image, stamp)
            self.samples += 1
            self._condition.notify()

    def _run(self):
        sinks = self._sinks
        current = None
        previous_source = None
        try:
            with open(self.dir / "frames.jsonl", "w", buffering=1) as stamps:
                while not self._abort.is_set():
                    with self._condition:
                        if current is None and self._latest is None and not self._stop:
                            self._condition.wait()
                            continue
                        if current is None and self._latest is None:
                            break
                        if self.started_ns is None:
                            self.started_ns = self._latest[2]
                        tick = self.started_ns + round(self.count * 1e9 / self.fps)
                        if self._stop and tick >= self.ended_ns and self.count:
                            break
                        delay = (tick - self.now_ns()) / 1e9
                        if delay > 0 and not self._stop:
                            self._condition.wait(delay)
                            continue
                        if self._latest is not None and (current is None or self._latest[2] <= tick):
                            current, self._latest = self._latest, None
                        sample = current
                    if not sinks:
                        sinks.append(Sink(sample[0], self.file, self.fps, self.max_px))
                        if self.depth_file:
                            sinks.append(Sink(sample[1], self.depth_file, self.fps, depth=True))
                    for sink, image in zip(sinks, sample[:2]):
                        sink.write(image)
                    stamps.write(json.dumps({"i": self.count, "t_ns": tick, "source_t_ns": sample[2]}) + "\n")
                    if sample[2] == previous_source:
                        self.repeated += 1
                    previous_source = sample[2]
                    self.count += 1
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            for sink in sinks:
                try:
                    sink.close()
                except Exception as exc:
                    self.error = "; ".join(filter(None, [self.error, f"{type(exc).__name__}: {exc}"]))

    def close(self):
        with self._condition:
            if not self._stop:
                self.ended_ns = self.now_ns()
                self._stop = True
                self._condition.notify()
        self._thread.join(timeout=35)
        if self._thread.is_alive():
            self.error = self.error or "video writer did not stop within 35s"
            self._abort.set()
            for sink in self._sinks:
                sink.proc.kill()
            self._thread.join(timeout=5)
        return self.facts()

    def facts(self):
        facts = {"frames": self.count, "samples": self.samples, "dropped": self.dropped, "repeated": self.repeated, "fps": self.fps,
                 "started_ns": self.started_ns, "ended_ns": self.ended_ns}
        if self.count:
            facts.update(video=self.file, timestamps=str(self.dir / "frames.jsonl"))
            if self.depth_file:
                facts["depth"] = self.depth_file
        if self.error:
            facts["error"] = self.error
        if self._stop and not self.count:
            facts["error"] = self.error or "no camera frames captured"
        return {key: value for key, value in facts.items() if value is not None}
