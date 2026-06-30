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
import math
from datetime import datetime
from . import config


def _sanitize_json(obj):
    """NaN/Infinity içeren float'ları None'a çevirir — JSON spec'ine aykırı değerler."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


def _path(account, state_dir):
    return os.path.join(state_dir, f"portfolio_{account}.json")


def load(account, state_dir="portfolios"):
    """Hesabın mevcut pozisyonlarını yükler. Bozuksa yedekler ve sıfırlar."""
    p = _path(account, state_dir)
    default = {"account": account, "cash": 1.0, "positions": {}, "history": []}
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError("state dict değil")
        if not isinstance(state.get("positions"), dict):
            raise ValueError("positions eksik veya dict değil")
        return state
    except Exception as e:
        import datetime as _dt
        bak = p + f".bozuk_{_dt.datetime.now():%Y%m%d_%H%M%S}.bak"
        try:
            os.rename(p, bak)
        except OSError:
            pass
        print(f"[portfolio] {account} bozuk JSON yedeklendi ({e}) → sıfırlandı: {bak}")
        return default


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
        json.dump(_sanitize_json(state), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, final)   # atomik (POSIX rename)


def stop_level(pos):
    """Bir pozisyonun güncel stop seviyesi (trailing + abs)."""
    entry = pos['entry']
    peak = pos.get('peak') or entry   # eski/bozuk JSON'da peak yoksa entry'ye düş
    gain = peak / entry - 1
    trail = (config.TRAIL_TIGHT if gain >= 0.30
             else config.TRAIL_MID if gain >= 0.15
             else config.TRAIL_WIDE)
    return max(entry * (1 - config.ABS_STOP_PCT), peak * (1 - trail))


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


def _trade_date(trade_date=None):
    return trade_date or datetime.now().strftime("%Y-%m-%d")


def close_positions(state, sells, prices_today, slippage=0.0, trade_date=None):
    """Stop sinyallerini uygular: pozisyonu kapatır, nakde döner ve işlem kaydı tutar."""
    friction = config.COMMISSION / 2 + slippage
    trades = []
    for item in sells:
        tic = item.get("ticker")
        pos = state.get("positions", {}).get(tic)
        if not pos:
            continue
        price = prices_today.get(tic) or item.get("price") or pos["entry"]
        proceeds = pos["shares"] * price * (1 - friction)
        state["cash"] += proceeds
        pnl_pct = (price / pos["entry"] - 1) * 100
        trades.append({
            "type": "SELL",
            "ticker": tic,
            "price": round(price, 2),
            "shares": round(pos["shares"], 6),
            "reason": item.get("reason", "stop"),
            "pnl_pct": round(pnl_pct, 2),
        })
        del state["positions"][tic]
    if trades:
        state.setdefault("history", []).append({
            "date": _trade_date(trade_date),
            "event": "stop",
            "total": round(current_value(state, prices_today), 4),
            "n_pos": len(state.get("positions", {})),
            "trades": trades,
        })
    return trades


def rebalance(state, picks_with_weights, prices_today, slippage=0.0, trade_date=None, reason="rebalance"):
    """
    Portföyü yeni pick'lere göre günceller (sat + weighted al).
    picks_with_weights: {ticker: lot_weight}
    prices_today: {ticker: price}
    Pozisyon state'i KALICI olarak günceller.
    """
    friction = config.COMMISSION / 2 + slippage
    trades = []
    # Toplam değer
    total = state["cash"]
    for tic, pos in state["positions"].items():
        p = prices_today.get(tic, pos['entry'])
        total += pos['shares'] * p
    # Tümünü sat
    for tic, pos in list(state["positions"].items()):
        p = prices_today.get(tic, pos['entry'])
        state["cash"] += pos['shares'] * p * (1 - friction)
        trades.append({
            "type": "SELL",
            "ticker": tic,
            "price": round(p, 2),
            "shares": round(pos["shares"], 6),
            "reason": reason,
            "pnl_pct": round((p / pos["entry"] - 1) * 100, 2),
        })
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
                trades.append({
                    "type": "BUY",
                    "ticker": tic,
                    "price": round(ep, 2),
                    "shares": round(alloc / ep, 6),
                    "weight": round(w, 4),
                    "reason": reason,
                })
    state["history"].append({"date": _trade_date(trade_date),
                             "event": reason,
                             "total": round(current_value(state, prices_today), 4),
                             "n_pos": len(state["positions"]),
                             "trades": trades})
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
