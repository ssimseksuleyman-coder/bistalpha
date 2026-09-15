#!/usr/bin/env python3
"""Durably reserve a report slot before a producer starts.

The local report gate state is not enough for two GitHub runners.  The claim
must reach origin before either producer is allowed to run its daemon.
"""
from __future__ import annotations

import os
import subprocess
import sys
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


def claim(label: str) -> int:
    if not label:
        print("label required", file=sys.stderr)
        return 1

    os.chdir(REPO_ROOT)
    # report_gate owns the slot key, malformed-record behavior, and TTL.
    if not report_gate.claim(label):
        _output("claimed", "false")
        print(f"claimed=false label={label} (another runner owns the slot)")
        return 0

    try:
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
        branch = os.environ.get("GITHUB_REF_NAME")
        if not branch:
            branch = _git("branch", "--show-current").stdout.strip() or "main"
        _git("push", "origin", branch)
    except Exception as exc:
        print(f"durable claim failed: {exc}", file=sys.stderr)
        return 1

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
