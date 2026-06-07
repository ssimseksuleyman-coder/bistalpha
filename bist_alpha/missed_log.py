"""
Missed opportunity ledger facade.

Radar candidate generation lives in radar.py; this module is the explicit
"missed log" entry point so daemon/dashboard code can call the learning ledger
without mixing it with watchlist construction.
"""
from __future__ import annotations

from .radar import update_missed_ledger


def update(data, watchlists, report, date=None, max_snapshots=90):
    return update_missed_ledger(
        data,
        watchlists,
        report,
        date=date,
        max_snapshots=max_snapshots,
    )
