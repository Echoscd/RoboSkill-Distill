#!/usr/bin/env python3
"""Local, read-only live monitor for Kinex + RoboEnv runs."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def newest(root: Path, pattern: str) -> Path | None:
    if not root.is_dir():
        return None
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


@dataclass
class Resolver:
    trace: Path | None
    iterations_root: Path
    roboenv_run: Path | None

    def trace_path(self) -> Path | None:
        return self.trace or newest(self.iterations_root, "**/events.jsonl")

    def roboenv_path(self) -> Path | None:
        if self.roboenv_run:
            return self.roboenv_run
        runs = list(self.iterations_root.glob("**/run.json")) if self.iterations_root.is_dir() else []
        ready = [path for path in runs if (read_json(path) or {}).get("state") == "ready"]
        pool = ready or runs
        return max(pool, key=lambda path: path.stat().st_mtime, default=None)


class TraceStore:
    def __init__(self, resolver: Resolver):
        self.resolver = resolver
        self._signature: tuple[str, int, int] | None = None
        self._snapshot: dict[str, Any] = self.empty()
        self._image: tuple[bytes, str] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "trace": None,
            "session": {},
            "calls": [],
            "messages": [],
            "inventory": [],
            "metrics": {
                "turns": 0,
                "tool_calls": 0,
                "tool_errors": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "model_latency_ms": 0,
            },
            "agent_status": "waiting",
            "updated_at": None,
        }

    def snapshot(self) -> dict[str, Any]:
        path = self.resolver.trace_path()
        if path is None or not path.is_file():
            return self.empty()
        stat = path.stat()
        signature = (str(path), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            if signature != self._signature:
                self._snapshot, self._image = self._parse(path)
                self._signature = signature
            return self._snapshot

    def image(self) -> tuple[bytes, str] | None:
        self.snapshot()
        with self._lock:
            return self._image

    def _parse(self, path: Path) -> tuple[dict[str, Any], tuple[bytes, str] | None]:
        data = self.empty()
        data["trace"] = str(path)
        calls: dict[str, dict[str, Any]] = {}
        call_order: list[str] = []
        inventory: dict[str, dict[str, Any]] = {}
        messages: list[dict[str, Any]] = []
        latest_image: tuple[bytes, str] | None = None

        try:
            stream = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            return data, None

        with stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "session":
                    data["session"] = {
                        "id": event.get("id"),
                        "started_at": event.get("timestamp"),
                        "cwd": event.get("cwd"),
                    }
                    data["agent_status"] = "starting"
                elif kind == "agent_start":
                    data["agent_status"] = "running"
                elif kind in {"agent_end", "agent_settled"}:
                    data["agent_status"] = "complete"
                elif kind == "tool_execution_start":
                    call_id = str(event.get("toolCallId") or f"line-{line_number}")
                    name = str(event.get("toolName") or "unknown")
                    calls[call_id] = {
                        "id": call_id,
                        "name": name,
                        "args": event.get("args") or {},
                        "status": "running",
                        "duration_ms": None,
                        "result": None,
                        "is_error": False,
                        "line": line_number,
                    }
                    call_order.append(call_id)
                    inventory.setdefault(name, {"name": name, "source": "session"})
                elif kind == "tool_execution_end":
                    call_id = str(event.get("toolCallId") or f"line-{line_number}")
                    result = event.get("result") if isinstance(event.get("result"), dict) else {}
                    is_error = bool(event.get("isError") or result.get("isError"))
                    record = calls.setdefault(call_id, {
                        "id": call_id,
                        "name": str(event.get("toolName") or "unknown"),
                        "args": {},
                        "line": line_number,
                    })
                    if call_id not in call_order:
                        call_order.append(call_id)
                    record.update({
                        "status": "error" if is_error else "complete",
                        "duration_ms": event.get("durationMs") or result.get("durationMs"),
                        "result": compact_result(result),
                        "is_error": is_error,
                    })
                    found = find_image(result)
                    if found:
                        latest_image = found
                elif kind == "turn_end":
                    data["metrics"]["turns"] += 1
                    message = event.get("message") if isinstance(event.get("message"), dict) else {}
                    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
                    data["metrics"]["input_tokens"] += number(usage.get("input"))
                    data["metrics"]["cached_tokens"] += number(usage.get("cacheRead"))
                    data["metrics"]["output_tokens"] += number(usage.get("output"))
                    data["metrics"]["total_tokens"] += number(usage.get("totalTokens"))
                    cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
                    data["metrics"]["cost_usd"] += float(cost.get("total") or 0)
                    data["metrics"]["model_latency_ms"] += number(message.get("durationMs"))
                    text = message_text(message)
                    if text:
                        messages.append({"role": "assistant", "text": text[-4000:], "timestamp": message.get("timestamp")})
                elif kind == "message_end":
                    message = event.get("message") if isinstance(event.get("message"), dict) else {}
                    if message.get("role") == "system":
                        for tool in message.get("toolsAdded") or []:
                            if isinstance(tool, dict) and tool.get("name"):
                                inventory[str(tool["name"])] = {
                                    "name": str(tool["name"]),
                                    "source": "session",
                                    "description": str(tool.get("description") or "")[:240],
                                }

        ordered_calls = [calls[call_id] for call_id in call_order]
        data["calls"] = ordered_calls
        data["messages"] = messages[-24:]
        data["inventory"] = sorted(inventory.values(), key=lambda item: item["name"])
        data["metrics"]["tool_calls"] = len(ordered_calls)
        data["metrics"]["tool_errors"] = sum(1 for call in ordered_calls if call.get("is_error"))
        data["metrics"]["cost_usd"] = round(data["metrics"]["cost_usd"], 8)
        data["updated_at"] = time.time()
        if ordered_calls and ordered_calls[-1].get("status") == "running":
            data["agent_status"] = "tool-running"
        return data, latest_image


def number(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def message_text(message: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in message.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()


def compact_result(result: dict[str, Any]) -> Any:
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = str(item.get("text") or "")
        parts.append(text[:12000])
    return "\n".join(parts)


def find_image(value: Any) -> tuple[bytes, str] | None:
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("data"), str):
            try:
                return base64.b64decode(value["data"], validate=True), str(value.get("mimeType") or "image/png")
            except ValueError:
                return None
        for nested in value.values():
            found = find_image(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = find_image(nested)
            if found:
                return found
    return None


class CameraSource:
    def __init__(self, resolver: Resolver, trace: TraceStore, camera: str, min_interval: float):
        self.resolver = resolver
        self.trace = trace
        self.camera = camera
        self.min_interval = min_interval
        self._cache: tuple[bytes, str, str, float] | None = None
        self._lock = threading.Lock()

    def frame(self) -> tuple[bytes, str, str]:
        with self._lock:
            now = time.monotonic()
            if self._cache and now - self._cache[3] < self.min_interval:
                return self._cache[:3]
            try:
                image, mime = self._read_roboenv()
                self._cache = image, mime, "roboenv-live", now
                return image, mime, "roboenv-live"
            except (OSError, ValueError, KeyError, HTTPError, URLError, TimeoutError):
                fallback = self.trace.image()
                if fallback:
                    image, mime = fallback
                    self._cache = image, mime, "trace-latest", now
                    return image, mime, "trace-latest"
                raise FileNotFoundError("No live or recorded camera frame is available")

    def _read_roboenv(self) -> tuple[bytes, str]:
        run_path = self.resolver.roboenv_path()
        run = read_json(run_path)
        if not run:
            raise FileNotFoundError("RoboEnv run not found")
        endpoint = str(run.get("endpoint") or "").rstrip("/")
        session = str(run.get("session") or run.get("id") or "")
        generation = int(run.get("generation") or 0)
        if not endpoint or not session:
            raise ValueError("Incomplete RoboEnv run identity")
        request_id = f"monitor-{secrets.token_hex(8)}"
        payload = {
            "protocol": "roboenv/1",
            "session": session,
            "generation": generation,
            "request_id": request_id,
            "deadline_s": 5,
            "op": "devices.call",
            "args": {"device": self.camera, "action": "read", "args": {}},
        }
        raw = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        response = json.loads(urlopen(Request(endpoint + "/", data=raw, headers={"Content-Type": "application/json"}), timeout=6).read())
        if not response.get("ok"):
            raise ValueError(str(response.get("error") or "RoboEnv camera read failed"))
        result = response.get("result") or {}
        frame = result.get("data") or {}
        if isinstance(frame.get("color"), str):
            return base64.b64decode(frame["color"], validate=True), "image/png"
        file_name = Path(str(frame.get("file") or "")).name
        if not file_name:
            raise ValueError("RoboEnv camera read returned no color frame")
        route = f"/artifacts/{quote(session)}/{generation}/{quote(file_name)}"
        return urlopen(endpoint + route, timeout=6).read(), "image/png"


def parse_simple_yaml(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^(name|type|description):\s*(.*)$", line)
            if match:
                result[match.group(1)] = match.group(2).strip().strip("'\"")
    except OSError:
        pass
    return result


def workspace_catalog(workspace: Path, repo: Path) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    locations = [
        (workspace / ".kinex" / "tools", "custom"),
        (repo / "packages" / "core" / "assets" / "builtin" / "tool", "builtin"),
    ]
    seen: set[str] = set()
    for root, source in locations:
        if not root.is_dir():
            continue
        for spec in sorted(root.glob("*/tool.yaml")):
            values = parse_simple_yaml(spec)
            name = values.get("name") or spec.parent.name.replace("-", "_")
            if name in seen:
                continue
            seen.add(name)
            tools.append({"name": name, "source": source, "description": values.get("description", "")})

    devices: list[dict[str, str]] = []
    device_root = workspace / ".kinex" / "devices"
    if device_root.is_dir():
        for profile in sorted(device_root.glob("*/profile.yaml")):
            values = parse_simple_yaml(profile)
            if values.get("name") and values.get("type"):
                devices.append({"name": values["name"], "type": values["type"]})
    return {"tools": tools, "devices": devices}


def run_status(resolver: Resolver, trace: dict[str, Any]) -> dict[str, Any]:
    run_path = resolver.roboenv_path()
    run = read_json(run_path) or {}
    terminal = read_json(run_path.parent / "evidence" / "terminal.json") if run_path else None
    trace_path = resolver.trace_path()
    state_file = trace_path.parent / "run-state.txt" if trace_path else None
    state_values: dict[str, str] = {}
    if state_file and state_file.is_file():
        for line in state_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                state_values[key] = value
    task = run.get("task")
    status = (terminal or {}).get("status") if isinstance(terminal, dict) else {}
    verdict = (terminal or {}).get("verdict") if isinstance(terminal, dict) else {}
    return {
        "task": task,
        "run_id": run.get("id"),
        "run_state": status.get("state") or run.get("state") or trace.get("agent_status"),
        "success": status.get("success"),
        "latched": verdict.get("latched"),
        "reward": verdict.get("reward"),
        "budget_used": (status.get("budget") or {}).get("used"),
        "started": state_values.get("started") or trace.get("session", {}).get("started_at"),
        "ended": state_values.get("ended"),
        "exit_code": state_values.get("exit_code"),
        "trace": str(trace_path) if trace_path else None,
        "roboenv_run": str(run_path) if run_path else None,
    }


class MonitorHandler(SimpleHTTPRequestHandler):
    server_version = "KinexMonitor/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    @property
    def app(self) -> "MonitorServer":
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/state":
            trace = self.app.trace.snapshot()
            catalog = workspace_catalog(self.app.workspace, self.app.repo)
            catalog_names = {item["name"] for item in catalog["tools"]}
            catalog["tools"].extend(item for item in trace["inventory"] if item["name"] not in catalog_names)
            return self.send_json({"trace": trace, "catalog": catalog, "run": run_status(self.app.resolver, trace)})
        if route == "/api/frame":
            try:
                payload, mime, source = self.app.camera.frame()
            except FileNotFoundError as error:
                return self.send_json({"error": str(error)}, status=HTTPStatus.NOT_FOUND)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Kinex-Frame-Source", source)
            self.end_headers()
            self.wfile.write(payload)
            return
        if route == "/api/health":
            return self.send_json({"ok": True, "time": time.time()})
        if route == "/":
            self.path = "/index.html"
        return super().do_GET()

    def translate_path(self, path: str) -> str:
        clean = urlparse(path).path.lstrip("/") or "index.html"
        target = (STATIC / clean).resolve()
        try:
            target.relative_to(STATIC.resolve())
        except ValueError:
            return str(STATIC / "404")
        return str(target)

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class MonitorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], resolver: Resolver, workspace: Path, repo: Path, camera: str, camera_hz: float):
        self.resolver = resolver
        self.workspace = workspace
        self.repo = repo
        self.trace = TraceStore(resolver)
        self.camera = CameraSource(resolver, self.trace, camera, min_interval=1 / camera_hz)
        super().__init__(address, MonitorHandler)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--workspace", type=Path, required=True, help="Kinex workspace containing .kinex")
    result.add_argument("--repo", type=Path, default=Path.cwd(), help="Kinex source checkout")
    result.add_argument("--iterations-root", type=Path, help="Root used to auto-discover the newest trace and RoboEnv run")
    result.add_argument("--trace", type=Path, help="Explicit live events.jsonl")
    result.add_argument("--roboenv-run", type=Path, help="Explicit RoboEnv run.json")
    result.add_argument("--camera", default="head_camera")
    result.add_argument("--camera-hz", type=float, default=2.0)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8765)
    return result


def main() -> None:
    args = parser().parse_args()
    if not 0.2 <= args.camera_hz <= 5:
        raise SystemExit("--camera-hz must be between 0.2 and 5")
    iterations_root = args.iterations_root or args.repo / "env" / "iterations"
    resolver = Resolver(args.trace, iterations_root, args.roboenv_run)
    server = MonitorServer((args.host, args.port), resolver, args.workspace, args.repo, args.camera, args.camera_hz)
    print(f"Kinex monitor: http://{args.host}:{args.port}")
    print(f"workspace: {args.workspace}")
    print(f"trace: {resolver.trace_path() or 'waiting for first events.jsonl'}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
