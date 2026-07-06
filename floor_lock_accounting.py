"""
floor_lock_accounting.py — TABAN-FARKINDA cikis muhasebesi (F'e DOKUNMAZ).

BIST +-%10 gunluk limit: stop tetiklendigi gun hisse TABAN'daysa (limit-down),
kapanista SATAMAZSIN (alici yok, kilit). Gercek cikis, kilit acilinca (unlock) olur.
Backtest + canli-paper muhasebesi "kapanista sat" varsayar -> IYIMSER.

DOGRULANDI (2026-07-05): bagimsiz olcum (TERA/OZATD/ANELE) birebir yeniden uretildi;
canli-yol (LivePosition) look-ahead-siz. Bkz. taban_readiness.py (izole defter).

*** KRITIK: IKI AYRI KOD YOLU ***
  backtest_exit(): tum seri elde -> unlock gununu ILERI bakarak bulur (backtest'te
                   look-ahead DEGIL, cunku gecmisi olcuyoruz, karar degil muhasebe)
  LivePosition:    canli -> unlock BILINMEZ. "kilitli" isaretler, her gun "hala
                   taban mi" kontrol eder, unlock olunca kapatir. ASLA ileri bakmaz.
"""
from __future__ import annotations

FLOOR_THRESH = -9.5      # gunluk % getiri bu altindaysa "taban" (kilit)
CEIL_THRESH = 9.5        # tavan (alis tarafi, simetrik)
MAX_LOCK_DAYS = 10       # guvenlik: bu kadar gun sonra zorla cik


def is_floor_day(prev_close, day_close, thresh=FLOOR_THRESH):
    """O gun taban mi (close-to-close getiri <= thresh). prev_close=onceki gun kapanis."""
    if prev_close is None or prev_close <= 0 or day_close is None:
        return False
    ret_pct = (day_close / prev_close - 1) * 100
    return ret_pct <= thresh + 1e-9


def backtest_exit(prices_series, stop_idx, thresh=FLOOR_THRESH, use_low=False, lows_series=None):
    """Backtest: stop_idx gununde stop tetiklendi -> gercek cikis fiyati.
    Doner: {exit_price, exit_idx, lock_days, was_locked}"""
    n = len(prices_series)
    if stop_idx <= 0 or stop_idx >= n:
        return {"exit_price": prices_series.iloc[stop_idx] if 0 <= stop_idx < n else None,
                "exit_idx": stop_idx, "lock_days": 0, "was_locked": False}
    prev_close = prices_series.iloc[stop_idx - 1]
    stop_close = prices_series.iloc[stop_idx]
    if not is_floor_day(prev_close, stop_close, thresh):
        return {"exit_price": stop_close, "exit_idx": stop_idx, "lock_days": 0, "was_locked": False}
    cur = stop_idx
    lock_days = 0
    while cur + 1 < n and lock_days < MAX_LOCK_DAYS:
        nxt = cur + 1
        if is_floor_day(prices_series.iloc[cur], prices_series.iloc[nxt], thresh):
            cur = nxt; lock_days += 1
        else:
            cur = nxt; lock_days += 1; break
    exit_price = (lows_series.iloc[cur] if use_low and lows_series is not None
                  else prices_series.iloc[cur])
    return {"exit_price": exit_price, "exit_idx": cur, "lock_days": lock_days, "was_locked": True}


class LivePosition:
    """Canli pozisyon: taban-kilidini gercek-zamanli takip eder. Look-ahead YOK."""
    def __init__(self, ticker, shares):
        self.ticker = ticker; self.shares = shares
        self.status = "open"; self.stop_signal_date = None; self.lock_days = 0

    def on_new_day(self, prev_close, day_close, day_low, stop_triggered, thresh=FLOOR_THRESH):
        if self.status == "exited":
            return ("already_exited", None)
        today_is_floor = is_floor_day(prev_close, day_close, thresh)
        if self.status == "open" and stop_triggered:
            if today_is_floor:
                self.status = "stop_pending_lock"; self.stop_signal_date = "today"; self.lock_days = 1
                return ("locked_wait", None)
            self.status = "exited"; return ("exit", day_close)
        if self.status == "stop_pending_lock":
            if today_is_floor and self.lock_days < MAX_LOCK_DAYS:
                self.lock_days += 1; return ("locked_wait", None)
            self.status = "exited"; return ("exit", day_close)
        return ("hold", None)


def portfolio_drag(stops):
    """stops: [{weight, recorded_exit, real_exit_close, real_exit_low}].
    Kayitli vs gercek cikis portfoy suruklemesi (agirlikli, birinci-derece).
    Doner: {drag_close_pct, drag_low_pct}. Toparlayan poz negatif drag (net)."""
    drag_c = 0.0; drag_l = 0.0
    for s in stops:
        rec = s["recorded_exit"]
        if rec <= 0:
            continue
        drag_c += s["weight"] / 100 * (rec - s["real_exit_close"]) / rec * 100
        drag_l += s["weight"] / 100 * (rec - s["real_exit_low"]) / rec * 100
    return {"drag_close_pct": round(drag_c, 2), "drag_low_pct": round(drag_l, 2)}
