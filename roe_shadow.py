"""
roe_shadow.py — IZOLE ROE-SAPMA olcum-araci (G3). OLCUM-ARACI, canli-hesap DEGIL.

F'e / portfoylere / dashboard.json'a / shadow.py'ye SIFIR dokunus. Sadece portfolio_F.json'i
OKUR + yfinance. backtest.run(F) DEGISMEZ (regresyon-none, taban-guard gibi).

AMAC: F'in momentum-pick'lerine ROE-filtresi (yuksek-ROE alt-kume) uygulamanin CANLI forward
katkisini olcmek. G3 = F'i AYNALAMAZ (yoksa sinyal olculmez) -> ROE-filtreli SAPMA. G3-vs-F
forward-getiri farki = ROE-filtre'nin katkisi. Yon OLCUMDEN turetildi (ROE +0.16 = yuksek-iyi,
ZAYIF-sinyal, n=67; G3 forward gozlem biriktirerek firm-up eder — simdiden hukum YOK).

LOOK-AHEAD-SIZ (kaynak-PIT'liginden degil, FORWARD-INSADAN): forward-only, backfill YOK. Her
karar O AN yfinance-guncel-ROE'yle DONDURULUR (frozen), gecmis kararlar current-ROE ile yeniden
hesaplanmaz. Deniz-PIT'e gerek yok (Deniz teknik, ROE vermez); kaynak yfinance-guncel.

KULLANIM:
  python roe_shadow.py             -> F'in GUNCEL portfoyunu tek-kayit dondurur (elle, hizli).
  python roe_shadow.py --catch-up  -> son ledger-kaydindan bugune F'in TUM event'lerini GERIYE-
                                      BAKIP yakalar (history-replay), her birini O EVENTIN
                                      tarihiyle + O AN frozen-ROE'yle kaydeder. Haftalik-cron bunu
                                      cagirir; boylece ara-event'ler (rebalans/stop) KACMAZ.

BACKFILL-YASAGI (catch-up'ta look-ahead onlemenin ANAHTARI): catch-up yalnizca OLGUNLASMAMIS
event'leri (yas < HORIZON_DAYS) dondurur. Forward-penceresi zaten dolmus (matured) bir event'i
"simdi" dondurmek = sonucu-bilerek-karar = backfill = look-ahead -> ATLANIR (skipped_matured).
Haftalik-cron'da her event <=7 gun icinde yakalanir (<< 21g ufuk) -> her zaman olgunlasmamis ->
temiz. Yalniz aracin-varligindan-ONCEKI matured event'ler (or. ilk-giris) kurtarilamaz — dogru,
onlari backfill etmek look-ahead olurdu.

KONSANTRASYON-KORUMASI: medyan-split AMA MIN_G3_PICKS taban -> G3 asiri-konsantre olup "edge"i
ROE yerine konsantrasyondan almasin (RSI-confound dersi). n_f vs n_g3 ledger'da (izlenir).

BAGIMSIZLIK NOTU (analiz-zamani, capture-zamani DEGIL): stop'lar mevcut-sepeti daraltir -> ardil
event'lerin sepetleri ORTUSUR (seri-korele). Bagimsiz-gozlem = tam-secim event'leri (initial/
rebalance): REBAL_GUN=30 > HORIZON=21 -> pencereleri ORTUSMEZ. Ledger her event'i event_type ile
etiketler; edge-ozeti hem ham-n hem bagimsiz-n (secim-event'leri) verir.
"""
import json, os, sys, warnings; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd, numpy as np

REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "roe_shadow_ledger.json")
MIN_G3_PICKS = 5        # az-pick taban (konsantrasyon-confound korumasi)
HORIZON_DAYS = 21       # forward-getiri ufku (~1 rebalans) + backfill-yasagi esigi
SELECTION_EVENTS = ("initial_entry", "rebalance")  # bagimsiz (tam-secim) event'ler


def _load(p, default):
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: return default
    return default


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _f_state():
    """portfolio_F.json (OKUR, dokunmaz)."""
    return json.load(open(os.path.join(REPO, "portfolios", "portfolio_F.json"), encoding="utf-8"))


def f_current_picks():
    """F'in guncel portfoyu (canli holdings) + son event tarihi. OKUR, dokunmaz."""
    s = _f_state()
    picks = list(s.get("positions", {}).keys())
    dt = s.get("history", [])[-1]["date"] if s.get("history") else None
    return picks, dt


def replay_holdings(history):
    """F history'sini (trade-delta'lari) oynatarak HER event'te post-trade holdings'i cikarir.
    Doner: [(date, event_type, sorted(holdings)), ...] — event sirasiyla."""
    held, out = set(), []
    for ev in history:
        for tr in ev.get("trades", []):
            if tr.get("type") == "BUY":
                held.add(tr["ticker"])
            elif tr.get("type") == "SELL":
                held.discard(tr["ticker"])
        out.append((ev.get("date"), ev.get("event", ""), sorted(held)))
    return out


def frozen_roe(tickers):
    """O ANKI yfinance-guncel ROE (frozen — karar-aninda dondurulur, sonra re-fetch yok)."""
    roe = {}
    for t in tickers:
        try: roe[t] = yf.Ticker(t + ".IS").info.get("returnOnEquity")
        except Exception: roe[t] = None
    return roe


def roe_filter(picks, roe):
    """Medyan-split + az-pick taban. Doner: (g3_picks, not)."""
    valid = {t: r for t, r in roe.items() if r is not None}
    if len(valid) < 2:
        return list(picks), "roe-yok -> filtre-yok (F ile ozdes, sinyal-yok kayit)"
    med = float(np.median(list(valid.values())))
    kept = [t for t in picks if valid.get(t, med - 1e9) >= med]   # yuksek-ROE yari
    note = "medyan-split (ROE>=%.3f)" % med
    if len(kept) < MIN_G3_PICKS and len(valid) >= 1:              # AZ-PICK KORUMASI
        kept = [t for t, _ in sorted(valid.items(), key=lambda x: -x[1])[:MIN_G3_PICKS]]
        note = "az-pick-floor: en yuksek-ROE %d (medyan-split %d biraktirdi)" % (MIN_G3_PICKS, sum(1 for t in picks if valid.get(t, med-1e9) >= med))
    return kept, note


def _freeze_decision(date, event_type, holdings):
    """Bir kararı DONDUR (frozen ROE + ROE-filtre). fwd=None (olgunlasinca dolar)."""
    roe = frozen_roe(holdings)
    g3, note = roe_filter(holdings, roe)
    return dict(date=date, event_type=event_type, f_picks=holdings,
                roe={t: (round(r, 4) if r is not None else None) for t, r in roe.items()},
                g3_picks=g3, n_f=len(holdings), n_g3=len(g3), filter_note=note, fwd=None)


def record(ledger):
    """Guncel (tek) rebalans kararini DONDUR (elle-kullanim; look-ahead-siz: bugunku ROE)."""
    picks, dt = f_current_picks()
    if not picks or dt is None:
        return ledger, [], []
    if any(e.get("date") == dt for e in ledger):
        return ledger, [], []
    etype = _f_state().get("history", [])[-1].get("event", "")
    rec = _freeze_decision(dt, etype, picks)
    ledger.append(rec)
    return ledger, [rec], []


def catch_up(ledger):
    """Son ledger-kaydindan bugune TUM F-event'lerini geriye-bakip yakalar (history-replay).
    Look-ahead-siz: yalniz OLGUNLASMAMIS (yas < HORIZON) event dondurulur; matured=backfill=atla.
    Doner: (ledger, caught[list of rec], skipped_matured[list of (date,age)])."""
    s = _f_state()
    history = s.get("history", [])
    recorded = {e.get("date") for e in ledger}
    last = max(recorded) if recorded else None
    now = pd.Timestamp.now().normalize()
    caught, skipped = [], []
    for date, etype, holdings in replay_holdings(history):
        if not date or not holdings:
            continue
        if date in recorded:                       # dedup (zaten kayitli)
            continue
        if last and date <= last:                  # yalniz son-kayittan SONRAsi
            continue
        age = (now - pd.Timestamp(date)).days
        if age >= HORIZON_DAYS:                     # BACKFILL-YASAGI: matured -> look-ahead -> atla
            skipped.append((date, age))
            continue
        rec = _freeze_decision(date, etype, holdings)
        ledger.append(rec)
        caught.append(rec)
        recorded.add(date)
    return ledger, caught, skipped


def evaluate(ledger):
    """Olgunlasan kararlar icin forward-getiri (F-all vs G3, esit-agirlik). Frozen kararlar."""
    for rec in ledger:
        if rec.get("fwd") is not None:
            continue
        d0 = pd.Timestamp(rec["date"])
        if (pd.Timestamp.now() - d0).days < HORIZON_DAYS:
            continue   # olgunlasmamis -> bekle (look-ahead-siz)
        tics = sorted(set(rec["f_picks"] + rec["g3_picks"]))
        try:
            raw = yf.download([t + ".IS" for t in tics],
                              start=(d0 - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                              end=(d0 + pd.Timedelta(days=HORIZON_DAYS + 7)).strftime("%Y-%m-%d"),
                              interval="1d", auto_adjust=True, progress=False, group_by="column")
            cl = raw["Close"].copy(); cl.columns = [c.replace(".IS", "") for c in cl.columns]
        except Exception:
            continue

        def basket_ret(names):
            rs = []
            for t in names:
                if t in cl.columns:
                    s = cl[t].dropna()
                    if len(s) >= 2:
                        r = (s.iloc[min(HORIZON_DAYS, len(s) - 1)] / s.iloc[0] - 1) * 100
                        if abs(r) <= 60:  # >±%60 = corp-action artefakti, atla (taban-guard dersi)
                            rs.append(r)
            return float(np.mean(rs)) if rs else None

        f_ret = basket_ret(rec["f_picks"]); g3_ret = basket_ret(rec["g3_picks"])
        if f_ret is not None and g3_ret is not None:
            rec["fwd"] = dict(f_ret=round(f_ret, 2), g3_ret=round(g3_ret, 2),
                              edge=round(g3_ret - f_ret, 2))
    return ledger


def _health(caught):
    """HEALTH-ozeti (workflow saglik-alarmi buna bagli). picks_with_roe=0 -> sessiz-bozulma alarmi;
    events_caught=0 (sessiz hafta) -> picks_with_roe=NA (yanlis-alarm onlenir)."""
    ec = len(caught)
    if ec == 0:
        pwr = "NA"
    else:
        pwr = sum(1 for r in caught for v in r["roe"].values() if v is not None)
    median_split = any(r["filter_note"].startswith("medyan-split") for r in caught)
    # SET-karsilastirma (siralamayla degil): az-pick floor g3'u ROE-sirali saklar, f alfabetik ->
    # liste-!= sadece siralama farkini "sapma" sanirdi. Gercek sapma = uye-kumesi farkli.
    deviation = any(set(r["g3_picks"]) != set(r["f_picks"]) for r in caught)
    return "HEALTH: events_caught=%d picks_with_roe=%s median_split_ok=%s deviation_happened=%s" % (
        ec, pwr, median_split, deviation)


if __name__ == "__main__":
    mode_catch = "--catch-up" in sys.argv[1:]
    ledger = _load(LEDGER, [])
    if mode_catch:
        ledger, caught, skipped = catch_up(ledger)
    else:
        ledger, caught, skipped = record(ledger)
    ledger = evaluate(ledger)
    ledger.sort(key=lambda e: e.get("date") or "")
    _save(LEDGER, ledger)

    print("=" * 64)
    print("ROE-SAPMA OLCUM DEFTERI (G3, izole; F'e/canliya DOKUNMAZ) - %s" %
          ("CATCH-UP" if mode_catch else "tek-kayit"))
    print("=" * 64)
    if caught:
        print("YENI KARAR(lar) frozen: %d" % len(caught))
        for rec in caught:
            print("  %s [%s] F(%d)=%s" % (rec["date"], rec.get("event_type", "?"), rec["n_f"], rec["f_picks"]))
            print("    ROE(frozen): %s" % {t: rec["roe"][t] for t in rec["f_picks"]})
            print("    G3(%d)=%s | %s" % (rec["n_g3"], rec["g3_picks"], rec["filter_note"]))
    else:
        print("Yeni karar yok (bu kosuda yeni F-event yok - dedup/son-kayit sonrasi bos).")
    if skipped:
        print("ATLANAN (matured, backfill-yasagi = look-ahead onleme): %s" %
              ["%s (%dg)" % (d, a) for d, a in skipped])

    matured = [e for e in ledger if e.get("fwd")]
    print("\nOLGUNLASAN KARARLAR (G3-vs-F forward, %dg):" % HORIZON_DAYS)
    if matured:
        edges = [e["fwd"]["edge"] for e in matured]
        indep = [e for e in matured if e.get("event_type") in SELECTION_EVENTS]
        for e in matured:
            print("  %s [%s]: F %+.2f%% | G3 %+.2f%% | edge %+.2fpp (n_g3=%d/%d)"
                  % (e["date"], e.get("event_type", "?"), e["fwd"]["f_ret"], e["fwd"]["g3_ret"],
                     e["fwd"]["edge"], e["n_g3"], e["n_f"]))
        print("  -> ROE-filtre ort edge: %+.2fpp (ham-n=%d; bagimsiz-n=%d secim-event). %s"
              % (np.mean(edges), len(edges), len(indep),
                 "cok az gozlem, hukum YOK" if len(indep) < 5 else "biriktikce firm-up"))
    else:
        print("  (henuz olgunlasan karar yok - forward-getiri %dg sonra dolar; look-ahead-siz)" % HORIZON_DAYS)

    print("\n" + _health(caught))
    print("Defter: %s (izole, daemon-commit yolunda DEGIL)" % os.path.relpath(LEDGER, REPO))
    print("Not: ROE zayif-sinyal (+0.16, n=67); G3 firm-up icin biriktirir, simdiden hukum yok.")
