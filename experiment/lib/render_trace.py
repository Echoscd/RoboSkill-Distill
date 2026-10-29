#!/usr/bin/env python3
"""Generate a self-contained HTML report for a Kinex + RoboEnv run.

This script intentionally does not render private model reasoning text. It shows
the observable transcript: prompts, model messages, tool calls/results, images,
RoboEnv actions, timing, and the terminal verdict.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import pathlib
import re
import struct
import zlib
from collections import Counter, defaultdict
from typing import Any, Iterable


MAX_ACTION_JSON_CHARS = 12000


def read_json(path: pathlib.Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                rows.append({
                    "type": "parse_error",
                    "timestamp": None,
                    "line": lineno,
                    "error": str(exc),
                })
                continue
            if isinstance(value, dict):
                value["_line"] = lineno
                rows.append(value)
    return rows


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return None


def local_time(value: Any) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return str(value or "")
    china = dt.timezone(dt.timedelta(hours=8))
    return parsed.astimezone(china).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def fmt_ms(value: Any) -> str:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return ""
    seconds = milliseconds / 1000.0
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}m {seconds:.1f}s"


def fmt_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, seconds = divmod(max(0.0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:04.1f}s"
    return f"{minutes}m {seconds:04.1f}s"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pretty(value: Any, limit: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if limit is not None and len(text) > limit:
        text = text[:limit] + f"\n… truncated ({len(text) - limit:,} chars omitted)"
    return text


def data_uri(block: dict[str, Any]) -> str | None:
    data = block.get("data")
    mime = block.get("mimeType", "image/png")
    if not isinstance(data, str) or not data:
        return None
    if data.startswith("data:"):
        return data
    return f"data:{mime};base64,{data}"


def file_data_uri(path: pathlib.Path, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def pgm_to_png_data_uri(path: pathlib.Path) -> str | None:
    """Convert binary P5 8/16-bit PGM to an 8-bit grayscale PNG preview."""
    raw = path.read_bytes()
    tokens: list[bytes] = []
    pos = 0
    while len(tokens) < 4 and pos < len(raw):
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        if pos < len(raw) and raw[pos] == ord("#"):
            while pos < len(raw) and raw[pos] not in b"\r\n":
                pos += 1
            continue
        start = pos
        while pos < len(raw) and raw[pos] not in b" \t\r\n":
            pos += 1
        tokens.append(raw[start:pos])
    if len(tokens) != 4 or tokens[0] != b"P5":
        return None
    width, height, maxval = map(int, tokens[1:])
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    pixels = raw[pos:]
    count = width * height
    if maxval < 256:
        gray = pixels[:count]
    else:
        if len(pixels) < count * 2:
            return None
        values = struct.unpack(f">{count}H", pixels[: count * 2])
        nonzero = sorted(v for v in values if v > 0)
        if nonzero:
            low = nonzero[int(len(nonzero) * 0.02)]
            high = nonzero[min(len(nonzero) - 1, int(len(nonzero) * 0.98))]
        else:
            low, high = 0, maxval
        span = max(1, high - low)
        gray = bytes(0 if v == 0 else max(0, min(255, int((v - low) * 255 / span))) for v in values)
    scanlines = b"".join(b"\x00" + gray[y * width : (y + 1) * width] for y in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += png_chunk(b"IDAT", zlib.compress(scanlines, 7))
    png += png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def message_timestamp(row: dict[str, Any]) -> Any:
    message = row.get("message")
    if isinstance(message, dict) and message.get("timestamp"):
        return message["timestamp"]
    return row.get("timestamp")


def collect_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "roles": Counter(),
        "tools": Counter(),
        "tool_errors": 0,
        "images": 0,
        "thinking_blocks": 0,
        "active_ms": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    times: list[dt.datetime] = []
    for row in rows:
        when = parse_time(message_timestamp(row))
        if when:
            times.append(when)
        message = row.get("message")
        if isinstance(message, dict):
            role = message.get("role", "unknown")
            stats["roles"][role] += 1
            if message.get("toolName"):
                stats["tools"][message["toolName"]] += 1
            if message.get("isError"):
                stats["tool_errors"] += 1
            usage = message.get("usage")
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if not isinstance(value, (int, float)):
                        continue
                    lowered = key.lower()
                    if "input" in lowered:
                        stats["input_tokens"] += int(value)
                    elif "output" in lowered:
                        stats["output_tokens"] += int(value)
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "image":
                        stats["images"] += 1
                    elif block.get("type") == "thinking":
                        stats["thinking_blocks"] += 1
        if row.get("customType") == "active_time":
            data = row.get("data")
            if isinstance(data, dict) and isinstance(data.get("milliseconds"), (int, float)):
                stats["active_ms"] += float(data["milliseconds"])
    stats["start"] = min(times) if times else None
    stats["end"] = max(times) if times else None
    stats["elapsed_s"] = (
        (stats["end"] - stats["start"]).total_seconds() if stats["start"] and stats["end"] else None
    )
    return stats


def render_block(block: dict[str, Any]) -> str:
    kind = block.get("type")
    if kind == "text":
        return f'<pre class="text-block">{esc(block.get("text", ""))}</pre>'
    if kind == "image":
        uri = data_uri(block)
        if uri:
            return f'<figure><img loading="lazy" src="{esc(uri)}"><figcaption>{esc(block.get("mimeType", "image"))}</figcaption></figure>'
        return '<div class="muted">Image block without inline data</div>'
    if kind == "toolCall":
        name = block.get("name", "tool")
        args = block.get("arguments", {})
        return (
            f'<div class="tool-title">call · {esc(name)}</div>'
            f'<pre class="json-block">{esc(pretty(args))}</pre>'
        )
    if kind == "thinking":
        return '<div class="reasoning-note">Internal reasoning block retained in the source log; content is not displayed.</div>'
    return f'<pre class="json-block">{esc(pretty(block))}</pre>'


def row_search_text(row: dict[str, Any]) -> str:
    clean = json.loads(json.dumps(row, ensure_ascii=False))
    message = clean.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        for block in message["content"]:
            if isinstance(block, dict):
                block.pop("data", None)
                block.pop("thinking", None)
                block.pop("thinkingSignature", None)
    return json.dumps(clean, ensure_ascii=False).lower()[:20000]


def render_event(row: dict[str, Any], index: int) -> str:
    message = row.get("message")
    if not isinstance(message, dict):
        kind = row.get("type", "event")
        if kind == "custom" and row.get("customType") == "active_time":
            return ""
        body = pretty({k: v for k, v in row.items() if k != "_line"}, MAX_ACTION_JSON_CHARS)
        return (
            f'<article class="event misc" data-search="{esc(row_search_text(row))}" data-role="misc">'
            f'<div class="event-head"><span class="badge">{esc(kind)}</span>'
            f'<time>{esc(local_time(row.get("timestamp")))}</time><span>#L{row.get("_line", "?")}</span></div>'
            f'<details><summary>event payload</summary><pre class="json-block">{esc(body)}</pre></details></article>'
        )

    role = str(message.get("role", "unknown"))
    tool_name = message.get("toolName")
    title = tool_name if tool_name else role
    meta: list[str] = []
    if message.get("model"):
        meta.append(str(message["model"]))
    if message.get("durationMs") is not None:
        meta.append(fmt_ms(message["durationMs"]))
    if message.get("stopReason"):
        meta.append("stop=" + str(message["stopReason"]))
    if message.get("isError"):
        meta.append("ERROR")
    rendered: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        rendered.append(f'<pre class="text-block">{esc(content)}</pre>')
    elif isinstance(content, list):
        rendered.extend(render_block(block) for block in content if isinstance(block, dict))
    if message.get("errorMessage"):
        rendered.append(f'<pre class="error-block">{esc(message["errorMessage"])}</pre>')
    usage = message.get("usage")
    if isinstance(usage, dict) and usage:
        rendered.append(f'<details><summary>usage</summary><pre class="json-block">{esc(pretty(usage))}</pre></details>')
    error_class = " error" if message.get("isError") else ""
    return (
        f'<article class="event {esc(role)}{error_class}" data-search="{esc(row_search_text(row))}" data-role="{esc(role)}">'
        f'<div class="event-head"><span class="badge">{esc(title)}</span>'
        f'<time>{esc(local_time(message_timestamp(row)))}</time>'
        f'<span>{esc(" · ".join(meta))}</span><span>#L{row.get("_line", "?")}</span></div>'
        + "".join(rendered)
        + "</article>"
    )


def request_summary(row: dict[str, Any]) -> tuple[str, str, str]:
    req = row.get("request") if isinstance(row.get("request"), dict) else {}
    args = req.get("args") if isinstance(req.get("args"), dict) else {}
    device = str(args.get("device", req.get("op", "unknown")))
    action = str(args.get("action", row.get("phase", "event")))
    rid = str(req.get("request_id", ""))
    return device, action, rid


def load_actions(evidence: pathlib.Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if evidence is None:
        return [], {}
    journal = evidence / "journal" / "actions.jsonl"
    rows = read_jsonl(journal) if journal.exists() else []
    terminal_path = evidence / "terminal.json"
    terminal = read_json(terminal_path) if terminal_path.exists() else {}
    return rows, terminal


def render_action_summary(actions: list[dict[str, Any]]) -> tuple[str, int, float]:
    requests = [row for row in actions if isinstance(row.get("request"), dict) and row.get("phase") in {"request", "begin", "start"}]
    if not requests:
        # Some journal versions use a different phase name. A request without response is unique enough.
        requests = [row for row in actions if isinstance(row.get("request"), dict) and "response" not in row]
    by_device: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    for row in requests:
        device, action, _ = request_summary(row)
        by_device[device] += 1
        by_action[action] += 1
    elapsed = sum(float(row.get("elapsed_s", 0.0)) for row in actions if isinstance(row.get("elapsed_s"), (int, float)))
    max_count = max(by_device.values(), default=1)
    bars = []
    for name, count in by_device.most_common():
        width = 100 * count / max_count
        bars.append(
            f'<div class="bar-row"><span>{esc(name)}</span><div class="bar"><i style="width:{width:.1f}%"></i></div><b>{count}</b></div>'
        )
    actions_text = ", ".join(f"{name} × {count}" for name, count in by_action.most_common())
    return "".join(bars) + f'<p class="muted">{esc(actions_text)}</p>', len(requests), elapsed


def render_action_timeline(actions: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for idx, row in enumerate(actions):
        if not isinstance(row.get("request"), dict) or "response" in row:
            continue
        device, action, rid = request_summary(row)
        args = row.get("request", {}).get("args", {})
        chunks.append(
            f'<details class="action-item" data-search="{esc((device + " " + action + " " + pretty(args)).lower())}">'
            f'<summary><time>{esc(local_time(row.get("ts")))}</time>'
            f'<span class="badge">{esc(device)}</span><b>{esc(action)}</b></summary>'
            f'<pre class="json-block">{esc(pretty(args, MAX_ACTION_JSON_CHARS))}</pre>'
            f'<div class="muted">request_id={esc(rid)} · journal row {idx + 1}</div></details>'
        )
    return "".join(chunks) or '<p class="muted">No action requests found.</p>'


def render_gallery(evidence: pathlib.Path | None) -> tuple[str, int]:
    if evidence is None:
        return '<p class="muted">No evidence directory supplied.</p>', 0
    captures = evidence / "captures"
    if not captures.exists():
        return '<p class="muted">No capture directory found.</p>', 0
    pngs = sorted(captures.glob("*.png"), key=lambda p: p.stat().st_mtime)
    cards: list[str] = []
    for image_path in pngs:
        rgb_uri = file_data_uri(image_path)
        depth_path = image_path.with_suffix(".pgm")
        depth_uri = pgm_to_png_data_uri(depth_path) if depth_path.exists() else None
        stamp = dt.datetime.fromtimestamp(image_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        depth = f'<img loading="lazy" src="{esc(depth_uri)}" alt="depth">' if depth_uri else ""
        cards.append(
            f'<article class="capture"><div class="pair"><img loading="lazy" src="{esc(rgb_uri)}" alt="RGB">{depth}</div>'
            f'<div><b>{esc(image_path.stem)}</b><span>{esc(stamp)} · RGB{(" + depth" if depth_uri else "")}</span></div></article>'
        )
    return "".join(cards) or '<p class="muted">No PNG captures found.</p>', len(pngs)


def render_recording(evidence: pathlib.Path | None) -> tuple[str, dict[str, Any]]:
    empty = {
        "available": False,
        "fps": 0.0,
        "frames": 0,
        "captured_samples": 0,
        "dropped_samples": 0,
        "videos": 0,
    }
    if evidence is None:
        return '<p class="muted">No evidence directory supplied.</p>', empty
    recording = evidence / "recording"
    manifest_path = recording / "manifest.json"
    timeline_path = recording / "frames.jsonl"
    videos = sorted(recording.glob("*.mp4")) if recording.is_dir() else []
    if not manifest_path.is_file() or not videos:
        return '<p class="muted">No RoboEnv execution recording found.</p>', empty

    manifest = read_json(manifest_path)
    timeline = read_jsonl(timeline_path) if timeline_path.is_file() else []
    timeline_payload = [
        {key: value for key, value in row.items() if key != "_line"}
        for row in timeline
    ]
    fps = float(manifest.get("fps") or 0.0)
    frame_count = int(manifest.get("encoded_frames") or 0)
    if not frame_count:
        frame_count = max(
            (int(row.get("frame_stop", 0)) for row in timeline_payload),
            default=0,
        )
    encoded_timeline = base64.b64encode(
        json.dumps(timeline_payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    players: list[str] = []
    for index, video_path in enumerate(videos):
        video_uri = file_data_uri(video_path, "video/mp4")
        player_id = f"execution-player-{index}"
        players.append(
            f'<article class="execution-player" id="{player_id}" data-fps="{fps}" '
            f'data-frames="{frame_count}" data-timeline="{encoded_timeline}">'
            f'<h3>{esc(video_path.stem)}</h3>'
            f'<video controls preload="metadata" src="{esc(video_uri)}"></video>'
            '<div class="frame-controls">'
            '<button type="button" data-step="-1">← Previous frame</button>'
            '<button type="button" data-step="1">Next frame →</button>'
            f'<input class="frame-slider" type="range" min="0" max="{max(0, frame_count - 1)}" value="0" step="1">'
            '<output class="frame-label">frame 0</output>'
            '<output class="source-label">source 0.000s</output>'
            '</div>'
            f'<p class="muted">{fps:g} FPS · {frame_count:,} encoded frames · '
            f'{esc(video_path.name)} · {video_path.stat().st_size / (1024 * 1024):.1f} MiB</p>'
            '</article>'
        )

    summary = {
        "available": True,
        "fps": fps,
        "frames": frame_count,
        "captured_samples": int(manifest.get("captured_samples") or 0),
        "dropped_samples": int(manifest.get("dropped_samples") or 0),
        "videos": len(videos),
    }
    status = esc(manifest.get("status", "unknown"))
    header = (
        '<div class="panel"><h2>RoboTwin execution recording</h2>'
        '<p class="muted">Use the buttons or slider to inspect every encoded video frame. '
        'The source timestamp comes from RoboEnv frames.jsonl.</p>'
        f'<div class="verdict-grid"><div><span>status</span><b>{status}</b></div>'
        f'<div><span>captured samples</span><b>{summary["captured_samples"]:,}</b></div>'
        f'<div><span>dropped samples</span><b>{summary["dropped_samples"]:,}</b></div></div></div>'
    )
    return header + "".join(players), summary


def terminal_summary(terminal: dict[str, Any]) -> str:
    if not terminal:
        return '<p class="muted">No terminal verdict yet.</p>'
    state = terminal.get("status") if isinstance(terminal.get("status"), dict) else terminal
    verdict = terminal.get("verdict") if isinstance(terminal.get("verdict"), dict) else {}
    fields = []
    for key in ("success", "terminal", "reason", "reward", "raw_score", "state"):
        if key in state:
            fields.append(f'<div><span>{esc(key)}</span><b>{esc(state[key])}</b></div>')
        elif key in verdict:
            fields.append(f'<div><span>{esc(key)}</span><b>{esc(verdict[key])}</b></div>')
        elif key in terminal:
            fields.append(f'<div><span>{esc(key)}</span><b>{esc(terminal[key])}</b></div>')
    return '<div class="verdict-grid">' + "".join(fields) + '</div><details><summary>terminal.json</summary><pre class="json-block">' + esc(pretty(terminal)) + "</pre></details>"


def page_html(
    title: str,
    session_path: pathlib.Path,
    rows: list[dict[str, Any]],
    evidence: pathlib.Path | None,
    actions: list[dict[str, Any]],
    terminal: dict[str, Any],
) -> str:
    stats = collect_stats(rows)
    action_chart, action_count, action_elapsed = render_action_summary(actions)
    gallery, capture_count = render_gallery(evidence)
    recording, recording_stats = render_recording(evidence)
    events = "".join(render_event(row, idx) for idx, row in enumerate(rows))
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    cards = [
        ("Session events", f"{len(rows):,}"),
        ("Model outputs", f"{stats['roles'].get('assistant', 0):,}"),
        ("Tool results", f"{stats['roles'].get('toolResult', 0):,}"),
        ("Tool errors", f"{stats['tool_errors']:,}"),
        ("Inline images", f"{stats['images']:,}"),
        ("Reasoning blocks", f"{stats['thinking_blocks']:,} hidden"),
        ("Evidence captures", f"{capture_count:,}"),
        ("Execution frames", f"{recording_stats['frames']:,}"),
        ("Robot requests", f"{action_count:,}"),
        ("Active time", fmt_ms(stats["active_ms"])),
    ]
    cards_html = "".join(f'<div class="metric"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in cards)
    model_wall = fmt_elapsed(stats["elapsed_s"])
    action_total = fmt_elapsed(action_elapsed)
    source = str(session_path)
    evidence_source = str(evidence) if evidence else "not supplied"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{--bg:#f4f0e8;--panel:#fffdf7;--ink:#262824;--muted:#72766e;--line:#d9d4c9;--blue:#386f7c;--blue2:#dbecef;--green:#237a52;--red:#a23a35;--purple:#6750a4;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
header{{padding:34px 4vw 22px;border-bottom:1px solid var(--line);background:rgba(255,253,247,.88);position:sticky;top:0;z-index:5;backdrop-filter:blur(12px)}}
h1{{margin:0;font-size:clamp(25px,4vw,44px);font-weight:650;letter-spacing:-.03em}} .sub{{color:var(--muted);margin-top:5px;word-break:break-all}}
nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}} nav button{{border:1px solid var(--line);background:#fff;padding:8px 13px;border-radius:20px;cursor:pointer}} nav button.active{{background:var(--ink);color:white}}
main{{max-width:1480px;margin:auto;padding:26px 4vw 70px}} section{{display:none}} section.active{{display:block}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin-bottom:20px}} .metric{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}} .metric span{{display:block;color:var(--muted);font-size:12px}} .metric b{{font-size:24px}}
.two-col{{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}} .panel{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px}} h2{{margin:0 0 14px;font-size:20px}} h3{{margin:0 0 8px}}
.verdict-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:12px}} .verdict-grid div{{border-left:4px solid var(--green);padding:5px 10px;background:#edf7f0}} .verdict-grid span{{display:block;color:var(--muted);font-size:11px}}
.bar-row{{display:grid;grid-template-columns:125px 1fr 35px;gap:9px;align-items:center;margin:7px 0}} .bar{{height:10px;background:#e9e5db;border-radius:99px;overflow:hidden}} .bar i{{display:block;height:100%;background:var(--blue);border-radius:99px}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;position:sticky;top:188px;z-index:4;background:var(--bg);padding:8px 0}} input[type=search]{{flex:1;min-width:220px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:white}} select{{border:1px solid var(--line);border-radius:10px;background:white;padding:9px}}
.event{{background:var(--panel);border:1px solid var(--line);border-left:5px solid #aaa;border-radius:12px;padding:13px 15px;margin:10px 0;overflow:hidden}} .event.user{{border-left-color:var(--purple)}} .event.assistant{{border-left-color:var(--blue)}} .event.toolResult{{border-left-color:var(--green)}} .event.error{{border-left-color:var(--red)}}
.event-head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-bottom:9px}} .badge{{background:var(--blue2);color:#315d66;border-radius:7px;padding:2px 8px;font-size:12px}} time{{font-variant-numeric:tabular-nums}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0;border-radius:8px;padding:10px 12px;max-height:520px;overflow:auto}} .text-block{{background:#faf8f1}} .json-block{{background:#20231f;color:#dce7dc;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}} .error-block{{background:#fff0ef;color:var(--red)}} .reasoning-note{{padding:10px 12px;background:#f0ecfa;color:#59468d;border-radius:8px}}
figure{{margin:8px 0}} figure img{{max-width:min(100%,820px);max-height:520px;border-radius:10px;border:1px solid var(--line)}} figcaption,.muted{{color:var(--muted);font-size:12px}} details summary{{cursor:pointer;color:var(--blue);margin:6px 0}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}} .capture{{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}} .capture .pair{{display:grid;grid-template-columns:1fr 1fr;background:#161816}} .capture img{{width:100%;height:240px;object-fit:contain}} .capture>div:last-child{{padding:10px 12px;display:flex;justify-content:space-between;gap:8px}} .capture span{{color:var(--muted);font-size:11px}}
.execution-player{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin:14px 0}} .execution-player video{{display:block;width:100%;max-height:72vh;background:#111;border-radius:12px}} .frame-controls{{display:grid;grid-template-columns:auto auto minmax(180px,1fr) auto auto;gap:9px;align-items:center;margin-top:12px}} .frame-controls button{{border:1px solid var(--line);background:white;border-radius:9px;padding:8px 11px;cursor:pointer}} .frame-slider{{width:100%}} .frame-controls output{{font:12px/1.4 ui-monospace,monospace;color:var(--muted);white-space:nowrap}}
.action-item{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}} .action-item summary{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;color:var(--ink)}} .hidden{{display:none!important}} .source{{font:12px/1.5 ui-monospace,monospace;word-break:break-all}}
@media(max-width:800px){{.two-col{{grid-template-columns:1fr}}header{{position:relative}}.toolbar{{top:0}}.capture img{{height:180px}}.frame-controls{{grid-template-columns:1fr 1fr}}.frame-slider{{grid-column:1/-1}}}}
</style>
</head>
<body>
<header><h1>{esc(title)}</h1><div class="sub">Kinex inference trace + RoboEnv execution evidence</div>
<nav><button class="active" data-tab="overview">Overview</button><button data-tab="trace">Inference trace</button><button data-tab="actions">Robot actions</button><button data-tab="recording">Execution video</button><button data-tab="captures">Camera captures</button></nav></header>
<main>
<section id="overview" class="active">
<div class="metrics">{cards_html}</div>
<div class="two-col"><div>
<div class="panel"><h2>Terminal verdict</h2>{terminal_summary(terminal)}</div>
<div class="panel"><h2>Robot request distribution</h2>{action_chart}</div>
</div><div>
<div class="panel"><h2>Timing</h2><div class="verdict-grid"><div><span>session wall clock</span><b>{esc(model_wall)}</b></div><div><span>summed action responses</span><b>{esc(action_total)}</b></div><div><span>active model/tool time</span><b>{esc(fmt_ms(stats['active_ms']))}</b></div></div></div>
<div class="panel"><h2>Sources</h2><p class="source">session: {esc(source)}</p><p class="source">evidence: {esc(evidence_source)}</p><p class="muted">Generated {esc(generated)}. Times are displayed in Asia/Shanghai (UTC+8). Private reasoning text is not rendered; observable prompts, outputs, calls, results, and images are retained.</p></div>
</div></div></section>
<section id="trace"><div class="toolbar"><input id="traceSearch" type="search" placeholder="Search prompts, outputs, tool names, arguments…"><select id="roleFilter"><option value="all">All roles</option><option value="user">User input</option><option value="assistant">Model output</option><option value="toolResult">Tool result</option><option value="system">System</option></select><button id="expandTrace">Expand details</button></div><div id="events">{events}</div></section>
<section id="actions"><div class="toolbar"><input id="actionSearch" type="search" placeholder="Search device, action, arguments…"><button id="expandActions">Expand all</button></div><div id="actionList">{render_action_timeline(actions)}</div></section>
<section id="recording">{recording}</section>
<section id="captures"><div class="gallery">{gallery}</div></section>
</main>
<script>
const tabs=[...document.querySelectorAll('nav button')];
tabs.forEach(b=>b.onclick=()=>{{tabs.forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('main>section').forEach(s=>s.classList.toggle('active',s.id===b.dataset.tab));}});
function filterTrace(){{const q=document.querySelector('#traceSearch').value.toLowerCase();const role=document.querySelector('#roleFilter').value;document.querySelectorAll('#events .event').forEach(e=>e.classList.toggle('hidden',!e.dataset.search.includes(q)||(role!=='all'&&e.dataset.role!==role)));}}
document.querySelector('#traceSearch').oninput=filterTrace;document.querySelector('#roleFilter').onchange=filterTrace;
document.querySelector('#actionSearch').oninput=e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('#actionList .action-item').forEach(x=>x.classList.toggle('hidden',!x.dataset.search.includes(q)));}};
function toggleAll(selector,button){{const nodes=[...document.querySelectorAll(selector)];const open=nodes.some(x=>!x.open);nodes.forEach(x=>x.open=open);button.textContent=open?'Collapse all':'Expand all';}}
document.querySelector('#expandTrace').onclick=e=>toggleAll('#events details',e.target);document.querySelector('#expandActions').onclick=e=>toggleAll('#actionList details',e.target);
document.querySelectorAll('.execution-player').forEach(player=>{{
  const video=player.querySelector('video');const slider=player.querySelector('.frame-slider');
  const frameLabel=player.querySelector('.frame-label');const sourceLabel=player.querySelector('.source-label');
  const fps=Number(player.dataset.fps)||1;const frames=Number(player.dataset.frames)||0;
  let timeline=[];try{{timeline=JSON.parse(atob(player.dataset.timeline||''));}}catch(_error){{timeline=[];}}
  const sourceFor=frame=>{{const row=timeline.find(x=>frame>=Number(x.frame_start)&&frame<Number(x.frame_stop));return row?Number(row.source_time_s):frame/fps;}};
  const update=frame=>{{frame=Math.max(0,Math.min(Math.max(0,frames-1),Math.round(frame)));slider.value=String(frame);frameLabel.value=`frame ${{frame}} / ${{Math.max(0,frames-1)}}`;sourceLabel.value=`source ${{sourceFor(frame).toFixed(3)}}s`;}};
  const seek=frame=>{{update(frame);video.currentTime=Number(slider.value)/fps+1e-6;}};
  slider.addEventListener('input',()=>seek(Number(slider.value)));
  player.querySelectorAll('[data-step]').forEach(button=>button.addEventListener('click',()=>seek(Number(slider.value)+Number(button.dataset.step))));
  video.addEventListener('timeupdate',()=>update(Math.floor(video.currentTime*fps+1e-6)));
  video.addEventListener('seeked',()=>update(Math.floor(video.currentTime*fps+1e-6)));
  update(0);
}});
</script>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=pathlib.Path, help="Kinex session JSONL")
    parser.add_argument("--evidence", type=pathlib.Path, help="RoboEnv evidence directory")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="Output HTML file")
    parser.add_argument("--title", default="Kinex run report")
    parser.add_argument("--from-line", type=int, default=1, help="First session JSONL line to include (1-based)")
    parser.add_argument("--to-line", type=int, help="Last session JSONL line to include (inclusive)")
    args = parser.parse_args()

    if not args.session.is_file():
        parser.error(f"session file not found: {args.session}")
    if args.evidence is not None and not args.evidence.is_dir():
        parser.error(f"evidence directory not found: {args.evidence}")

    rows = read_jsonl(args.session)
    rows = [
        row for row in rows
        if row.get("_line", 0) >= args.from_line
        and (args.to_line is None or row.get("_line", 0) <= args.to_line)
    ]
    actions, terminal = load_actions(args.evidence)
    report = page_html(args.title, args.session, rows, args.evidence, actions, terminal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    print(f"session events: {len(rows):,}; action records: {len(actions):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
