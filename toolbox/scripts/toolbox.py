#!/usr/bin/env python3
"""Manage the scored Kinex toolbox without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TOOLBOX_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = TOOLBOX_ROOT / "tools"
REGISTRY_PATH = TOOLBOX_ROOT / "registry.json"
FAILUREBOX_DIR = TOOLBOX_ROOT / "failurebox"
FAILURE_EVENTS_DIR = FAILUREBOX_DIR / "events"
FAILURE_INDEX_PATH = FAILUREBOX_DIR / "index.json"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
VALID_STATUS = {"draft", "experimental", "validated", "deprecated"}
VALID_AUTHORS = {"gpt", "human", "joint"}
VALID_TYPES = {"atomic", "composite"}
VALID_FAILURE_STATUS = {"open", "resolved", "wont_fix"}


class ToolboxError(ValueError):
    """Raised when toolbox metadata or topology is invalid."""


@dataclass(frozen=True)
class ToolRecord:
    path: Path
    metadata: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.metadata["name"])

    @property
    def level(self) -> int:
        return int(self.metadata["level"]["score"])

    @property
    def generality(self) -> int:
        return int(self.metadata["generality"]["score"])

    @property
    def dependencies(self) -> list[str]:
        return list(self.metadata["composition"]["dependencies"])


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolboxError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolboxError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ToolboxError(f"{path} must contain a JSON object")
    return value


def require_keys(value: dict[str, Any], keys: Iterable[str], where: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ToolboxError(f"{where} is missing: {', '.join(missing)}")


def require_nonempty_strings(values: Any, where: str) -> None:
    if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
        raise ToolboxError(f"{where} must be a list of non-empty strings")


def yaml_scalar(text: str, field: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(field)}:\s*([^#\n]+?)\s*$", text)
    return match.group(1).strip().strip('"\'') if match else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ToolboxError(f"missing {path}") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ToolboxError(f"invalid JSONL in {path}:{line_number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ToolboxError(f"{path}:{line_number} must contain a JSON object")
        records.append(item)
    return records


def validate_change_log(record: ToolRecord) -> None:
    changes = read_jsonl(record.path / "changes.jsonl")
    if not changes:
        raise ToolboxError(f"{record.name}: changes.jsonl must contain at least one entry")
    for index, change in enumerate(changes, start=1):
        where = f"{record.name}.changes[{index}]"
        require_keys(change, ("timestamp", "version", "author", "change_type", "summary", "reason", "failure_ids", "files"), where)
        if not isinstance(change["timestamp"], str) or "T" not in change["timestamp"]:
            raise ToolboxError(f"{where}.timestamp must be ISO-8601")
        if not isinstance(change["version"], str) or not SEMVER_RE.fullmatch(change["version"]):
            raise ToolboxError(f"{where}.version must be semantic x.y.z")
        for field in ("author", "change_type", "summary", "reason"):
            if not isinstance(change[field], str) or not change[field].strip():
                raise ToolboxError(f"{where}.{field} must be a non-empty string")
        for field in ("failure_ids", "files"):
            if not isinstance(change[field], list) or any(not isinstance(item, str) for item in change[field]):
                raise ToolboxError(f"{where}.{field} must be a list of strings")
    if changes[-1]["version"] != record.metadata["version"]:
        raise ToolboxError(f"{record.name}: latest change version must match metadata version")


def validate_record(record: ToolRecord) -> None:
    data = record.metadata
    require_keys(
        data,
        (
            "schema_version", "name", "version", "status", "formulated_by",
            "created_at", "updated_at", "summary", "tool_type", "generality",
            "level", "composition", "provenance",
        ),
        str(record.path / "metadata.json"),
    )
    if data["schema_version"] != 1:
        raise ToolboxError(f"{record.name}: schema_version must be 1")
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise ToolboxError(f"{record.path.name}: invalid tool name {data['name']!r}")
    if record.path.name != record.name:
        raise ToolboxError(f"{record.name}: directory name must equal tool name")
    if not isinstance(data["version"], str) or not SEMVER_RE.fullmatch(data["version"]):
        raise ToolboxError(f"{record.name}: version must be semantic x.y.z")
    if data["status"] not in VALID_STATUS:
        raise ToolboxError(f"{record.name}: unsupported status {data['status']!r}")
    if data["formulated_by"] not in VALID_AUTHORS:
        raise ToolboxError(f"{record.name}: unsupported formulated_by value")
    if data["tool_type"] not in VALID_TYPES:
        raise ToolboxError(f"{record.name}: tool_type must be atomic or composite")
    for field in ("created_at", "updated_at"):
        if not isinstance(data[field], str) or not DATE_RE.fullmatch(data[field]):
            raise ToolboxError(f"{record.name}: {field} must use YYYY-MM-DD")
    if not isinstance(data["summary"], str) or len(data["summary"].strip()) < 12:
        raise ToolboxError(f"{record.name}: summary is too short")

    generality = data["generality"]
    require_keys(generality, ("score", "rationale", "assumptions", "limitations", "tested_tasks"), f"{record.name}.generality")
    if type(generality["score"]) is not int or not 1 <= generality["score"] <= 10:
        raise ToolboxError(f"{record.name}: generality.score must be an integer from 1 to 10")
    if not isinstance(generality["rationale"], str) or len(generality["rationale"].strip()) < 12:
        raise ToolboxError(f"{record.name}: generality rationale is too short")
    for field in ("assumptions", "limitations", "tested_tasks"):
        require_nonempty_strings(generality[field], f"{record.name}.generality.{field}")

    level = data["level"]
    require_keys(level, ("score", "rationale"), f"{record.name}.level")
    if type(level["score"]) is not int or not 1 <= level["score"] <= 10:
        raise ToolboxError(f"{record.name}: level.score must be an integer from 1 to 10")
    if not isinstance(level["rationale"], str) or len(level["rationale"].strip()) < 12:
        raise ToolboxError(f"{record.name}: level rationale is too short")

    composition = data["composition"]
    require_keys(composition, ("dependencies", "strategy"), f"{record.name}.composition")
    dependencies = composition["dependencies"]
    if not isinstance(dependencies, list) or any(not isinstance(item, str) or not NAME_RE.fullmatch(item) for item in dependencies):
        raise ToolboxError(f"{record.name}: dependencies must contain valid tool names")
    if len(dependencies) != len(set(dependencies)):
        raise ToolboxError(f"{record.name}: dependencies must be unique")
    if record.name in dependencies:
        raise ToolboxError(f"{record.name}: a tool cannot depend on itself")
    if data["tool_type"] == "atomic" and dependencies:
        raise ToolboxError(f"{record.name}: an atomic tool cannot declare toolbox dependencies")
    if not isinstance(composition["strategy"], str):
        raise ToolboxError(f"{record.name}: composition.strategy must be a string")

    provenance = data["provenance"]
    require_keys(provenance, ("experiment", "iteration", "failure_gap", "evidence"), f"{record.name}.provenance")
    for field in ("experiment", "iteration", "failure_gap"):
        if not isinstance(provenance[field], str):
            raise ToolboxError(f"{record.name}: provenance.{field} must be a string")
    require_nonempty_strings(provenance["evidence"], f"{record.name}.provenance.evidence")

    for required_file in ("tool.py", "tool.yaml", "toolbook.yaml", "changes.jsonl"):
        if not (record.path / required_file).is_file():
            raise ToolboxError(f"{record.name}: missing required file {required_file}")
    yaml_text = (record.path / "tool.yaml").read_text(encoding="utf-8")
    if yaml_scalar(yaml_text, "name") != record.name:
        raise ToolboxError(f"{record.name}: tool.yaml name does not match metadata")
    if yaml_scalar(yaml_text, "version") != data["version"]:
        raise ToolboxError(f"{record.name}: tool.yaml version does not match metadata")
    kind = yaml_scalar(yaml_text, "kind")
    if kind not in {"perception", "controller"}:
        raise ToolboxError(
            f"{record.name}: tool.yaml kind must be perception or controller"
        )
    if yaml_scalar(yaml_text, "manual") != "toolbook.yaml":
        raise ToolboxError(f"{record.name}: tool.yaml manual must be toolbook.yaml")
    for field in ("description", "parameters"):
        if not re.search(rf"(?m)^{field}:", yaml_text):
            raise ToolboxError(f"{record.name}: tool.yaml is missing {field}")

    toolbook_text = (record.path / "toolbook.yaml").read_text(encoding="utf-8")
    if yaml_scalar(toolbook_text, "schema_version") != "1":
        raise ToolboxError(f"{record.name}: toolbook.yaml schema_version must be 1")
    if yaml_scalar(toolbook_text, "name") != record.name:
        raise ToolboxError(f"{record.name}: toolbook.yaml name does not match metadata")
    if yaml_scalar(toolbook_text, "version") != data["version"]:
        raise ToolboxError(f"{record.name}: toolbook.yaml version does not match metadata")
    for section in ("usage", "parameters", "returns", "failure_handling", "source"):
        if not re.search(rf"(?m)^{section}:\s*(?:\{{\}})?\s*$", toolbook_text):
            raise ToolboxError(f"{record.name}: toolbook.yaml is missing {section}")
    validate_change_log(record)


def load_records(tools_dir: Path = TOOLS_DIR) -> dict[str, ToolRecord]:
    records: dict[str, ToolRecord] = {}
    if not tools_dir.is_dir():
        raise ToolboxError(f"tool directory does not exist: {tools_dir}")
    for path in sorted(item for item in tools_dir.iterdir() if item.is_dir() and not item.name.startswith(".")):
        record = ToolRecord(path=path, metadata=read_json(path / "metadata.json"))
        validate_record(record)
        if record.name in records:
            raise ToolboxError(f"duplicate tool name: {record.name}")
        records[record.name] = record
    if not records:
        raise ToolboxError(f"no tools found under {tools_dir}")
    return records


def validate_graph(records: dict[str, ToolRecord]) -> None:
    for record in records.values():
        for dependency in record.dependencies:
            if dependency not in records:
                raise ToolboxError(f"{record.name}: unknown dependency {dependency}")
            dependency_record = records[dependency]
            if dependency_record.level >= record.level:
                raise ToolboxError(
                    f"{record.name} (level {record.level}) depends on {dependency} "
                    f"(level {dependency_record.level}); dependency level must be lower"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, trail: list[str]) -> None:
        if name in visiting:
            start = trail.index(name)
            raise ToolboxError(f"dependency cycle: {' -> '.join(trail[start:] + [name])}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in records[name].dependencies:
            visit(dependency, trail + [dependency])
        visiting.remove(name)
        visited.add(name)

    for name in records:
        visit(name, [name])


def registry_payload(records: dict[str, ToolRecord]) -> dict[str, Any]:
    tools = []
    for record in sorted(records.values(), key=lambda item: (item.level, item.name)):
        data = record.metadata
        tools.append({
            "name": record.name,
            "version": data["version"],
            "status": data["status"],
            "tool_type": data["tool_type"],
            "generality": record.generality,
            "level": record.level,
            "dependencies": record.dependencies,
            "summary": data["summary"],
            "tested_tasks": data["generality"]["tested_tasks"],
            "interface": f"tools/{record.name}/tool.yaml",
            "toolbook": f"tools/{record.name}/toolbook.yaml",
            "change_log": f"tools/{record.name}/changes.jsonl",
        })
    return {"schema_version": 1, "tool_count": len(tools), "tools": tools}


def write_registry(records: dict[str, ToolRecord], path: Path = REGISTRY_PATH) -> None:
    path.write_text(json.dumps(registry_payload(records), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_failures(events_dir: Path = FAILURE_EVENTS_DIR) -> dict[str, dict[str, Any]]:
    failures: dict[str, dict[str, Any]] = {}
    if not events_dir.exists():
        return failures
    for path in sorted(events_dir.glob("*.json")):
        item = read_json(path)
        require_keys(item, ("schema_version", "failure_id", "occurred_at", "tool", "call", "error", "trace", "diagnosis", "resolution", "artifacts"), str(path))
        if item["schema_version"] != 1:
            raise ToolboxError(f"{path}: schema_version must be 1")
        failure_id = item["failure_id"]
        if not isinstance(failure_id, str) or not failure_id.startswith("failure_"):
            raise ToolboxError(f"{path}: invalid failure_id")
        if path.stem != failure_id:
            raise ToolboxError(f"{path}: filename must match failure_id")
        if failure_id in failures:
            raise ToolboxError(f"duplicate failure_id: {failure_id}")
        tool = item["tool"]
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise ToolboxError(f"{path}: tool.name is required")
        resolution = item["resolution"]
        if not isinstance(resolution, dict) or resolution.get("status") not in VALID_FAILURE_STATUS:
            raise ToolboxError(f"{path}: resolution.status must be one of {sorted(VALID_FAILURE_STATUS)}")
        failures[failure_id] = item
    return failures


def write_failure_index(failures: dict[str, dict[str, Any]]) -> None:
    FAILUREBOX_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for failure_id, item in sorted(failures.items(), key=lambda pair: (pair[1]["occurred_at"], pair[0])):
        rows.append({
            "failure_id": failure_id,
            "occurred_at": item["occurred_at"],
            "tool": item["tool"]["name"],
            "code": item["error"].get("code"),
            "stage": item["error"].get("stage"),
            "diagnosis_status": item["diagnosis"].get("status"),
            "resolution_status": item["resolution"].get("status"),
        })
    FAILURE_INDEX_PATH.write_text(
        json.dumps({"schema_version": 1, "failure_count": len(rows), "failures": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def cmd_validate(args: argparse.Namespace) -> int:
    records = load_records()
    validate_graph(records)
    failures = load_failures()
    if args.write_registry:
        write_registry(records)
        write_failure_index(failures)
        print(f"wrote {REGISTRY_PATH}")
        print(f"wrote {FAILURE_INDEX_PATH}")
    print(f"toolbox valid: {len(records)} tools, {len(failures)} failure records")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    records = load_records()
    validate_graph(records)
    print(f"{'NAME':36} {'TYPE':9} {'GEN':>3} {'LVL':>3}  DEPENDENCIES")
    for record in sorted(records.values(), key=lambda item: (item.level, item.name)):
        dependencies = ",".join(record.dependencies) or "-"
        print(f"{record.name:36} {record.metadata['tool_type']:9} {record.generality:>3} {record.level:>3}  {dependencies}")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    records = load_records()
    validate_graph(records)
    if args.format == "mermaid":
        print("flowchart TD")
        for record in sorted(records.values(), key=lambda item: item.name):
            print(f'  {record.name}["{record.name}<br/>G{record.generality} / L{record.level}"]')
        for record in sorted(records.values(), key=lambda item: item.name):
            for dependency in record.dependencies:
                print(f"  {record.name} --> {dependency}")
    else:
        print("digraph kinex_toolbox {")
        for record in sorted(records.values(), key=lambda item: item.name):
            print(f'  "{record.name}" [label="{record.name}\\nG{record.generality} L{record.level}"];')
        for record in sorted(records.values(), key=lambda item: item.name):
            for dependency in record.dependencies:
                print(f'  "{record.name}" -> "{dependency}";')
        print("}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    if not NAME_RE.fullmatch(args.name):
        raise ToolboxError("tool name must use lowercase snake_case")
    destination = TOOLS_DIR / args.name
    if destination.exists():
        raise ToolboxError(f"tool already exists: {destination}")
    dependencies = list(args.depends_on or [])
    if args.type == "atomic" and dependencies:
        raise ToolboxError("atomic tools cannot declare toolbox dependencies")
    if dependencies:
        records = load_records()
        missing = sorted(set(dependencies) - set(records))
        if missing:
            raise ToolboxError(f"unknown dependencies: {', '.join(missing)}")
        too_high = [name for name in dependencies if records[name].level >= args.level]
        if too_high:
            raise ToolboxError(f"dependencies must be below level {args.level}: {', '.join(too_high)}")

    destination.mkdir(parents=True)
    metadata = {
        "schema_version": 1,
        "name": args.name,
        "version": "0.1.0",
        "status": "draft",
        "formulated_by": "gpt",
        "created_at": args.date,
        "updated_at": args.date,
        "summary": args.summary,
        "tool_type": args.type,
        "domains": [],
        "generality": {
            "score": args.generality,
            "rationale": "TODO: justify this score against SCORING.md.",
            "assumptions": ["TODO: state the narrowest implementation assumption."],
            "limitations": ["TODO: state a known non-transfer case."],
            "tested_tasks": [],
        },
        "level": {
            "score": args.level,
            "rationale": "TODO: explain the composed operations and control scope.",
        },
        "composition": {
            "dependencies": dependencies,
            "strategy": "TODO: describe how dependency outputs are combined." if dependencies else "",
        },
        "provenance": {
            "experiment": args.experiment,
            "iteration": args.iteration,
            "failure_gap": "TODO: state the observed capability gap.",
            "evidence": [],
        },
    }
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / "tool.yaml").write_text(
        f"name: {args.name}\nversion: 0.1.0\ntitle: {args.name.replace('_', ' ').title()}\nkind: perception\n"
        f"description: >-\n  {args.summary}\n"
        "parameters:\n  type: object\n  additionalProperties: false\n  properties: {}\n"
        "annotations:\n  read_only: true\n  destructive: false\n  idempotent: true\n  open_world: false\n"
        "manual: toolbook.yaml\nentry: tool.py\ntimeout_s: 30\n",
        encoding="utf-8",
    )
    (destination / "toolbook.yaml").write_text(
        f"schema_version: 1\nname: {args.name}\nversion: 0.1.0\n"
        f"summary: >-\n  {args.summary}\n"
        "usage:\n  when_to_use: []\n  when_not_to_use: []\n  prerequisites: []\n  examples: []\n"
        "parameters: {}\nreturns: {}\n"
        "failure_handling:\n  inspect_order: [tool.yaml, toolbook.yaml, tool.py]\n  known_failures: []\n  recovery: []\n"
        "source:\n  entrypoint: tool.py\n  implementation: []\n  tests: []\n",
        encoding="utf-8",
    )
    (destination / "tool.py").write_text(
        '#!/usr/bin/env python3\n"""TODO: implement the Kinex tool."""\n\n'
        "from kinex import fail\n\nfail(\"tool is not implemented\")\n",
        encoding="utf-8",
    )
    change = {
        "timestamp": f"{args.date}T00:00:00Z", "version": "0.1.0", "author": "gpt",
        "change_type": "create", "summary": "Create the layered tool skeleton.",
        "reason": "Provide a runtime contract, on-demand manual, source, and auditable history.",
        "failure_ids": [], "files": ["tool.yaml", "toolbook.yaml", "tool.py", "metadata.json", "changes.jsonl"],
    }
    (destination / "changes.jsonl").write_text(json.dumps(change, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"created {destination}")
    print("complete TODO fields and add evidence before validation")
    return 0


def dependency_closure(names: Iterable[str], records: dict[str, ToolRecord]) -> set[str]:
    selected: set[str] = set()

    def add(name: str) -> None:
        if name not in records:
            raise ToolboxError(f"unknown tool requested for install: {name}")
        if name in selected:
            return
        selected.add(name)
        for dependency in records[name].dependencies:
            add(dependency)

    for name in names:
        add(name)
    return selected


def cmd_resolve(args: argparse.Namespace) -> int:
    """Print one dependency-closed tool name per line for shell manifests."""
    records = load_records()
    validate_graph(records)
    selected = dependency_closure(args.tools, records) if args.tools else set(records)
    for name in sorted(selected, key=lambda item: (records[item].level, item)):
        print(name)
    return 0


def cmd_record_failure(args: argparse.Namespace) -> int:
    records = load_records()
    if args.tool not in records:
        raise ToolboxError(f"unknown tool: {args.tool}")
    try:
        call_arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        raise ToolboxError(f"--arguments must be a JSON object: {exc}") from exc
    if not isinstance(call_arguments, dict):
        raise ToolboxError("--arguments must be a JSON object")
    occurred_at = args.occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stamp = re.sub(r"[^0-9]", "", occurred_at)[:14]
    suffix = args.id_suffix or f"{len(list(FAILURE_EVENTS_DIR.glob('*.json'))) + 1:04d}"
    failure_id = f"failure_{stamp}_{suffix}"
    event = {
        "schema_version": 1,
        "failure_id": failure_id,
        "occurred_at": occurred_at,
        "tool": {"name": args.tool, "version": records[args.tool].metadata["version"], "kind": yaml_scalar((records[args.tool].path / "tool.yaml").read_text(encoding="utf-8"), "kind")},
        "call": {"arguments": call_arguments},
        "error": {"stage": args.stage, "code": args.code, "message": args.message},
        "trace": {"session_id": args.session_id, "run_id": args.run_id, "trace_ref": args.trace_ref},
        "diagnosis": {"status": "unreviewed", "category": None, "root_cause": None, "confidence": None},
        "resolution": {"status": "open", "tool_version": None, "change_log_ref": None, "notes": None},
        "artifacts": list(args.artifact or []),
    }
    FAILURE_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = FAILURE_EVENTS_DIR / f"{failure_id}.json"
    if path.exists():
        raise ToolboxError(f"failure record already exists: {path}")
    path.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_failure_index(load_failures())
    print(f"recorded {failure_id} -> {path}")
    return 0


def cmd_log_change(args: argparse.Namespace) -> int:
    records = load_records()
    if args.tool not in records:
        raise ToolboxError(f"unknown tool: {args.tool}")
    record = records[args.tool]
    if not SEMVER_RE.fullmatch(args.version):
        raise ToolboxError("--version must be semantic x.y.z")
    known_failures = load_failures()
    missing = sorted(set(args.failure_id or []) - set(known_failures))
    if missing:
        raise ToolboxError(f"unknown failure IDs: {', '.join(missing)}")
    change = {
        "timestamp": args.timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": args.version,
        "author": args.author,
        "change_type": args.change_type,
        "summary": args.summary,
        "reason": args.reason,
        "failure_ids": list(args.failure_id or []),
        "files": list(args.file or []),
    }
    with (record.path / "changes.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(change, ensure_ascii=False) + "\n")
    print(f"logged change for {args.tool} {args.version}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    records = load_records()
    validate_graph(records)
    selected = dependency_closure(args.tools, records) if args.tools else set(records)
    destination = Path(args.destination).expanduser().resolve()
    if destination == Path(destination.anchor):
        raise ToolboxError("refusing to install tools into a filesystem root")
    for name in sorted(selected):
        source = records[name].path
        target = destination / name
        print(f"{'would install' if args.dry_run else 'installing'} {name} -> {target}")
        if args.dry_run:
            continue
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if item.name in {"metadata.json", "changes.jsonl", "__pycache__"} or item.name.startswith("test_"):
                continue
            if item.is_dir():
                shutil.copytree(item, target / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target / item.name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate metadata and dependency topology")
    validate_parser.add_argument("--write-registry", action="store_true")
    validate_parser.set_defaults(func=cmd_validate)

    list_parser = subparsers.add_parser("list", help="list tools and scores")
    list_parser.set_defaults(func=cmd_list)

    graph_parser = subparsers.add_parser("graph", help="print the dependency graph")
    graph_parser.add_argument("--format", choices=("mermaid", "dot"), default="mermaid")
    graph_parser.set_defaults(func=cmd_graph)

    new_parser = subparsers.add_parser("new", help="scaffold a GPT-formulated tool")
    new_parser.add_argument("name")
    new_parser.add_argument("--type", choices=sorted(VALID_TYPES), required=True)
    new_parser.add_argument("--generality", type=int, choices=range(1, 11), required=True)
    new_parser.add_argument("--level", type=int, choices=range(1, 11), required=True)
    new_parser.add_argument("--summary", required=True)
    new_parser.add_argument("--depends-on", nargs="*", default=[])
    new_parser.add_argument("--date", default=date.today().isoformat())
    new_parser.add_argument("--experiment", default="")
    new_parser.add_argument("--iteration", default="")
    new_parser.set_defaults(func=cmd_new)

    install_parser = subparsers.add_parser("install", help="install runtime files into a Kinex workspace")
    install_parser.add_argument("--destination", required=True)
    install_parser.add_argument("--tools", nargs="*", default=[])
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(func=cmd_install)

    resolve_parser = subparsers.add_parser("resolve", help="print the dependency closure for a tool selection")
    resolve_parser.add_argument("--tools", nargs="*", default=[])
    resolve_parser.set_defaults(func=cmd_resolve)

    failure_parser = subparsers.add_parser("record-failure", help="record one failed tool invocation in failurebox")
    failure_parser.add_argument("--tool", required=True)
    failure_parser.add_argument("--stage", required=True, choices=("selection", "validation", "runtime", "verification"))
    failure_parser.add_argument("--code", required=True)
    failure_parser.add_argument("--message", required=True)
    failure_parser.add_argument("--arguments", default="{}")
    failure_parser.add_argument("--session-id")
    failure_parser.add_argument("--run-id")
    failure_parser.add_argument("--trace-ref")
    failure_parser.add_argument("--artifact", action="append", default=[])
    failure_parser.add_argument("--occurred-at")
    failure_parser.add_argument("--id-suffix")
    failure_parser.set_defaults(func=cmd_record_failure)

    change_parser = subparsers.add_parser("log-change", help="append an auditable tool modification record")
    change_parser.add_argument("--tool", required=True)
    change_parser.add_argument("--version", required=True)
    change_parser.add_argument("--author", choices=("gpt", "human", "joint", "migration"), required=True)
    change_parser.add_argument("--change-type", choices=("create", "contract", "implementation", "documentation", "fix", "structure"), required=True)
    change_parser.add_argument("--summary", required=True)
    change_parser.add_argument("--reason", required=True)
    change_parser.add_argument("--failure-id", action="append", default=[])
    change_parser.add_argument("--file", action="append", default=[])
    change_parser.add_argument("--timestamp")
    change_parser.set_defaults(func=cmd_log_change)
    return parser


def main() -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args()
        return int(arguments.func(arguments))
    except ToolboxError as exc:
        print(f"toolbox error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

