#!/usr/bin/env python3
"""One archived-frame Qwen API probe with exact input/output preservation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_report(out: Path, manifest: dict, frames: list[dict], prompt: str, content: str, metrics: dict) -> None:
    figures = []
    for frame in frames:
        encoded = base64.b64encode((out / frame["path"]).read_bytes()).decode("ascii")
        label = f'Source frame {frame["source_frame_index"]} · {frame["video_time_s"]:.2f}s'
        figures.append(
            f'<figure><a href="data:image/jpeg;base64,{encoded}" target="_blank">'
            f'<img src="data:image/jpeg;base64,{encoded}" alt="{label}"></a>'
            f'<figcaption>{label}</figcaption></figure>'
        )
    esc = html.escape
    native_video = manifest.get("input_mode") == "video"
    preview = ""
    if native_video:
        video_bytes = Path(manifest["source_video"]).read_bytes()
        encoded_video = base64.b64encode(video_bytes).decode("ascii")
        preview = (
            '<h2>Exact video file sent to the API</h2>'
            '<video controls preload="metadata" style="width:100%;max-width:800px" '
            f'src="data:video/mp4;base64,{encoded_video}"></video>'
            '<p>The request contains one video_url data part and zero image_url parts. '
            'Provider-side video sampling is not disclosed by this probe.</p>'
        )
    input_label = "one original MP4 video" if native_video else f"{len(frames)} sampled images"
    frame_heading = (
        "Local preview frames (not sent as images to the model)"
        if native_video else "Images supplied to Qwen, in request order"
    )
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Iter3 · Qwen video diagnosis smoke test</title>
<style>
body{{margin:0;background:#f5f3ed;color:#242729;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1400px;margin:auto;padding:28px}}h1{{font-size:26px;margin:0 0 8px}}
h2{{font-size:20px;margin-top:32px}}p{{margin:8px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;border:1px solid #d5d5cd;border-radius:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
figure{{margin:0;background:white;padding:8px}}img{{width:100%;display:block}}figcaption{{font-size:13px;color:#555}}
.notice{{border-left:3px solid #506c72;padding:8px 16px}}details{{margin-top:16px}}
</style><main>
<h1>Iter3 · Qwen video diagnosis smoke test</h1>
<p class="notice">Archived-video analysis only. No robot execution. The text below is Qwen's response, not an independently verified root cause.</p>
<p>Model: {esc(manifest['model'])} · Input: {esc(input_label)} · Source: {esc(manifest['source_video'])}</p>
{preview}
<h2>Qwen response</h2><pre>{esc(content)}</pre>
<details><summary>Exact instruction supplied to Qwen</summary><pre>{esc(prompt)}</pre></details>
<details><summary>API metrics</summary><pre>{esc(json.dumps(metrics, ensure_ascii=False, indent=2))}</pre></details>
<h2>{frame_heading}</h2><div class="grid">{''.join(figures)}</div>
<p>Full request, response and frame provenance are saved beside this HTML as request.wire.json, response.raw.json, manifest.json and frames.json.</p>
</main></html>'''
    (out / "trace.html").write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--proxy")
    parser.add_argument("--model", default="qwen/qwen3-vl-235b-a22b-instruct")
    parser.add_argument("--endpoint", default="https://openrouter.ai/api/v1/chat/completions")
    parser.add_argument("--stride", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--provider", help="Pin one OpenRouter provider for known image-count limits.")
    parser.add_argument("--input-mode", choices=("frames", "video"), default="frames")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"))
    options = parser.parse_args()
    if options.stride < 1:
        parser.error("stride must be positive")
    out = options.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "frames").mkdir()
    probe_result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,duration,nb_frames,nb_read_frames", "-of", "json", str(options.video)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(probe_result.stdout)["streams"][0]
    numerator, denominator = map(float, stream["r_frame_rate"].split("/"))
    fps = numerator / denominator
    source_frame_count = int(stream["nb_read_frames"])
    selected_indices = sorted(set([*range(0, source_frame_count, options.stride), source_frame_count - 1]))
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(options.video),
         "-vf", f"select=not(mod(n\\,{options.stride}))+eq(n\\,{source_frame_count - 1})", "-vsync", "vfr",
         "-q:v", "2", "-start_number", "0", str(out / "frames" / "%04d.jpg")],
        check=True,
    )
    prompt = options.prompt.read_text(encoding="utf-8")
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    frames = []
    message_content = [{"type": "text", "text": prompt}]
    image_paths = sorted((out / "frames").glob("*.jpg"))
    if len(image_paths) != len(selected_indices):
        raise RuntimeError("extracted frames do not match selected source indices")
    for source_index, frame_path in zip(selected_indices, image_paths, strict=True):
        raw = frame_path.read_bytes()
        frame = {
            "path": str(frame_path.relative_to(out)),
            "source_frame_index": source_index,
            "video_time_s": source_index / fps,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        frames.append(frame)
        message_content.extend([
            {"type": "text", "text": f"Source frame {source_index}, video time {source_index / fps:.2f} seconds."},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"),
            }},
        ])
    if not frames:
        raise RuntimeError("video extraction produced no frames")
    if options.input_mode == "video":
        message_content = [
            {"type": "text", "text": prompt},
            {"type": "video_url", "video_url": {
                "url": "data:video/mp4;base64," + base64.b64encode(options.video.read_bytes()).decode("ascii"),
            }},
        ]
    body = {
        "model": options.model,
        "messages": [{"role": "user", "content": message_content}],
        "temperature": 0,
        "max_tokens": options.max_tokens,
        "stream": False,
    }
    if options.provider:
        body["provider"] = {"order": [options.provider], "allow_fallbacks": False}
    if options.reasoning_effort:
        body["reasoning"] = {"effort": options.reasoning_effort}
    request_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (out / "request.wire.json").write_bytes(request_bytes)
    dump(out / "frames.json", frames)
    manifest = {
        "schema": "kinex/video-diagnosis-smoke/1",
        "created_at": now(),
        "model": options.model,
        "input_mode": options.input_mode,
        "sent_image_parts": 0 if options.input_mode == "video" else len(frames),
        "sent_video_parts": 1 if options.input_mode == "video" else 0,
        "reasoning_effort": options.reasoning_effort or "provider_default",
        "endpoint": options.endpoint,
        "source_video": str(options.video.resolve()),
        "source_sha256": hashlib.sha256(options.video.read_bytes()).hexdigest(),
        "source_stream": stream,
        "sampling": {"method": "every_nth_source_frame", "stride": options.stride,
                     "effective_fps": fps / options.stride, "frame_count": len(frames),
                     "purpose": "local preview only" if options.input_mode == "video" else "model input"},
        "provider_video_sampling": "not disclosed" if options.input_mode == "video" else "not applicable",
        "input_evidence": ["task goal", "native failure label", "original MP4 video" if options.input_mode == "video" else "chronologically sampled video frames"],
        "prior_diagnosis_included": False,
        "robot_motion": False,
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "request_bytes": len(request_bytes),
        "status": "prepared",
    }
    dump(out / "manifest.json", manifest)
    api_key = options.key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        raise RuntimeError("API key file is empty")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": options.proxy, "https": options.proxy} if options.proxy else {})
    )
    request = urllib.request.Request(
        options.endpoint, data=request_bytes, method="POST", headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Kinex archived-video diagnosis smoke test",
        },
    )
    metrics = {"started_at": now(), "http_status": None}
    start = time.perf_counter()
    print(json.dumps({"status": "requesting", "input_mode": options.input_mode,
                      "sent_video_parts": manifest["sent_video_parts"],
                      "sent_image_parts": manifest["sent_image_parts"],
                      "request_bytes": len(request_bytes)}, ensure_ascii=False), flush=True)
    response_bytes = b""
    response = {}
    try:
        with opener.open(request, timeout=180) as result:
            metrics["http_status"] = result.status
            response_bytes = result.read()
    except urllib.error.HTTPError as error:
        metrics["http_status"] = error.code
        response_bytes = error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        metrics["transport_error"] = type(error).__name__ + ": " + str(error)
    metrics.update({"ended_at": now(), "duration_s": time.perf_counter() - start})
    (out / "response.raw.json").write_bytes(response_bytes)
    if response_bytes:
        try:
            response = json.loads(response_bytes)
        except json.JSONDecodeError:
            metrics["parse_error"] = "response is not JSON"
    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content") or ""
    metrics.update({
        "usage": response.get("usage"), "provider": response.get("provider"),
        "response_id": response.get("id"), "response_model": response.get("model"),
        "finish_reason": choices[0].get("finish_reason") if choices else None,
    })
    dump(out / "assistant.message.json", message)
    (out / "assistant.txt").write_text(content, encoding="utf-8")
    dump(out / "metrics.json", metrics)
    ok = metrics["http_status"] == 200 and bool(content)
    manifest.update({"status": "complete" if ok else "failed", "ended_at": now()})
    dump(out / "manifest.json", manifest)
    render_report(out, manifest, frames, prompt, content or json.dumps(response or metrics, ensure_ascii=False, indent=2), metrics)
    print(json.dumps({"ok": ok, "output_dir": str(out), "metrics": metrics}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
