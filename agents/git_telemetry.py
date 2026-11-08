"""Read-only local Git repository telemetry and diff collector.

Strict safety rules:
- Read-only commands only (rev-parse, log, status, diff).
- Never push, commit, fetch, checkout, or modify Git repository state.
- Redact secrets, tokens, passwords, and sensitive keys from diff output.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from agents.llm_runtime import _redact_sensitive_content

ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_DIFF_CHARACTERS = 4000


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    executable = os.getenv("DEVOPS_GIT_CLI", "git")
    try:
        proc = subprocess.run(
            [executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def collect_git_evidence(repo_dir: Path | str | None = None) -> dict[str, Any]:
    """Collect read-only Git status, commit history, and sanitized diff."""
    target_dir = Path(repo_dir).resolve() if repo_dir else ROOT
    timestamp = time.time()

    code, branch, err = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], target_dir)
    if code != 0:
        return {
            "status": "unavailable",
            "source": "Local Git repository (read-only)",
            "timestamp": timestamp,
            "detail": f"Git repository unavailable or git not installed: {err or 'non-zero exit'}",
        }

    _, commit_sha, _ = _run_git(["rev-parse", "HEAD"], target_dir)
    _, log_out, _ = _run_git(
        ["log", "-n", "5", "--pretty=format:%h%x1f%an%x1f%ad%x1f%s", "--date=iso"],
        target_dir,
    )
    recent_commits = []
    if log_out:
        for line in log_out.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 4:
                recent_commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })

    _, status_out, _ = _run_git(["status", "--porcelain"], target_dir)
    modified_files = []
    if status_out:
        for line in status_out.splitlines():
            entry = line.strip()
            if entry:
                modified_files.append(entry)

    _, diff_stat, _ = _run_git(["diff", "--stat"], target_dir)
    _, raw_diff, _ = _run_git(["diff", "-U3"], target_dir)

    sanitized_diff = _redact_sensitive_content(raw_diff)
    truncated = len(sanitized_diff) > MAX_DIFF_CHARACTERS
    if truncated:
        sanitized_diff = sanitized_diff[:MAX_DIFF_CHARACTERS] + "\n... [diff truncated]"

    has_changes = bool(modified_files or raw_diff)
    return {
        "status": "ok",
        "source": "Local Git repository (read-only)",
        "timestamp": timestamp,
        "branch": branch,
        "commit": commit_sha[:8] if commit_sha else "unknown",
        "recent_commits": recent_commits,
        "modified_files": modified_files,
        "has_changes": has_changes,
        "diff_stat": diff_stat,
        "diff": sanitized_diff,
        "code_changes": {
            "status": "ok" if has_changes else "no_changes",
            "branch": branch,
            "commit": commit_sha[:8] if commit_sha else "unknown",
            "modified_files": modified_files,
            "diff_stat": diff_stat,
            "diff": sanitized_diff,
        },
    }

