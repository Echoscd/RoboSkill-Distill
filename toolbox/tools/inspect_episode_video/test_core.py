"""Evidence-selection and cross-run scope invariants."""

import importlib.util
import math
from pathlib import Path
import tempfile


spec = importlib.util.spec_from_file_location("inspect_episode_video_core", Path(__file__).with_name("core.py"))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def test_overview_preserves_first_and_last_and_detail_stays_in_interval():
    timestamps = [index / 25 for index in range(555)]
    overview = core.choose_frame_indices(timestamps, max_frames=12)
    assert overview[0] == 0 and overview[-1] == 554
    assert len(overview) == 12 and overview == sorted(set(overview))
    detail = core.choose_frame_indices(timestamps, start_s=18, end_s=19, max_frames=12)
    assert detail[0] == 450 and detail[-1] == 475
    assert all(18 <= timestamps[index] <= 19 for index in detail)


def test_rejects_invalid_times_and_empty_intervals():
    for values in ({"start_s": -1}, {"end_s": math.nan}, {"start_s": 4}, {"max_frames": 1}):
        try:
            core.choose_frame_indices([0, 1, 2], **values)
        except ValueError:
            continue
        raise AssertionError(f"expected rejection for {values}")


def test_rejects_cross_run_paths_and_symlink_escapes():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        current = root / "current"
        current.mkdir()
        video = current / "scene.mp4"
        video.touch()
        outside = root / "other.mp4"
        outside.touch()
        assert core.scoped_video_path(str(video), str(current)) == video.resolve()
        escaped = current / "escape.mp4"
        escaped.symlink_to(outside)
        for path in (outside, escaped):
            try:
                core.scoped_video_path(str(path), str(current))
            except ValueError:
                continue
            raise AssertionError("cross-run video accepted")
