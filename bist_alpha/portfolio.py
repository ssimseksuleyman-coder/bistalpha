"""
İŞLEV EKSİĞİ — Pozisyon durumu kalıcılığı (canlı/shadow için kritik).

Canlı sistem pozisyonları çalışmalar arası HATIRLAMALI. Bu olmadan:
  - 'SAT' sinyali çalışmaz (neyin tutulduğunu + stop'u bilemez)
  - Give-back / güncel P&L hesaplanamaz
  - Shadow mode (A/B/F kalıcı portföyleri) imkansız

Bu modül her hesap (A/B/F) için holdings'i JSON'da saklar/yükler,
stop durumunu hesaplar, SAT sinyali üretir.
"""
import os
import json
from datetime import datetime
from . import config


def _path(account, state_dir):
    return os.path.join(state_dir, f"portfolio_{account}.json")


def load(account, state_dir="portfolios"):
    """Hesabın mevcut pozisyonlarını yükler. Yoksa boş döner."""
    p = _path(account, state_dir)
    if not os.path.exists(p):
        return {"account": account, "cash": 1.0, "positions": {}, "history": []}
    with open(p) as f:
        return json.load(f)


def save(state, state_dir="portfolios"):
    """
    Portföy durumunu ATOMİK kaydeder (TESPİT 3).
    SQLite WAL KULLANMIYORUZ — kasıtlı: WAL sidecar dosyaları (-wal/-shm) ve
    ephemeral GitHub Actions runner'da git-commit kalıcılığı çatışır. JSON +
    atomik yazım (geçici dosya → os.replace) hem git-dostu hem yarım-yazıma güvenli.
    Runner görev ortasında ölse bile dosya ya eski ya yeni — asla bozuk.
    """
    os.makedirs(state_dir, exist_ok=True)
    final = _path(state["account"], state_dir)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, final)   # atomik (POSIX rename)


def stop_level(pos):
    """Bir pozisyonun güncel stop seviyesi (trailing + abs)."""
    gain = pos['peak'] / pos['entry'] - 1
    trail = (config.TRAIL_TIGHT if gain >= 0.30
             else config.TRAIL_MID if gain >= 0.15
             else config.TRAIL_WIDE)
    return max(pos['entry'] * (1 - config.ABS_STOP_PCT), pos['peak'] * (1 - trail))


def check_stops(state, prices_today):
    """
    Güncel fiyatlarla stop kontrolü. SAT edilmesi gerekenleri döner.
    prices_today: {ticker: price}
    Returns: [{'ticker', 'price', 'reason', 'giveback'}]
    """
    sells = []
    for tic, pos in state["positions"].items():
        pt = prices_today.get(tic)
        if pt is None:
            continue
        if pt > pos['peak']:
            pos['peak'] = pt          # peak güncelle (kalıcı)
        st = stop_level(pos)
        if pt < st:
            giveback = (pos['peak'] - pt) / pos['peak'] * 100
            sells.append({"ticker": tic, "price": round(pt, 2),
                          "reason": "stop", "giveback": round(giveback, 2)})
    return sells


def rebalance(state, picks_with_weights, prices_today, slippage=0.0):
    """
    Portföyü yeni pick'lere göre günceller (sat + weighted al).
    picks_with_weights: {ticker: lot_weight}
    prices_today: {ticker: price}
    Pozisyon state'i KALICI olarak günceller.
    """
    friction = config.COMMISSION / 2 + slippage
    # Toplam değer
    total = state["cash"]
    for tic, pos in state["positions"].items():
        p = prices_today.get(tic, pos['entry'])
        total += pos['shares'] * p
    # Tümünü sat
    for tic, pos in list(state["positions"].items()):
        p = prices_today.get(tic, pos['entry'])
        state["cash"] += pos['shares'] * p * (1 - friction)
    state["positions"] = {}
    # Weighted al
    tw = sum(picks_with_weights.values())
    if tw > 0:
        for tic, w in picks_with_weights.items():
            ep = prices_today.get(tic)
            if ep and ep > 0:
                alloc = total * (w / tw) * (1 - friction)
                state["positions"][tic] = {"entry": ep, "peak": ep, "shares": alloc / ep}
                state["cash"] -= alloc
    state["history"].append({"date": datetime.now().strftime("%Y-%m-%d"),
                             "total": round(total, 4), "n_pos": len(state["positions"])})
    return state


def current_value(state, prices_today):
    """Portföyün güncel toplam değeri."""
    total = state["cash"]
    for tic, pos in state["positions"].items():
        p = prices_today.get(tic, pos['entry'])
        total += pos['shares'] * p
    return total


def held_tickers(state):
    return set(state["positions"].keys())
