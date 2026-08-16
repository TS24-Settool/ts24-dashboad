#!/usr/bin/env python3
"""Non-destructive TS24 L0 quality gate.

This runner never executes git add/stash/tag/reset/checkout and never restores
files automatically. It writes evidence only under .gate/.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GATE_DIR = Path(__file__).resolve().parent
CASES = GATE_DIR / "golden_cases.yaml"
ARTIFACTS = ROOT / ".gate"
BACKUPS = ARTIFACTS / "backups"
JOB_RE = re.compile(r"^JOB-[0-9]{4,}$")
RUNNER_VERSION = "0.1.0-foundation"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cfg(path: Path = CASES) -> dict[str, Any]:
    # JSON is a strict subset of YAML. Keeping the .yaml filename preserves the
    # gate contract while avoiding a bootstrapping dependency on PyYAML.
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("gate config must be a mapping")
    return value


def run_process(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 180,
) -> tuple[int, str]:
    """Run an argv list without a shell and return exit code/output tail."""
    if not command or not all(isinstance(x, str) and x for x in command):
        return 125, "RUNNER ERROR: command must be a non-empty argv list"
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode, output[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT: exceeded {timeout}s"
    except Exception as exc:
        return 125, f"RUNNER ERROR: {type(exc).__name__}: {exc}"


def git(args: list[str]) -> tuple[int, str]:
    return run_process(["git", *args], cwd=ROOT, timeout=120)


def require_git_repo() -> None:
    rc, out = git(["rev-parse", "--show-toplevel"])
    if rc != 0:
        raise RuntimeError(f"not a git repository: {out}")
    if Path(out.strip()).resolve() != ROOT.resolve():
        raise RuntimeError(f"runner root mismatch: expected {ROOT}, got {out.strip()}")


def parse_porcelain_paths(raw: str) -> set[str]:
    """Return paths from git status --porcelain=v1 -z, including rename targets."""
    parts = raw.split("\0")
    paths: set[str] = set()
    idx = 0
    while idx < len(parts):
        item = parts[idx]
        idx += 1
        if not item:
            continue
        status = item[:2]
        path = item[3:]
        if path:
            paths.add(path)
        if "R" in status or "C" in status:
            if idx < len(parts) and parts[idx]:
                paths.add(parts[idx])
                idx += 1
    return paths


def current_status() -> tuple[str, set[str]]:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=str(ROOT),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    raw = proc.stdout.decode("utf-8", errors="surrogateescape")
    return raw, parse_porcelain_paths(raw)


def safe_snapshot_name(index: int, rel: str) -> str:
    suffix = Path(rel).name or "root"
    return f"{index:04d}-{suffix}"


def snapshot_path(src: Path, dest: Path) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": str(src),
        "exists": src.exists(),
        "kind": "missing",
        "sha256": None,
        "snapshot": None,
    }
    if not src.exists():
        return item
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dest)
        item.update(kind="file", sha256=sha256_file(src), snapshot=str(dest))
    elif src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=False)
        item.update(kind="directory", snapshot=str(dest))
    else:
        item.update(kind="unsupported")
    return item


def checkpoint(cfg: dict[str, Any]) -> dict[str, Any]:
    require_git_repo()
    stamp = utc_stamp()
    checkpoint_id = f"gate-ckpt-{stamp}"
    dest = BACKUPS / checkpoint_id
    dest.mkdir(parents=True, exist_ok=False)

    rc, head = git(["rev-parse", "HEAD"])
    if rc != 0:
        raise RuntimeError(head)
    status_raw, dirty_paths = current_status()

    rc, unstaged = git(["diff", "--binary", "--no-ext-diff"])
    if rc != 0:
        raise RuntimeError(unstaged)
    rc, staged = git(["diff", "--cached", "--binary", "--no-ext-diff"])
    if rc != 0:
        raise RuntimeError(staged)

    evidence = dest / "evidence"
    evidence.mkdir()
    (evidence / "status.porcelain").write_bytes(status_raw.encode("utf-8", errors="surrogateescape"))
    (evidence / "diff.unstaged.patch").write_text(unstaged, encoding="utf-8")
    (evidence / "diff.staged.patch").write_text(staged, encoding="utf-8")

    dirty_snapshots: list[dict[str, Any]] = []
    dirty_dir = dest / "dirty-at-checkpoint"
    for index, rel in enumerate(sorted(dirty_paths), 1):
        src = ROOT / rel
        snap = dirty_dir / safe_snapshot_name(index, rel)
        record = snapshot_path(src, snap)
        record["relative_path"] = rel
        dirty_snapshots.append(record)

    configured_snapshots: list[dict[str, Any]] = []
    files_dir = dest / "configured-files"
    for index, rel in enumerate(cfg.get("backup", {}).get("snapshot_paths", []), 1):
        src = (ROOT / rel).resolve()
        snap = files_dir / safe_snapshot_name(index, rel)
        record = snapshot_path(src, snap)
        record["configured_path"] = rel
        configured_snapshots.append(record)

    record = {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "checkpoint": checkpoint_id,
        "created_at": stamp,
        "repository_root": str(ROOT),
        "git_head": head.strip(),
        "git_status_sha256": sha256_bytes(status_raw.encode("utf-8", errors="surrogateescape")),
        "unstaged_diff_sha256": sha256_bytes(unstaged.encode("utf-8")),
        "staged_diff_sha256": sha256_bytes(staged.encode("utf-8")),
        "gate_config_sha256": sha256_file(CASES),
        "dirty_paths": sorted(dirty_paths),
        "dirty_snapshots": dirty_snapshots,
        "configured_snapshots": configured_snapshots,
        "restore_policy": "manual_only_no_commands_executed",
    }
    write_json(dest / "manifest.json", record)
    write_json(ARTIFACTS / "last_checkpoint.json", record)
    return record


def get_checkpoint() -> dict[str, Any]:
    path = ARTIFACTS / "last_checkpoint.json"
    if not path.exists():
        raise RuntimeError("checkpoint missing; run checkpoint first")
    record = json.loads(path.read_text(encoding="utf-8"))
    if Path(record.get("repository_root", "")).resolve() != ROOT.resolve():
        raise RuntimeError("checkpoint belongs to a different repository")
    return record


def workdir_for(case: dict[str, Any], defaults: dict[str, Any]) -> Path:
    raw = case.get("workdir", defaults.get("workdir", "."))
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"workdir escapes repository: {raw}") from exc
    return path


def run_group(
    items: list[dict[str, Any]],
    defaults: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in items:
        if not case.get("enabled", True):
            results.append({**case, "status": "SKIP", "exit": None, "output": "enabled: false"})
            continue
        command = case.get("cmd")
        if not isinstance(command, list):
            results.append({
                **case,
                "status": "FAIL",
                "exit": 125,
                "output": "RUNNER ERROR: cmd must be an argv YAML list; shell strings are forbidden",
            })
            continue
        try:
            cwd = workdir_for(case, defaults)
        except ValueError as exc:
            results.append({**case, "status": "FAIL", "exit": 125, "output": str(exc)})
            continue
        rc, output = run_process(
            command,
            cwd=cwd,
            timeout=int(case.get("timeout_sec", defaults.get("timeout_sec", 180))),
        )
        results.append({
            **case,
            "status": "PASS" if rc == 0 else "FAIL",
            "exit": rc,
            "output": output,
        })
    return results


def decide(
    baseline: list[dict[str, Any]],
    golden: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[str, str]:
    baseline_fail = [x for x in baseline if x["status"] == "FAIL"]
    golden_fail = [x for x in golden if x["status"] == "FAIL"]
    golden_enabled = [x for x in golden if x["status"] != "SKIP"]
    if baseline_fail and policy.get("block_on_baseline_fail", True):
        return "REJECTED", f"baseline failures: {len(baseline_fail)}"
    if golden_fail and policy.get("block_on_any_golden_fail", True):
        return "BLOCKED", f"golden failures: {len(golden_fail)}"
    if policy.get("require_enabled_golden", True) and not golden_enabled:
        return "NOT_READY", "no Golden Eval is enabled"
    return "READY_FOR_L2", "L0 passed; prepare independent Reviewer packet"


def capture_job_diff(job: str, checkpoint_record: dict[str, Any]) -> dict[str, Any]:
    """Capture auditable final git diff and metadata without changing git state."""
    job_dir = ARTIFACTS / "jobs" / job
    job_dir.mkdir(parents=True, exist_ok=True)
    rc, full_diff = git(["diff", "--binary", "--no-ext-diff", "HEAD"])
    if rc != 0:
        raise RuntimeError(full_diff)
    status_raw, paths = current_status()
    diff_path = job_dir / "git-diff.patch"
    diff_path.write_text(full_diff, encoding="utf-8")
    status_path = job_dir / "git-status.porcelain"
    status_path.write_bytes(status_raw.encode("utf-8", errors="surrogateescape"))
    return {
        "diff_file": str(diff_path.relative_to(ROOT)),
        "diff_sha256": sha256_file(diff_path),
        "status_file": str(status_path.relative_to(ROOT)),
        "status_sha256": sha256_file(status_path),
        "changed_paths": sorted(paths),
        "diff_scope_note": (
            "Diff is against HEAD and may include pre-existing worktree changes. "
            "Reviewer must compare changed_paths with checkpoint dirty_paths."
        ),
        "checkpoint_dirty_paths": checkpoint_record.get("dirty_paths", []),
    }


def validate_requirements(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "sha256": None, "status": "missing"}
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError(f"requirements file not found: {resolved}")
    return {"path": str(resolved), "sha256": sha256_file(resolved), "status": "present"}


def run_gate(job: str, requirements: Path | None) -> tuple[int, dict[str, Any]]:
    if not JOB_RE.fullmatch(job):
        raise RuntimeError("job id must match JOB-0001 (at least four digits)")
    cfg = load_cfg()
    checkpoint_record = get_checkpoint()
    baseline = run_group(cfg.get("baseline", []), cfg.get("defaults", {}))
    golden = run_group(cfg.get("golden_cases", []), cfg.get("defaults", {}))
    verdict, reason = decide(baseline, golden, cfg.get("policy", {}))
    diff = capture_job_diff(job, checkpoint_record)
    req = validate_requirements(requirements)
    if req["status"] == "missing" and verdict == "READY_FOR_L2":
        verdict, reason = "NOT_READY", "requirements snapshot missing"
    result = {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "job": job,
        "verdict": verdict,
        "reason": reason,
        "generated_at": utc_stamp(),
        "repository_root": str(ROOT),
        "checkpoint": checkpoint_record,
        "requirements": req,
        "gate_config_sha256": sha256_file(CASES),
        "baseline": baseline,
        "golden": golden,
        "diff": diff,
        "reviewer_can_override_l0": False,
        "next_step": "L2_REVIEW" if verdict == "READY_FOR_L2" else "RETURN_TO_BUILDER",
    }
    write_json(ARTIFACTS / f"{job}.json", result)
    return (0 if verdict == "READY_FOR_L2" else 1), result


def restore_plan() -> dict[str, Any]:
    checkpoint_record = get_checkpoint()
    return {
        "checkpoint": checkpoint_record["checkpoint"],
        "policy": "manual_only",
        "warning": "No restore command was executed. Review each file with Tatsuki before replacement.",
        "configured_snapshots": checkpoint_record.get("configured_snapshots", []),
        "dirty_snapshots": checkpoint_record.get("dirty_snapshots", []),
        "git_head_at_checkpoint": checkpoint_record.get("git_head"),
        "forbidden_automatic_actions": [
            "git reset --hard",
            "git checkout --",
            "git clean",
            "database overwrite",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TS24 non-destructive quality gate")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("checkpoint")
    run_parser = subs.add_parser("run")
    run_parser.add_argument("--job", required=True)
    run_parser.add_argument("--requirements", type=Path)
    subs.add_parser("restore-plan")
    args = parser.parse_args()

    try:
        if args.command == "checkpoint":
            record = checkpoint(load_cfg())
            print(json.dumps({
                "checkpoint": record["checkpoint"],
                "git_head": record["git_head"],
                "dirty_paths": len(record["dirty_paths"]),
                "policy": record["restore_policy"],
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == "run":
            rc, result = run_gate(args.job, args.requirements)
            print(json.dumps({
                "job": result["job"],
                "verdict": result["verdict"],
                "reason": result["reason"],
                "next_step": result["next_step"],
                "artifact": f".gate/{result['job']}.json",
            }, ensure_ascii=False, indent=2))
            return rc
        if args.command == "restore-plan":
            print(json.dumps(restore_plan(), ensure_ascii=False, indent=2))
            return 0
    except Exception as exc:
        print(f"GATE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
