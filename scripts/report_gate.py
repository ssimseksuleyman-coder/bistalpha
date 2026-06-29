#!/usr/bin/env python3
"""GitHub Actions report gate.

GitHub scheduled runs can be late or skipped. This gate lets Actions retry in
short windows, but sends only one successful report per target slot.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SLOTS = [
    ("acilis", time(9, 45)),
    ("gunici", time(14, 30)),
    ("kapanis", time(18, 40)),
]
STATE_PATH = Path("docs/state/report_runs.json")
WINDOW_MINUTES = int(os.environ.get("REPORT_WINDOW_MINUTES", "50"))


def _now_istanbul() -> datetime:
    if ZoneInfo is None:
        return datetime.now()
    return datetime.now(ZoneInfo("Europe/Istanbul"))


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sent": {}}


def _write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _marker_key(now: datetime, label: str) -> str:
    return f"{now:%Y-%m-%d}:{label}"


def _github_output(**values: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def due_slot(now: datetime | None = None) -> tuple[bool, str, str]:
    now = now or _now_istanbul()
    event = os.environ.get("GITHUB_EVENT_NAME", "")

    if event in {"workflow_dispatch", "push"}:
        label = "manuel" if event == "workflow_dispatch" else "push"
        return True, label, event

    if now.weekday() >= 5:
        return False, "", "weekend"

    sent = _load_state().get("sent", {})
    for label, slot_time in SLOTS:
        target = datetime.combine(now.date(), slot_time, tzinfo=now.tzinfo)
        if target <= now <= target + timedelta(minutes=WINDOW_MINUTES):
            key = _marker_key(now, label)
            if key in sent:
                return False, label, f"already_sent:{key}"
            return True, label, f"due:{key}"
    return False, "", "not_due"


def mark(label: str, now: datetime | None = None) -> None:
    if not label:
        raise SystemExit("label required")
    now = now or _now_istanbul()
    state = _load_state()
    state.setdefault("sent", {})[_marker_key(now, label)] = {
        "sent_at": now.isoformat(timespec="seconds"),
    }
    _write_state(state)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        run, label, reason = due_slot()
        _github_output(run=str(run).lower(), label=label, reason=reason)
        print(f"run={str(run).lower()} label={label} reason={reason}")
        return 0
    if cmd == "mark":
        label = argv[2] if len(argv) > 2 else ""
        mark(label)
        print(f"marked {label}")
        return 0
    raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
