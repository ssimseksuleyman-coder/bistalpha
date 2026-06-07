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
from . import portfolio as pf
from .levels import pivot_levels
from .sectors import get_sector
from .signals import signal_for
from .strategy import last_n_return, select, score


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


def _round_price(value):
    if value is None or pd.isna(value):
        return None
    return round(float(value), 2)


def _held_position(held_positions, ticker):
    if isinstance(held_positions, dict):
        return held_positions.get(ticker)
    return None


def _price_plan(data, ticker, date, held_positions=None):
    prices = data['prices']
    current = prices.loc[date, ticker] if ticker in prices.columns and date in prices.index else None
    if current is None or pd.isna(current) or current <= 0:
        return {
            "mevcut_fiyat": None,
            "giris_fiyati": None,
            "hedef_1": None,
            "hedef_2": None,
            "stop": None,
            "risk_pct": None,
            "potansiyel_pct": None,
        }

    pos = _held_position(held_positions, ticker)
    entry = float(pos.get("entry", current)) if pos else float(current)
    stop = pf.stop_level(pos) if pos else entry * (1 - config.ABS_STOP_PCT)

    levels = pivot_levels(data, ticker, date) or {}
    r1 = levels.get("r1")
    r2 = levels.get("r2")
    current_f = float(current)
    target1 = r1 if r1 and r1 > current_f else r2
    if not target1 or target1 <= current_f:
        target1 = current_f * 1.08
    target2 = r2 if r2 and r2 > target1 else current_f * 1.15

    return {
        "mevcut_fiyat": _round_price(current_f),
        "giris_fiyati": _round_price(entry),
        "hedef_1": _round_price(target1),
        "hedef_2": _round_price(target2),
        "stop": _round_price(stop),
        "risk_pct": round((entry - stop) / entry * 100, 1) if stop and stop > 0 and entry > 0 else None,
        "potansiyel_pct": round((target1 / current_f - 1) * 100, 1) if target1 and current_f > 0 else None,
    }


def _momentum_snapshot(data, ticker, date):
    m5 = last_n_return(data, date, ticker, 5)
    m21 = last_n_return(data, date, ticker, 21)
    return {
        "m5": round(float(m5), 1) if m5 is not None else None,
        "m21": round(float(m21), 1) if m21 is not None else None,
    }


def _watch_signal(item):
    return item.get("display_signal") or item.get("sm_signal") or "-"


def _display_signal(sig):
    if sig in ("Üst_fitil_dağıtım", "Üst_fitil_UYARI"):
        return "Üst_fitil_UYARI"
    return sig


def _watch_tags(item, max_tags=3):
    tags = item.get("tags") or []
    labels = []
    seen = set()
    for tag in tags:
        if isinstance(tag, dict):
            label = tag.get("label")
        else:
            label = str(tag)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return " | ".join(labels[:max_tags])


def _quarantine_text(item):
    status = item.get("quarantine_status")
    days = item.get("watch_days")
    if not status or days is None:
        return ""
    if status == "karantina":
        return f" | karantina:{days}/3"
    return f" | teyit:{days}g"


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
            "display_signal": _display_signal(sig),
            "visa": t in exceptions,
        }
        row.update(_momentum_snapshot(data, t, date))
        row.update(_price_plan(data, t, date, held_positions=held_positions))
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
        top_scored = (s.rename("score").to_frame()
                      .assign(ticker=lambda df: df.index.astype(str))
                      .sort_values(["score", "ticker"],
                                   ascending=[False, True], kind="mergesort")
                      .head(30).index)
        for t in top_scored:
            if t in picks:
                continue
            sig = signal_for(signals, date, t)
            if sig == "GÜÇLÜ_BİRİKİM" and t in m252.index and m252[t] > config.DUAL_THRESHOLD:
                firsatlar.append({"ticker": t, "sector": get_sector(t),
                                  "m252": round(float(m252[t]), 1), "sm_signal": sig,
                                  **_momentum_snapshot(data, t, date)})
            if len(firsatlar) >= 5:
                break

    return {
        "date": str(date.date()) if hasattr(date, "date") else str(date),
        "mode": mode,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": data.get("_source"),
        "source_pool_count": data.get("_source_pool_count"),
        "source_pool_method": data.get("_source_pool_method"),
        "source_pool_fallback": data.get("_source_pool_fallback"),
        "last_data_date": str(prices.index[-1].date()) if hasattr(prices.index[-1], "date") else str(prices.index[-1]),
        "price_count": int(prices.shape[1]),
        "dynamic_universe_count": len(data.get("_dynamic_universe", [])) if data.get("_dynamic_universe") else None,
        "dynamic_universe_method": data.get("_dynamic_universe_method"),
        "top10": rows,
        "firsatlar": firsatlar,
        "market_score_deniz": deniz_bulletin.get("market_score") if deniz_bulletin else None,
    }


def format_text(report):
    """Raporu okunabilir metin (e-posta/Telegram için)."""
    L = []
    L.append(f"📊 BIST ALPHA v1.2 — {report['date']} (mod {report['mode']})")
    L.append(f"Üretim: {report['generated_at']}")
    if report.get("source"):
        pool = report.get("source_pool_count")
        pool_method = report.get("source_pool_method")
        pool_note = f" | BIST havuzu: {pool}" if pool else ""
        if pool_method:
            pool_note += f" ({pool_method})"
        L.append(f"Kaynak: {report['source']}{pool_note} | canlı veri: {report.get('price_count')} | evren: {report.get('dynamic_universe_count')} | son veri: {report.get('last_data_date')}")
    if report.get("market_score_deniz") is not None:
        L.append(f"Deniz market puanı: {report['market_score_deniz']}")
    L.append("")
    L.append("TOP 10:")
    for r in report["top10"]:
        v = " 🎫" if r.get("visa") else ""
        dz = f" [{r['deniz_regime']}]" if r.get("deniz_regime") else ""
        emoji = {"AL": "🟢", "SAT": "🔴", "BEKLE": "🟡", "FIRSAT": "⭐"}.get(r["action"], "")
        L.append(f" {r['rank']:2d}. {emoji} {r['ticker']:7s} {r['action']:6s} "
                 f"M252:%{r['m252']}  {r.get('display_signal') or r['sm_signal']}{v}{dz}")
        L.append(f"        1H:%{r.get('m5')} | 1A:%{r.get('m21')} | 1Y:%{r.get('m252')}")
        L.append(f"        Fiyat:{r.get('mevcut_fiyat')} | Giriş:{r.get('giris_fiyati')} | "
                 f"Hedef:{r.get('hedef_1')}/{r.get('hedef_2')} | Stop:{r.get('stop')} | "
                 f"Risk:%{r.get('risk_pct')} | Pot:%{r.get('potansiyel_pct')}")
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
            L.append(f"   {f['ticker']:7s} {f['sector']:7s} 1H:%{f.get('m5')} 1A:%{f.get('m21')} M252:%{f['m252']}")
    watch = report.get("watchlists") or {}
    if watch and not watch.get("error"):
        if watch.get("transformation"):
            L.append("")
            L.append("DONUSUM RADARI (Top 10 degil, guc yeni geciyor):")
            for w in watch["transformation"][:5]:
                tags = _watch_tags(w)
                tag_txt = f" | {tags}" if tags else ""
                L.append(f"   {w['ticker']:7s} 1Y-rank:{w['rank_1y']} -> 1A:{w['rank_1a']} / 1H:{w['rank_1h']} "
                         f"1A:%{w['m21']} 1H:%{w['m5']} {_watch_signal(w)}{_quarantine_text(w)}{tag_txt}")
        if watch.get("quiet_accumulation"):
            L.append("")
            L.append("SESSIZ BIRIKIM (islem degil, izleme):")
            for w in watch["quiet_accumulation"][:5]:
                tags = _watch_tags(w)
                tag_txt = f" | {tags}" if tags else ""
                L.append(f"   {w['ticker']:7s} hacim:{w.get('volume_ratio')}x 1A:%{w['m21']} 1H:%{w['m5']} {_watch_signal(w)}{_quarantine_text(w)}{tag_txt}")
        if watch.get("peak_risks"):
            L.append("")
            L.append("TEPE RISKI / NEDEN DISARIDA (islem degil, aciklama):")
            for w in watch["peak_risks"][:5]:
                tags = _watch_tags(w, max_tags=4)
                L.append(f"   {w['ticker']:7s} 1Y:%{w['m252']} 1A:%{w['m21']} 1H:%{w['m5']} "
                         f"{_watch_signal(w)} | {tags}")
    if report.get("shadow_accounts"):
        L.append("")
        L.append("📈 SHADOW PERFORMANS:")
        for acc in ["A", "B", "F", "O"]:
            info = report["shadow_accounts"].get(acc, {})
            if info.get("error"):
                L.append(f"   {acc}: hata — {info['error']}")
                continue
            event = info.get("last_event") or {}
            event_txt = event.get("event", "islem yok")
            trade_count = len(event.get("trades") or [])
            L.append(f"   {acc}: değer {info.get('value')} | getiri %{info.get('return_pct')} | "
                     f"pozisyon {info.get('n_positions')} | son: {event_txt} ({trade_count} işlem)")
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
