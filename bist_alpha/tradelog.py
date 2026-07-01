"""
SQLite islem gunlugu — Surface Pro 5 kalici hafiza.

GitHub Actions runner her calismada sifirlanir (ephemeral); Surface Pro 5
diskte kalici DB tutabilir. Bu modul her shadow adiminda gerceklesen
islemleri (BUY/SELL/REENTRY) tek bir SQLite dosyasina ekler — JSON
portfolio state'lerinin aksine, TUM gecmis sorgulanabilir kalir
(JSON'lar sadece son N kaydi tutar, .HISTORY_CAP/.TRADES_CAP ile sinirli).

Kullanim:
    from bist_alpha import tradelog
    tradelog.log_trades("F", "2026-06-30", trades_list)
    tradelog.best_signal()
    tradelog.worst_stop()
"""
import os
import sqlite3
from . import config

DB_PATH = os.path.join(getattr(config, "STATE_DIR", "portfolios"), "tradelog.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    account TEXT NOT NULL,
    type TEXT NOT NULL,
    ticker TEXT NOT NULL,
    price REAL,
    pnl_pct REAL,
    signal TEXT,
    reason TEXT,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
"""


def _connect(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def log_trades(account, date, trades, db_path=None):
    """
    Bir hesabin bir gunluk islem listesini DB'ye ekler.
    trades: [{"type", "ticker", "price", "pnl_pct"?, "signal"?, "reason"?}, ...]
    """
    if not trades:
        return 0
    conn = _connect(db_path)
    try:
        rows = [
            (date, account, t.get("type"), t.get("ticker"), t.get("price"),
             t.get("pnl_pct"), t.get("signal"), t.get("reason"))
            for t in trades
        ]
        conn.executemany(
            "INSERT INTO trades (date, account, type, ticker, price, pnl_pct, signal, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def best_signal(account=None, min_trades=3, db_path=None):
    """Hangi sinyal etiketi (signal kolonu) en yuksek ortalama pnl_pct uretti."""
    conn = _connect(db_path)
    try:
        q = ("SELECT signal, COUNT(*) n, AVG(pnl_pct) avg_pnl "
             "FROM trades WHERE type='SELL' AND signal IS NOT NULL AND pnl_pct IS NOT NULL")
        params = []
        if account:
            q += " AND account = ?"
            params.append(account)
        q += " GROUP BY signal HAVING COUNT(*) >= ? ORDER BY avg_pnl DESC"
        params.append(min_trades)
        rows = conn.execute(q, params).fetchall()
        return [{"signal": r[0], "n": r[1], "avg_pnl_pct": round(r[2], 2)} for r in rows]
    finally:
        conn.close()


def worst_stop(account=None, limit=10, db_path=None):
    """En kotu (en negatif pnl_pct) stop islemleri."""
    conn = _connect(db_path)
    try:
        q = ("SELECT date, account, ticker, price, pnl_pct, reason FROM trades "
             "WHERE type='SELL' AND reason='stop' AND pnl_pct IS NOT NULL")
        params = []
        if account:
            q += " AND account = ?"
            params.append(account)
        q += " ORDER BY pnl_pct ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [{"date": r[0], "account": r[1], "ticker": r[2], "price": r[3],
                 "pnl_pct": r[4], "reason": r[5]} for r in rows]
    finally:
        conn.close()


def account_stats(account, db_path=None):
    """Bir hesabin toplam islem sayisi, win-rate, ortalama pnl."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), AVG(pnl_pct), "
            "SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) "
            "FROM trades WHERE account = ? AND type='SELL' AND pnl_pct IS NOT NULL",
            (account,)).fetchone()
        n, avg_pnl, wins = row
        return {
            "n_closed_trades": n or 0,
            "avg_pnl_pct": round(avg_pnl, 2) if avg_pnl is not None else None,
            "win_rate_pct": round(wins / n * 100, 1) if n else None,
        }
    finally:
        conn.close()
