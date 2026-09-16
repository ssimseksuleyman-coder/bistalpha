#!/usr/bin/env python3
"""Durably reserve a report slot before a producer starts.

The local report gate state is not enough for two GitHub runners.  The claim
must reach origin before either producer is allowed to run its daemon.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import report_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_REL = "docs/state/report_runs.json"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _output(key: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def _failure_detail(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    return detail[-500:] if detail else f"exit={proc.returncode}"


def _branch_name() -> str:
    branch = os.environ.get("GITHUB_REF_NAME")
    if branch:
        return branch
    return _git("branch", "--show-current").stdout.strip() or "main"


def _commit_claim(label: str) -> str:
    """Commit only the local claim and return its commit SHA."""
    _git("add", "-f", STATE_REL)
    staged_paths = _git("diff", "--cached", "--name-only").stdout.splitlines()
    if staged_paths != [STATE_REL]:
        raise RuntimeError(f"claim commit scope is not isolated: {staged_paths}")
    staged = _git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        raise RuntimeError("claim state did not produce a staged change")

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    _git("config", "user.name", "bist-alpha-bot")
    _git("config", "user.email", "bot@users.noreply.github.com")
    _git("commit", "-m", f"report claim {label} run {run_id}")
    commit = _git("rev-parse", "HEAD").stdout.strip()
    if not commit:
        raise RuntimeError("claim commit SHA could not be read")
    return commit


def _align_after_failed_push(target: str, claim_commit: str) -> None:
    """Drop the unpushed claim commit and align the checkout to target.

    `claim_commit` is the current tip. Rebasing the empty range after that tip
    moves the checked-out branch without replaying the losing claim.
    """
    moved = _git("rebase", "--onto", target, claim_commit, check=False)
    if moved.returncode != 0:
        _git("rebase", "--abort", check=False)
        raise RuntimeError(f"claim checkout could not align to {target}: {_failure_detail(moved)}")

    head = _git("rev-parse", "HEAD").stdout.strip()
    expected = target
    if target.startswith("origin/"):
        expected = _git("rev-parse", target).stdout.strip()
    if not head or head != expected:
        raise RuntimeError(f"claim checkout alignment mismatch: head={head!r} target={expected!r}")


def _origin_state(branch: str) -> dict:
    shown = _git("show", f"origin/{branch}:{STATE_REL}", check=False)
    if shown.returncode != 0:
        raise RuntimeError(f"origin claim state could not be read: {_failure_detail(shown)}")
    try:
        state = json.loads(shown.stdout)
    except Exception as exc:
        raise RuntimeError(f"origin claim state is invalid JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise RuntimeError("origin claim state root is not an object")
    sent = state.get("sent", {})
    if not isinstance(sent, dict):
        raise RuntimeError("origin claim state sent field is not an object")
    return state


def _origin_blocks(branch: str, label: str, now: datetime) -> bool:
    state = _origin_state(branch)
    key = report_gate._marker_key(now, label)
    return report_gate._record_blocks(state.get("sent", {}).get(key), now)


def _durable_claim(label: str, now: datetime, branch: str) -> bool:
    """Persist a claim, distinguishing a competing owner from a real failure."""
    for attempt in range(2):
        base_commit = _git("rev-parse", "HEAD").stdout.strip()
        if not base_commit:
            raise RuntimeError("claim base SHA could not be read")

        # report_gate owns the slot key, malformed-record behavior, and TTL.
        if not report_gate.claim(label, now=now):
            return False
        claim_commit = _commit_claim(label)

        pushed = _git("push", "origin", branch, check=False)
        if pushed.returncode == 0:
            return True

        remote_ref = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
        fetched = _git("fetch", "origin", remote_ref, check=False)
        if fetched.returncode != 0:
            # Never leave an unpushed claim for a later `always()` state step
            # to publish without a producer run.
            _align_after_failed_push(base_commit, claim_commit)
            raise RuntimeError(
                "claim push failed and origin refresh failed: "
                f"push={_failure_detail(pushed)}; fetch={_failure_detail(fetched)}"
            )

        # Read and retry from the fetched source of truth, not from our losing
        # local commit. This also preserves unrelated origin state changes.
        _align_after_failed_push(f"origin/{branch}", claim_commit)
        if _origin_blocks(branch, label, now):
            return False
        if attempt == 1:
            raise RuntimeError(
                "claim push failed twice while the target slot remained unclaimed: "
                f"{_failure_detail(pushed)}"
            )

    raise RuntimeError("claim retry loop exhausted")


def claim(label: str) -> int:
    if not label:
        print("label required", file=sys.stderr)
        return 1

    os.chdir(REPO_ROOT)
    now = report_gate._now_istanbul()
    try:
        claimed = _durable_claim(label, now, _branch_name())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"durable claim failed: {exc}", file=sys.stderr)
        return 1

    if not claimed:
        _output("claimed", "false")
        print(f"claimed=false label={label} (another runner owns the origin slot)")
        return 0

    _output("claimed", "true")
    print(f"claimed=true label={label} (origin durable)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "claim":
        print("usage: report_claim.py claim LABEL", file=sys.stderr)
        return 2
    return claim(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
