"""
taban_readiness.py â€” IZOLE gercek-para-hazirlik defteri. CANLI STATE'E DOKUNMAZ.

Ne yapar: canli F stop'larini taban-lock-farkinda duzeltir (floor_lock_accounting),
taban-risk metrikleri + OLCULEBILIR gecis-kriteri uretir, reports/taban_honest_ledger.json'a
EKLER (dashboard.json'a DEGIL -> izole, risksiz). Sadece portfolio_F.json'i OKUR + yfinance.

Amac: paper penceresinde iki soruyu SEZGIYLE degil KANITLA yanitlamak:
  1. "Kagit sayi ne kadar iyimserdi?" -> booked vs taban-honest (gap)
  2. "Gercek-paraya hazir miyiz?" -> birikimli, cok-pencere kriter (asagida)

GECIS KRITERI (onden sabit, sezgi degil):
  C1 Yeterli kanit : >=5 bagimsiz pencere (tek/uc pencere yetmez)
  C2 Kumulatif+drag: (a) KUMULATIF taban-honest low > 0 (bireysel dusus-penceresine izin;
                     "her pencere pozitif" momentum'u paper'da hapseder) + (b) pencere-basi
                     taban-drag <= 8pp (taban-lock SURPRIZINI yakalar, piyasa-dususunu degil)
  C3 Modellenmis kuyruk: max ardisik-kilit <= 5 gun (olctugumuz kuyrugun icinde, surpriz yok)
  C4 Karakterize   : taban_ratio pencereler-arasi tutarli (asiri spike raporlanir)
  HAZIR ancak C1 & C2 & C3 & C4. Aksi: "N pencere daha gerek".

Kullanim: python taban_readiness.py   (her paper-pencere/rebalans sonrasi calistir)
"""
import json, os, sys, warnings; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd
import floor_lock_accounting as FLA

REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "taban_honest_ledger.json")

MIN_READY_WINDOWS = 5
MIN_LOW_RETURN_PCT = 0.0        # C2a: KUMULATIF taban-honest low bu ustunde (pencere-basi DEGIL)
MAX_READY_LOCK_DAYS = 5
MAX_TABAN_RATIO_PCT = 60
MAX_TABAN_RATIO_RANGE_PCT = 50
MAX_WINDOW_DRAG_PCT = 8.0       # C2b: pencere-basi taban-drag (low) tavani. YARGI-CAGRISI:
#   drag ~1.5pp/taban-stop (olculen: TERA %17.5 ceza x %9 agirlik). 8pp ~= 5-6 taban-stop =
#   sepetin YARISI bir pencerede kilit = kriz-baslangici (2018/2020 deseni) = yakalanmasi
#   gereken kuyruk. Gozlem-ustu (olculen max 4.45pp, ~1.8x), felaket-alti (gercek kriz 12-30pp+).
#   PROVIZYONEL: 2 pencerede kalibre; C1=5'e ulasinca YENIDEN BAK (normal-rough 8'e yaklasirsa
#   cok-tutuk). C2b "tum pencereler <=tavan" -> bir asim kalici diskalifiye (KASITLI: gercek
#   felaket-penceresi gorursen gecme; churny-non-felaket tetiklerse esigi revize et).

CORP_ACTION_THRESH = -20.0     # gunluk < bu = BIST ±%10/20 limit-DISI = kesin bedelsiz/split
#   artefakti (ham veri, auto_adjust=False). Taban DEGIL -> ledger'da taban-sayimi+drag'den haric.
#   IZOLE: sadece bu tool; F'e/F-girdisine/backtest.py'ye dokunmaz (regresyon riski YOK).


def _last_history_date(pf_path=None):
    pf_path = pf_path or os.path.join(REPO, "portfolios", "portfolio_F.json")
    s = json.load(open(pf_path, encoding="utf-8"))
    hist = s.get("history", [])
    return hist[-1]["date"] if hist else None


def _total_at_or_before(hist, date_value):
    total = 1.0
    for h in hist:
        if h.get("date") <= date_value:
            total = h.get("total", total)
    return total


def analyze_window(pf_path=None, since_date=None):
    pf_path = pf_path or os.path.join(REPO, "portfolios", "portfolio_F.json")
    s = json.load(open(pf_path, encoding="utf-8"))
    hist = s.get("history", [])
    end_date = hist[-1]["date"] if hist else None
    start_total = _total_at_or_before(hist, since_date) if since_date else 1.0
    stops = []
    for h in hist:
        if since_date and h.get("date") <= since_date:
            continue
        for tr in (h.get("trades") or []):
            if tr.get("type") == "SELL" and tr.get("reason") == "stop":
                stops.append(dict(date=h["date"], tic=tr["ticker"], price=tr["price"],
                                  shares=tr.get("shares"), total=h.get("total")))
    booked = (hist[-1]["total"] / start_total - 1) * 100 if hist and start_total else 0.0
    tics = list({x["tic"] for x in stops})
    if not tics:
        return dict(
            run_date=str(pd.Timestamp.now().date()),
            window_start_date=since_date,
            window_last_date=end_date,
            n_stops=0, n_taban_stops=0,
            taban_ratio=0,
            max_consecutive_lock=0,
            multi_day_locks=0,
            booked_ret=round(booked, 1),
            drag_close=0, drag_low=0,
            taban_honest_close=round(booked, 1),
            taban_honest_low=round(booked, 1),
            stops=[],
            note="stop yok",
        )
    start = (pd.Timestamp(since_date) - pd.Timedelta(days=5) if since_date
             else pd.Timestamp("2026-05-20"))
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=2)
    raw = yf.download([t + ".IS" for t in tics], start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                      interval="1d", auto_adjust=False, progress=False, group_by="column")
    close = raw["Close"].copy(); low = raw["Low"].copy()
    close.columns = [c.replace(".IS", "") for c in close.columns]
    low.columns = [c.replace(".IS", "") for c in low.columns]
    details = []; drag_stops = []; locks = []; corp_actions = 0
    for x in stops:
        t = x["tic"]
        if t not in close.columns:
            continue
        ser = close[t].dropna(); lser = low[t].reindex(ser.index)
        pos = ser.index.searchsorted(pd.Timestamp(x["date"]))
        if pos <= 0 or pos >= len(ser):
            continue
        rc = FLA.backtest_exit(ser, pos)
        rl = FLA.backtest_exit(ser, pos, use_low=True, lows_series=lser)
        dayret = round((ser.iloc[pos] / ser.iloc[pos - 1] - 1) * 100, 1)
        # CORPORATE-ACTION GUARD (izole, ledger-side): gunluk < -%20 = BIST ±%10/20 limit-DISI
        # = kesin bedelsiz/split artefakti (auto_adjust=False), gercek taban DEGIL -> taban-sayimi
        # + drag'den haric tut. F'e/F-girdisine/backtest'e SIFIR dokunus; sadece hayalet-tabani onler.
        is_corp = dayret < CORP_ACTION_THRESH
        details.append(dict(date=x["date"], tic=t, daily_ret=dayret,
                            taban=(rc["was_locked"] and not is_corp),
                            corp_action=is_corp, lock_days=rc["lock_days"]))
        if is_corp:
            corp_actions += 1
        elif rc["was_locked"]:
            locks.append(rc["lock_days"])
            w = (x["shares"] * ser.iloc[pos] / x["total"] * 100
                 if x.get("shares") and x.get("total") else 0)
            drag_stops.append(dict(weight=w, recorded_exit=x["price"],
                                   real_exit_close=rc["exit_price"], real_exit_low=rl["exit_price"]))
    dg = FLA.portfolio_drag(drag_stops)
    n = len(details); nt = len(locks)
    return dict(
        run_date=str(pd.Timestamp.now().date()),
        window_start_date=since_date,
        window_last_date=end_date,
        n_stops=n, n_taban_stops=nt, corp_action_stops=corp_actions,
        taban_ratio=round(nt / (n - corp_actions) * 100) if (n - corp_actions) else 0,
        max_consecutive_lock=max(locks) if locks else 0,
        multi_day_locks=sum(1 for l in locks if l >= 2),
        booked_ret=round(booked, 1),
        drag_close=dg["drag_close_pct"], drag_low=dg["drag_low_pct"],
        taban_honest_close=round(booked - dg["drag_close_pct"], 1),
        taban_honest_low=round(booked - dg["drag_low_pct"], 1),
        stops=details,
    )


def load_ledger():
    if os.path.exists(LEDGER):
        try:
            return json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            return []
    return []


def save_ledger(ledger):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)


def assess(ledger):
    """OLCULEBILIR gecis-kriteri (sezgi degil). Doner: (hazir_mi, satirlar)."""
    n = len(ledger)
    c1 = n >= MIN_READY_WINDOWS
    # C2: (a) KUMULATIF taban-honest low > 0 (bireysel dusus-penceresine izin; momentum
    #     stratejisi dusus donemleri yasar — "her pencere pozitif" sistemi paper'da hapseder)
    #     + (b) pencere-basi taban-drag sinirli (taban-lock SURPRIZINI yakalar, piyasayi degil).
    cum_low = 1.0
    for w in ledger:
        cum_low *= (1 + w.get("taban_honest_low", 0) / 100.0)
    cum_low = (cum_low - 1) * 100
    c2a = (cum_low > MIN_LOW_RETURN_PCT) and n > 0
    c2b = all(w.get("drag_low", 0) <= MAX_WINDOW_DRAG_PCT for w in ledger) and n > 0
    c2 = c2a and c2b
    c3 = all(w.get("max_consecutive_lock", 0) <= MAX_READY_LOCK_DAYS for w in ledger) and n > 0
    ratios = [w.get("taban_ratio", 0) for w in ledger]
    ratio_range = (max(ratios) - min(ratios)) if ratios else 0
    c4 = (
        n > 0
        and max(ratios) <= MAX_TABAN_RATIO_PCT
        and (n < 2 or ratio_range <= MAX_TABAN_RATIO_RANGE_PCT)
    )
    lines = [
        f"  C1 Yeterli kanit (>={MIN_READY_WINDOWS} pencere): {'OK' if c1 else 'HAYIR'} ({n} pencere)",
        f"  C2 Kumulatif-poz + drag-sinir  : {'OK' if c2 else 'HAYIR'} "
        f"(a: kum-low {cum_low:+.1f}%>0={c2a} | b: drag<={MAX_WINDOW_DRAG_PCT}pp={c2b})",
        f"  C3 Modellenmis kuyruk (<={MAX_READY_LOCK_DAYS} gun): {'OK' if c3 else 'HAYIR'}",
        f"  C4 Taban_ratio kontrolu        : {'OK' if c4 else 'HAYIR'} "
        f"{ratios} (max<={MAX_TABAN_RATIO_PCT}, aralik<={MAX_TABAN_RATIO_RANGE_PCT})",
    ]
    ready = c1 and c2 and c3 and c4
    verdict = ("HAZIR-ADAYI (kriter saglandi; yine de son karari sen ver)" if ready
               else f"HENUZ DEGIL â€” {max(0, MIN_READY_WINDOWS-n)} pencere daha + kriterler tutmali (kanit birikiyor)")
    return ready, lines, verdict


if __name__ == "__main__":
    ledger = load_ledger()
    last_window = ledger[-1].get("window_last_date") if ledger else None
    current_window = _last_history_date()
    if last_window and current_window == last_window:
        print("=" * 62)
        print("TABAN-DURUST GERCEK-PARA DEFTERI (izole; dashboard'a dokunmaz)")
        print("=" * 62)
        print(f"Yeni pencere yok: son kayit zaten {last_window}. Defter degismedi.")
        print()
        print(f"GECIS KRITERI ({len(ledger)} pencere birikti):")
        ready, lines, verdict = assess(ledger)
        for l in lines:
            print(l)
        print(f"  -> {verdict}")
        print(f"\nDefter: {os.path.relpath(LEDGER, REPO)} (izole, daemon commit yolunda DEGIL)")
        sys.exit(0)

    rec = analyze_window(since_date=last_window)
    # ayni pencereyi tekrar ekleme (dedup: window_last_date)
    ledger = [w for w in ledger if w.get("window_last_date") != rec.get("window_last_date")]
    ledger.append(rec)
    ledger.sort(key=lambda w: w.get("window_last_date") or "")
    save_ledger(ledger)

    print("=" * 62)
    print("TABAN-DURUST GERCEK-PARA DEFTERI (izole; dashboard'a dokunmaz)")
    print("=" * 62)
    print(f"Pencere son tarih: {rec.get('window_last_date')} | stop: {rec.get('n_stops')} "
          f"| taban-stop: {rec.get('n_taban_stops')} (%{rec.get('taban_ratio')})")
    print(f"  Kayitli (kagit)      : +{rec.get('booked_ret')}%")
    print(f"  Taban-durust ARALIK  : +{rec.get('taban_honest_low')}% .. +{rec.get('taban_honest_close')}%  "
          f"(drag {rec.get('drag_low')} .. {rec.get('drag_close')}pp)")
    print(f"  Ardisik-kilit: max {rec.get('max_consecutive_lock')} gun | cok-gunluk lock: {rec.get('multi_day_locks')}")
    print("  Stop detay:")
    for d in rec.get("stops", []):
        print(f"    {d['date']} {d['tic']:6s} gun-ret {d['daily_ret']:+.1f}%  "
              f"{'TABAN ('+str(d['lock_days'])+'g kilit)' if d['taban'] else 'normal'}")
    print()
    print(f"GECIS KRITERI ({len(ledger)} pencere birikti):")
    ready, lines, verdict = assess(ledger)
    for l in lines:
        print(l)
    print(f"  -> {verdict}")
    print(f"\nDefter: {os.path.relpath(LEDGER, REPO)} (izole, daemon commit yolunda DEGIL)")
