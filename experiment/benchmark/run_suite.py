#!/usr/bin/env python3
"""Run the installed RoboTwin ALOHA catalog serially through the shared harness.

One immutable attempt per task, native verdicts, complete traces and videos.
The default is a seed-0 demo_clean coverage pass, not an official multi-seed score.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprint(repo):
    paths = [repo / "experiment/toolset.txt"]
    for relative in ["toolbox/tools", "experiment/runtime", "experiment/prompts",
                     "experiment/skills", "experiment/harness", "experiment/lib"]:
        paths.extend(p for p in (repo / relative).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and not any(part in {"runs", "private-config", "private-data"} for part in p.parts)
            and p.suffix in {".py", ".yaml", ".json", ".jsonl", ".txt", ".mjs", ".sh", ".md"})
    return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


def read_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def discover(catalog, upstream, seed):
    import yaml
    jobs = []
    for source in sorted(catalog.rglob("task.yaml")):
        task = yaml.safe_load(source.read_text(encoding="utf-8"))
        if task.get("robot") != "robotwin/robotwin-aloha-agilex":
            continue
        native_name = task["backend_kwargs"]["task_name"]
        goal = task["instruction"].strip()
        goal_source = str(source)
        if re.search(r"\{[^}]+\}", goal):
            description = upstream / "description/task_instruction" / (native_name + ".json")
            goal = " ".join(read_object(description).get("full_description", "").split())
            goal_source = str(description)
            if not goal or re.search(r"\{[^}]+\}", goal):
                raise ValueError(f"No usable public instruction for {task['id']}")
        task.update(seed=seed, instruction=goal, budget_mode="practice",
                    execution_mode="realtime", stop_on_success=True)
        task["backend_kwargs"].update(task_config="demo_clean", allow_seed_substitution=False)
        jobs.append({"task_id": task["id"], "native_task": native_name,
            "goal": goal, "goal_source": goal_source,
            "catalog_instruction": yaml.safe_load(source.read_text())["instruction"],
            "task_config": task})
    if not jobs or len({job["task_id"] for job in jobs}) != len(jobs):
        raise ValueError("Catalog is empty or contains duplicate task IDs")
    return jobs


def prepare(batch, catalog, upstream, seed):
    import yaml
    manifest_file = batch / "suite-manifest.json"
    if manifest_file.exists():
        return read_object(manifest_file)
    jobs = discover(catalog, upstream, seed)
    for index, job in enumerate(jobs, 1):
        task_dir = batch / "tasks" / f"{index:03d}_{job['native_task']}"
        task_dir.mkdir(parents=True, exist_ok=False)
        (task_dir / "task.json").write_text(json.dumps({"task_id": job["task_id"], "goal": job["goal"]}), encoding="utf-8")
        (task_dir / "task.yaml").write_text(yaml.safe_dump(job.pop("task_config"), sort_keys=False), encoding="utf-8")
        job.update(index=index, task_dir=str(task_dir), run_dir=str(batch / "runs" / f"{index:03d}_{job['native_task']}"))
    manifest = {"schema": "kinex/benchmark-suite/1", "created_at": now(), "seed": seed,
        "configuration": "demo_clean", "embodiment": "aloha_agilex", "concurrency": 1,
        "model": os.environ.get("KINEX_EXPERIMENT_MODEL", "openrouter/qwen/qwen3.8-max-0902"),
        "thinking": os.environ.get("KINEX_THINKING_LEVEL", "low"),
        "action_timeout_s": int(os.environ.get("KINEX_EXPERIMENT_TIMEOUT_S", "600")),
        "failure_analysis_timeout_s": int(os.environ.get("KINEX_FAILURE_ANALYSIS_TIMEOUT_S", "360")),
        "protocol": "absolute_joint_position_25hz_practice", "official_multi_seed_score": False,
        "task_count": len(jobs), "source_sha256": fingerprint(REPO), "jobs": jobs}
    write_json(manifest_file, manifest)
    return manifest


def run(batch, manifest):
    events_file = batch / "suite-events.jsonl"
    results_file = batch / "suite-results.json"
    prior = read_object(results_file).get("results", [])
    results = {item["task_id"]: item for item in prior}

    def event(kind, **values):
        record = {"time": now(), "event": kind, **values}
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    def state(status, current=None):
        write_json(batch / "suite-state.json", {"status": status, "updated_at": now(),
            "total": len(manifest["jobs"]), "completed": len(results), "current": current})

    for job in manifest["jobs"]:
        if job["task_id"] in results:
            continue
        if (batch / "STOP_AFTER_CURRENT").exists():
            state("stopped_by_request")
            event("stopped_by_request")
            return 0
        if fingerprint(REPO) != manifest["source_sha256"]:
            state("source_changed")
            event("source_changed", message="Source changed; refusing to mix versions in one suite.")
            return 3
        run_dir = Path(job["run_dir"])
        if run_dir.exists():
            # An interrupted attempt is preserved; resume never overwrites it.
            state("attention_required", job)
            event("existing_incomplete_attempt", task_id=job["task_id"], run_dir=str(run_dir))
            return 4
        state("running", job)
        event("task_started", task_id=job["task_id"], index=job["index"], run_dir=str(run_dir))
        environment = {**os.environ, "KINEX_EXPERIMENT_MODEL": manifest["model"],
            "KINEX_THINKING_LEVEL": manifest["thinking"],
            "KINEX_EXPERIMENT_TIMEOUT_S": str(manifest["action_timeout_s"]),
            "KINEX_FAILURE_ANALYSIS_TIMEOUT_S": str(manifest["failure_analysis_timeout_s"]),
            "KINEX_AUTO_FORMULATE": "0"}
        with (batch / f"task_{job['index']:03d}.log").open("x", encoding="utf-8") as log:
            process = subprocess.run(["bash", str(REPO / "experiment/runtime/start-task.sh"),
                job["task_dir"], str(run_dir)], cwd=REPO, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        if not (run_dir / "trace-manifest.json").exists():
            subprocess.run([sys.executable, str(REPO / "experiment/lib/finalize_run.py"),
                "--run-dir", str(run_dir), "--process-exit-code", str(process.returncode)], cwd=REPO, check=False)
        verdict = read_object(run_dir / "simulator-verdict.json")
        authoritative = (verdict.get("schema") == "kinex/simulator-verdict/1"
            and verdict.get("authority") == "roboenv_native_evaluator"
            and verdict.get("agent_claim_used") is False)
        success = verdict.get("success") if authoritative and isinstance(verdict.get("success"), bool) else None
        result = {"task_id": job["task_id"], "index": job["index"], "finished_at": now(),
            "process_exit_code": process.returncode, "native_success": success,
            "status": "success" if success is True else "failure" if success is False else "unscored_error",
            "trace": str(run_dir / "trace.html"), "run_dir": str(run_dir)}
        results[job["task_id"]] = result
        write_json(results_file, {"schema": "kinex/benchmark-results/1", "updated_at": now(),
            "total": len(manifest["jobs"]), "completed": len(results), "results": list(results.values())})
        event("task_finished", **result)
    state("complete")
    event("suite_complete", tasks=len(results))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    batch = args.batch_dir.resolve()
    batch.mkdir(parents=True, exist_ok=True)
    # flock prevents two drivers from sharing mutable simulator device profiles.
    import fcntl
    with (REPO / "env/benchmark-runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare(batch, REPO / "env/RoboEnv/catalog/tasks/robotwin",
            REPO / "env/RoboEnv/third_party/RoboTwin", args.seed)
        raise SystemExit(0 if args.prepare_only else run(batch, manifest))
