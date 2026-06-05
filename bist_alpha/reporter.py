"""
EKSİK #2 & #4 — Sinyal raporu üretimi + hisse bazlı analiz.

Üretir:
- Top 10 liste (skor + sektör + SM sinyal + Deniz rejim)
- Her hisse için aksiyon: AL / SAT / BEKLE / FIRSAT
- Hisse bazlı detay analiz (on-demand)

Aksiyon mantığı (momentum + akıllı para sentezi):
  AL     : yeni pick, GÜÇLÜ BİRİKİM veya Birikim
  FIRSAT : pick değil ama GÜÇLÜ BİRİKİM + M252 eşik üstü (izleme listesi)
  BEKLE  : pick ama Nötr/zayıf sinyal
  SAT    : stop tetiklendi veya DAĞITIM + momentum kırıldı
"""
import pandas as pd
from datetime import datetime
from . import config
from .sectors import get_sector
from .signals import signal_for
from .strategy import select, score


def _action(in_portfolio, is_pick, sig, stopped):
    if stopped:
        return "SAT"
    if is_pick:
        if sig in ("GÜÇLÜ_BİRİKİM", "Birikim"):
            return "AL"
        return "BEKLE"
    # Pick değil ama güçlü sinyal -> fırsat (izleme)
    if sig == "GÜÇLÜ_BİRİKİM":
        return "FIRSAT"
    return "BEKLE"


def generate_report(data, signals, date=None, mode=None, deniz_bulletin=None,
                    held_positions=None, stopped_tickers=None):
    """
    Günlük sinyal raporu üretir.
    held_positions: şu an portföydeki hisseler (set) — opsiyonel
    stopped_tickers: bugün stop yiyenler (set) — opsiyonel
    Returns: dict (rapor)
    """
    mode = mode or config.MODE
    prices = data['prices']
    if date is None:
        date = prices.index[-1]
    held = held_positions or set()
    stopped = stopped_tickers or set()

    picks, sig_map, exceptions = select(data, signals, date, mode=mode)
    s, m252 = score(data, date)

    rows = []
    for rank, t in enumerate(picks, 1):
        sig = sig_map.get(t, "veri_yok")
        act = _action(t in held, True, sig, t in stopped)
        row = {
            "rank": rank, "ticker": t, "sector": get_sector(t),
            "skor": round(float(s[t]), 1) if t in s.index else None,
            "m252": round(float(m252[t]), 1) if t in m252.index else None,
            "sm_signal": sig, "action": act,
            "visa": t in exceptions,
        }
        if deniz_bulletin:
            from .deniz import sector_regime_flag
            row["deniz_regime"] = sector_regime_flag(deniz_bulletin, get_sector(t))
        # Yan kaynak overlay (OMEGA istihbaratı — bayrak/etiket)
        from . import sidesource
        ss = sidesource.annotate_ticker(t, get_sector(t))
        if ss:
            row["yan_kaynak"] = ss
        rows.append(row)

    # FIRSAT listesi: pick olmayan ama GÜÇLÜ BİRİKİM + yüksek momentum
    firsatlar = []
    if s is not None:
        top_scored = s.sort_values(ascending=False).head(30).index
        for t in top_scored:
            if t in picks:
                continue
            sig = signal_for(signals, date, t)
            if sig == "GÜÇLÜ_BİRİKİM" and t in m252.index and m252[t] > config.DUAL_THRESHOLD:
                firsatlar.append({"ticker": t, "sector": get_sector(t),
                                  "m252": round(float(m252[t]), 1), "sm_signal": sig})
            if len(firsatlar) >= 5:
                break

    return {
        "date": str(date.date()) if hasattr(date, "date") else str(date),
        "mode": mode,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "top10": rows,
        "firsatlar": firsatlar,
        "market_score_deniz": deniz_bulletin.get("market_score") if deniz_bulletin else None,
    }


def format_text(report):
    """Raporu okunabilir metin (e-posta/Telegram için)."""
    L = []
    L.append(f"📊 BIST ALPHA v1.2 — {report['date']} (mod {report['mode']})")
    L.append(f"Üretim: {report['generated_at']}")
    if report.get("market_score_deniz") is not None:
        L.append(f"Deniz market puanı: {report['market_score_deniz']}")
    L.append("")
    L.append("TOP 10:")
    for r in report["top10"]:
        v = " 🎫" if r.get("visa") else ""
        dz = f" [{r['deniz_regime']}]" if r.get("deniz_regime") else ""
        emoji = {"AL": "🟢", "SAT": "🔴", "BEKLE": "🟡", "FIRSAT": "⭐"}.get(r["action"], "")
        L.append(f" {r['rank']:2d}. {emoji} {r['ticker']:7s} {r['action']:6s} "
                 f"M252:%{r['m252']}  {r['sm_signal']}{v}{dz}")
        # Yan kaynak bayrakları (varsa)
        ss = r.get("yan_kaynak")
        if ss:
            parts = []
            if "deniz_skor" in ss: parts.append(f"Deniz:{ss['deniz_skor']:.0f}")
            if "yabancı" in ss: parts.append(ss["yabancı"])
            if "bilanço" in ss: parts.append(f"bilanço:{ss['bilanço']}")
            if "hacim" in ss: parts.append(ss["hacim"])
            if "fx_risk" in ss: parts.append("FX-risk")
            if "sezonsal" in ss: parts.append(ss["sezonsal"])
            if "sektör_uyarı" in ss: parts.append(f"⚠{ss['sektör_uyarı']}")
            if parts:
                L.append(f"        └─ {' | '.join(parts)}")
    if report["firsatlar"]:
        L.append("")
        L.append("⭐ FIRSAT (izleme — pick değil ama güçlü birikim):")
        for f in report["firsatlar"]:
            L.append(f"   {f['ticker']:7s} {f['sector']:7s} M252:%{f['m252']}")
    L.append("")
    L.append("⚠️ Tek rejim (boğa) verisinde kalibre. Yatırım tavsiyesi değildir.")
    return "\n".join(L)


def analyze_stock(data, signals, ticker, date=None):
    """
    EKSİK #4 — Tek hisse derin analiz (on-demand).
    """
    prices = data['prices']
    if ticker not in prices.columns:
        return {"error": f"{ticker} veride yok"}
    if date is None:
        date = prices.index[-1]
    idx = prices.index.searchsorted(date)

    p_now = prices.iloc[idx][ticker]
    def chg(n):
        if idx - n < 0:
            return None
        p0 = prices.iloc[idx - n][ticker]
        return round((p_now / p0 - 1) * 100, 1) if pd.notna(p0) and p0 > 0 else None

    sig = signal_for(signals, date, ticker)
    cpr = signals['cpr_10'].loc[date, ticker] if date in signals['cpr_10'].index and ticker in signals['cpr_10'].columns else None
    acc = signals['acc_ratio'].loc[date, ticker] if date in signals['acc_ratio'].index and ticker in signals['acc_ratio'].columns else None
    uw = signals['upper_wick'].loc[date, ticker] if date in signals['upper_wick'].index and ticker in signals['upper_wick'].columns else None

    s, m252 = score(data, date)
    in_universe = ticker in s.index if s is not None else False

    # Destek/direnç seviyeleri
    from .levels import pivot_levels, position_in_range, close_window_liquidity_ok
    levels = pivot_levels(data, ticker, date)
    pos_in_range = position_in_range(data, ticker, date)
    # Kapanış penceresi likidite (TESPİT 2) — örnek 5mn TL pozisyon için
    liq = close_window_liquidity_ok(data, ticker, position_tl=5_000_000, date=date)

    return {
        "ticker": ticker, "date": str(date.date()) if hasattr(date, "date") else str(date),
        "sector": get_sector(ticker),
        "fiyat": round(float(p_now), 2) if pd.notna(p_now) else None,
        "getiri": {"5g": chg(5), "30g": chg(30), "252g": chg(252)},
        "skor": round(float(s[ticker]), 1) if in_universe else None,
        "evrende_mi": in_universe,
        "sm_signal": sig,
        "cpr": round(float(cpr), 2) if cpr is not None and pd.notna(cpr) else None,
        "acc_ratio": round(float(acc), 2) if acc is not None and pd.notna(acc) else None,
        "upper_wick": round(float(uw), 2) if uw is not None and pd.notna(uw) else None,
        "destek_direnc": levels,
        "banttaki_yeri": pos_in_range,
        "kapanis_likidite": liq,
    }
