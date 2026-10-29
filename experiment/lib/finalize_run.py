#!/usr/bin/env python3
"""Finalize one Kinex experiment run without losing failed or partial traces."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


SCHEMA = "kinex/experiment-trace-manifest/1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_state(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def first_file(root: Path, pattern: str) -> Path | None:
    return next((path for path in root.glob(pattern) if path.is_file()), None)


def file_record(path: Path | None, run_dir: Path) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    line_count = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            line_count += chunk.count(b"\n")
    try:
        relative = str(path.relative_to(run_dir))
    except ValueError:
        relative = str(path)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "lines": line_count,
        "sha256": digest.hexdigest(),
    }


def native_verdict(run_dir: Path) -> tuple[bool | None, dict[str, Any]]:
    verdict_path = run_dir / "simulator-verdict.json"
    verdict = read_json(verdict_path)
    native_path = first_file(run_dir, "**/evidence/native-episode.json")
    stop_path = run_dir / "stop.json"
    native = read_json(native_path) if native_path else {}
    stop = read_json(stop_path)
    simulation = stop.get("simulation") if isinstance(stop.get("simulation"), dict) else {}

    canonical = verdict.get("success")
    candidates = [native.get("native_success"), native.get("success_latched"), simulation.get("success")]
    if verdict_path.is_file():
        success = (
            canonical
            if isinstance(canonical, bool)
            and verdict.get("schema") == "kinex/simulator-verdict/1"
            and verdict.get("authority") == "roboenv_native_evaluator"
            and verdict.get("agent_claim_used") is False
            else None
        )
    else:
        # Compatibility for archived runs created before simulator-verdict.json
        # became a mandatory pipeline artifact.
        success = next((value for value in candidates if isinstance(value, bool)), None)
    evidence: dict[str, Any] = {
        "simulator_verdict": file_record(
            verdict_path if verdict_path.is_file() else None, run_dir
        ),
        "native_episode": file_record(native_path, run_dir),
        "stop": file_record(stop_path if stop_path.is_file() else None, run_dir),
    }
    recording_dir = native_path.parent / "recording" if native_path else None
    if recording_dir and recording_dir.is_dir():
        videos = [
            record
            for path in sorted(recording_dir.glob("*.mp4"))
            if (record := file_record(path, run_dir)) is not None
        ]
        evidence["recording"] = {
            "manifest": file_record(recording_dir / "manifest.json", run_dir),
            "timeline": file_record(recording_dir / "frames.jsonl", run_dir),
            "videos": videos,
        }
    if native:
        evidence["task"] = native.get("task")
        evidence["submitted"] = native.get("submitted")
        evidence["action_frames"] = (
            native.get("budget", {}).get("used")
            if isinstance(native.get("budget"), dict)
            else None
        )
    return success, evidence


def fallback_html(title: str, reason: str, manifest: dict[str, Any]) -> str:
    payload = html.escape(json.dumps(manifest, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:15px/1.6 system-ui,sans-serif;max-width:980px;margin:48px auto;padding:0 24px;background:#f5f1e8;color:#292b27}}
main{{background:#fffdf8;border:1px solid #d9d4c9;border-radius:16px;padding:28px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#20231f;color:#dce7dc;padding:16px;border-radius:10px}}
.error{{border-left:5px solid #a23a35;padding:10px 14px;background:#fff0ef}}
</style></head><body><main><h1>{html.escape(title)}</h1>
<p class="error">Trace visualization fallback: {html.escape(reason)}</p>
<p>The run directory and available raw artifacts were still retained.</p><pre>{payload}</pre></main></body></html>"""


def run_harness_audit(
    run_dir: Path, session: Path, manifest_path: Path
) -> dict[str, Any]:
    """Create a derived contract audit without modifying the raw session."""

    output = run_dir / "harness-audit.json"
    log = run_dir / "harness-audit.log"
    repository = Path(__file__).resolve().parents[2]
    harness = repository / "experiment" / "harness"
    if not session.is_file():
        return {"status": "skipped", "reason": "No session.jsonl was produced."}
    if not harness.is_dir():
        return {"status": "skipped", "reason": f"Harness package is missing: {harness}"}

    command = [
        sys.executable,
        "-m",
        "experiment.harness.tracing.audit_pi_session",
        "--run-dir",
        str(run_dir),
        "--output",
        output.name,
    ]
    completed = subprocess.run(
        command,
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        return {
            "status": "error",
            "error": f"Harness audit exited with code {completed.returncode}.",
            "log": file_record(log, run_dir),
        }
    return {
        "status": "complete",
        "report": file_record(output, run_dir),
        "log": file_record(log, run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--process-exit-code", type=int)
    parser.add_argument("--renderer", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = run_dir / "agent"
    state = read_state(agent_dir / "run-state.txt")
    events = agent_dir / "events.jsonl"
    session = agent_dir / "session.jsonl"
    trace = session if session.is_file() and session.stat().st_size else events if events.is_file() else None
    evidence_dir = None
    native_path = first_file(run_dir, "**/evidence/native-episode.json")
    if native_path:
        evidence_dir = native_path.parent

    native_success, native_evidence = native_verdict(run_dir)
    exit_code: int | None = args.process_exit_code
    try:
        if "exit_code" in state:
            exit_code = int(state["exit_code"])
    except ValueError:
        pass
    status = (
        "native_success"
        if native_success is True
        else "timeout"
        if exit_code in {124, 130, 137, 143}
        else "failed"
        if native_success is False
        else "incomplete"
    )
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "task": state.get("task") or native_evidence.get("task"),
        "model": state.get("model"),
        "iteration": state.get("iteration"),
        "started": state.get("started"),
        "ended": state.get("ended"),
        "process_exit_code": exit_code,
        "status": status,
        "native_success": native_success,
        "raw_artifacts": {
            "events": file_record(events if events.is_file() else None, run_dir),
            "session": file_record(session if session.is_file() else None, run_dir),
            "harness_online": file_record(
                run_dir / "harness-events.jsonl", run_dir
            ),
            "prompt": file_record(agent_dir / "prompt.txt", run_dir),
            "stderr": file_record(agent_dir / "stderr.log", run_dir),
            "failure_analysis_decision": file_record(
                run_dir / "failure-analysis-decision.json", run_dir
            ),
            "failure_analysis_session": file_record(
                agent_dir / "failure-analysis-session.jsonl", run_dir
            ),
        },
        "native_evidence": native_evidence,
        "visualization": {"path": "trace.html", "source": None},
    }
    manifest_path = run_dir / "trace-manifest.json"

    title_task = manifest.get("task") or run_dir.parent.name
    title = f"Kinex trace · {title_task} · {run_dir.name}"
    output = run_dir / "trace.html"
    renderer = args.renderer or Path(__file__).with_name("render_trace.py")
    render_error: str | None = None
    if trace is None:
        render_error = "No Kinex session.jsonl or events.jsonl was produced."
    elif not renderer.is_file():
        render_error = f"Renderer is missing: {renderer}"
    else:
        command = [
            sys.executable,
            str(renderer),
            "--session",
            str(trace),
            "--output",
            str(output),
            "--title",
            title,
        ]
        if evidence_dir:
            command.extend(["--evidence", str(evidence_dir)])
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        (run_dir / "trace-render.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )
        if completed.returncode:
            render_error = f"Renderer exited with code {completed.returncode}."
        else:
            manifest["visualization"]["source"] = str(trace.relative_to(run_dir))

    if render_error:
        manifest["visualization"]["error"] = render_error
        output.write_text(fallback_html(title, render_error, manifest), encoding="utf-8")
        if not (run_dir / "trace-render.log").exists():
            (run_dir / "trace-render.log").write_text(render_error + "\n", encoding="utf-8")

    manifest["visualization"]["bytes"] = output.stat().st_size
    # The audit reads only the public manifest verdict. Write a preliminary copy,
    # then add the audit artifact records and atomically replace it below.
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest["harness_audit"] = run_harness_audit(run_dir, session, manifest_path)
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_manifest.replace(manifest_path)
    print(json.dumps({
        "run_dir": str(run_dir),
        "status": status,
        "native_success": native_success,
        "trace": str(trace) if trace else None,
        "html": str(output),
        "render_error": render_error,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
