#!/usr/bin/env python3
"""Poll joint feedback for a non-blocking Servo command using wall time."""

import time

from kinex import args, device, fail, finish

from core import evaluate_sample


def main() -> None:
    values = args()
    try:
        arm = values["arm"]
        target = values["target_joints"]
        tolerance = float(values.get("tolerance_rad", 0.02))
        timeout = float(values.get("timeout_wall_s", 60.0))
        interval = float(values.get("poll_interval_s", 0.5))
        stable_samples = values.get("stable_samples", 2)
        if not 0 < timeout <= 120:
            raise ValueError("timeout_wall_s must be in (0, 120]")
        if not 0.1 <= interval <= 5:
            raise ValueError("poll_interval_s must be in [0.1, 5]")
        if not isinstance(stable_samples, int):
            raise ValueError("stable_samples must be an integer")

        started = time.monotonic()
        consecutive = 0
        samples = 0
        latest = None
        measured_at_s = None
        while True:
            reading = device(arm, "read")
            samples += 1
            measured_at_s = reading.get("timestamp")
            latest = evaluate_sample(
                measured_joints=reading["positions"],
                target_joints=target,
                tolerance_rad=tolerance,
                faults=reading.get("faults", []),
                consecutive_reached=consecutive,
                stable_samples=stable_samples,
            )
            consecutive = latest["consecutive_reached"]
            elapsed = time.monotonic() - started
            if latest["reached"] or latest["faults"] or elapsed >= timeout:
                finish({
                    "arm": arm,
                    "timed_out": elapsed >= timeout and not latest["reached"],
                    "elapsed_wall_s": elapsed,
                    "samples": samples,
                    "measured_at_s": measured_at_s,
                    **latest,
                })
                return
            time.sleep(min(interval, max(0.0, timeout - elapsed)))
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))


main()
