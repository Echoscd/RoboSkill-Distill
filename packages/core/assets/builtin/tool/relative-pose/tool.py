#!/usr/bin/env python3
"""Relative pose between two device frames, from the calibrated frame graph.

A thin agent-facing wrapper over kinex.frames: mount chains and fixed or live
frames, optionally bridged by caller-supplied pose estimates.
The pose direction is the documented transform convention — child expressed in
parent, p_parent = R·p_child + t, quaternion xyzw.
"""

from kinex import args, finish, frames
from kinex.geometry import apply_rt, pose_to_rt


def main():
    a = args()
    result = frames.pose(a["child"], a["parent"], estimates=a.get("estimates"))
    point = a.get("point")
    if point is not None:
        moved = apply_rt(pose_to_rt(result), [float(v) for v in point])
        result["point_in_parent"] = [round(v, 6) for v in moved]
    result["translation"] = [round(v, 6) for v in result["translation"]]
    result["rotation"] = [round(v, 6) for v in result["rotation"]]
    finish(result)


main()
