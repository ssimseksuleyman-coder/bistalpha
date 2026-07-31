#!/usr/bin/env python3
"""
Shadow mode runner — A/B/F/O paralel hesaplar, KALICI portföylerle.

Her çağrıda (günlük/rebalance):
  1. Her hesabın kalıcı portföyünü yükle
  2. Stop kontrol -> SAT
  3. Rebalance günüyse yeni pick'lerle güncelle
  4. Portföyü kaydet (state kalıcı)
  5. 4 metrik logla: getiri, DD, give-back, false-negative

Kullanım:
  python shadow.py                  # bugünün shadow adımı
  python shadow.py --status         # hesapların güncel durumu
"""
import argparse
import sys
import os
import json
import traceback
from datetime import datetime

import pandas as pd

from bist_alpha import config, datafeed
from bist_alpha import notifier
from bist_alpha import signals as sig_mod
from bist_alpha import strategy as strat_mod
from bist_alpha import omega as omega_mod
from bist_alpha import g1_account as g1_mod
from bist_alpha import portfolio as pf
from bist_alpha import backtest as bt_mod
from bist_alpha import tradelog
from bist_alpha.signals import lot_multiplier

ACCOUNTS = {"A": "A", "B": "B", "F": "F", "O": "O"}  # mode'lar


def _attach_dynamic_universe(feed, data):
    """Stratejinin canlı feed'in seçtiği dinamik evreni kullanmasını sağlar."""
    universe = feed.dynamic_universe(data)
    data['_dynamic_universe'] = universe
    data['_dynamic_universe_method'] = (
        'likidite_fiyat_x_hacim'
        if data.get('_source') in ('yahoo', 'borsapy')
        else 'piyasa_degeri'
    )
    print(f"[shadow] Kaynak: {data.get('_source', config.DATA_SOURCE)}")
    print(f"[shadow] Dinamik evren: {len(universe)}")
    return data



def _g1_events_to_trades(events):
    """G1 events yapisini mevcut trade notice formatina cevirir."""
    trades = []
    for item in (events or {}).get("buys", []):
        trades.append({
            "type": "BUY", "ticker": item.get("ticker"),
            "price": item.get("price"), "reason": "g1",
        })
    for item in (events or {}).get("sells", []):
        trades.append({
            "type": "SELL", "ticker": item.get("ticker"),
            "price": item.get("price"), "reason": item.get("reason", "g1"),
            "pnl_pct": item.get("pnl_pct"),
            "was_reentry": item.get("was_reentry", False),
        })
    for item in (events or {}).get("reentries", []):
        trades.append({
            "type": "REENTRY", "ticker": item.get("ticker"),
            "price": item.get("price"), "reason": "g1",
        })
    return trades

def _format_trade_notice(result):
    """Sadece gerçekleşen shadow işlemleri için kısa bildirim metni üretir."""
    lines = []
    for acc, info in result.get("accounts", {}).items():
        event = info.get("last_event") or {}
        trades = info.get("new_trades") or []
        if not trades:
            continue
        lines.append(f"Hesap {acc} | {event.get('event', 'islem')} | değer {info.get('value')} | pozisyon {info.get('n_pos')}")
        for tr in trades[:12]:
            extra = f" | P/L %{tr['pnl_pct']}" if tr.get("pnl_pct") is not None else ""
            lines.append(f"  {tr.get('type')} {tr.get('ticker')} @ {tr.get('price')}{extra}")
        if len(trades) > 12:
            lines.append(f"  ... {len(trades) - 12} işlem daha")
    if not lines:
        return None
    return f"Tarih: {result.get('date')}\n\n" + "\n".join(lines)


def _last_selection_date(state):
    """history'deki son (initial_entry|rebalance) olayinin tarihi; yoksa None."""
    for h in reversed(state.get("history") or []):
        if h.get("event") in ("initial_entry", "rebalance"):
            d = str(h.get("date") or "")[:10]
            return d or None
    return None


def _trading_days_between(prices_index, start_date, end_date):
    """prices index'ine gore start (haric) -> end (dahil) arasi ISLEM-GUNU; hesaplanamazsa None."""
    if not start_date:
        return None
    try:
        s = pd.Timestamp(start_date)
        e = pd.Timestamp(end_date)
    except Exception:
        return None
    i = int(prices_index.searchsorted(s))
    j = int(prices_index.searchsorted(e))
    if i >= len(prices_index) or j >= len(prices_index):
        return None
    return j - i


def rebal_status(state, prices, date):
    """
    REBALANCE TAKVIMI — PORTFOY-DEMIRLI (bar-index DEGIL).

    ESKI BUG: is_rebal = date in bt_mod._rebal_dates(prices) -> veri-penceresinin
    252./282./312. INDEX'leri. Backtest'te pencere SABIT oldugu icin dogru calisir;
    ama canlida pencere her gun KAYIYOR (yfinance rolling "2y") -> bugunun index'i
    hep 252'den ~249 uzakta -> 249 %% 30 != 0 -> rebalance HIC tetiklenmedi
    (06-05'ten 07-17'ye 0 kez; 3 bagimsiz kanit: modulo, dashboard, portfoy-gecmisi).
    REBAL_GUN canlida "30 islem gunu gecti mi" degil "pencere 30'un katinda mi"
    anlamina geliyordu — ayni sabit, iki farkli anlam.

    DOGRU semantik: son secim-olayindan (initial_entry|rebalance) bu yana
    REBAL_GUN ISLEM-GUNU gectiyse rebalance zamani.

    Returns: (should_rebalance, initial_entry, elapsed, last_selection)
    elapsed/last_selection sonuca yazilir -> takvim DASHBOARD'DA GORUNUR
    (sessiz-hic-tetiklenmeme bir daha fark edilmeden kalmasin).
    """
    initial_entry = not state.get("positions") and not state.get("history")
    if initial_entry:
        return True, True, None, None
    last_sel = _last_selection_date(state)
    elapsed = _trading_days_between(prices.index, last_sel, date)
    should = elapsed is not None and elapsed >= config.REBAL_GUN
    return should, False, elapsed, last_sel


def step(data, signals, date=None, slippage=None, run_label=None):
    """Tüm hesaplar için bir shadow adımı.

    run_label: koşu slotu ("acilis"/"bulten"/"gunici"/"kapanis"/"manuel"...).
    STOP DEGERLENDIRMESI YALNIZ "kapanis" KOSUSUNDA yapilir — bkz #0l.
    """
    prices = data['prices']
    if date is None:
        date = prices.index[-1]
    slippage = slippage if slippage is not None else config.SLIPPAGE_PER_SIDE
    row = prices.loc[date].dropna()
    prices_today = row.to_dict()

    # NOT: rebalance takvimi artik PORTFOY-DEMIRLI (bkz. rebal_status).
    # Eski global bar-index tetikleyicisi (bt_mod._rebal_dates) canlida hic tetiklenmiyordu.
    trade_date = str(date.date()) if hasattr(date, "date") else str(date)

    results = {}
    for acc, mode in ACCOUNTS.items():
        try:
            state = pf.load(acc, state_dir=config.STATE_DIR)
            # 1) Stop kontrol — YALNIZ KAPANIS KOSUSU (#0l phantom-stop duzeltmesi)
            #
            # ESKI DAVRANIS (bug): her kosuda (acilis/gunici/kapanis) calisirdi.
            #   (A) BAYAT-BAR: acilis kosusu (09:45 TR, borsa kapali) onceki/eski
            #       bara donuyordu -> eski fiyat, yeni peak'e karsi cokus gorunur.
            #       OZATD 2026-07-27: pt=3427.5 (07-27 bari) vs peak=3770 (07-28
            #       kapanisi) -> gain %39.9 -> TIGHT(%5) -> phantom stop.
            #   (B) INTRADAY PEAK SISMESI: gun-ici kosu peak'i KISMI bardan
            #       guncelliyordu (backtest asla yapmaz; peak yalniz yukari
            #       kilitlendigi icin bias tek yonlu). GUNDG: peak 2637.5 >
            #       en yuksek kapanis 2630.0 -> kapanis-bazli olsaydi stop YOK.
            #   Olculen sonuc: 5 stop'un 2'si ARTEFAKT (2026-07-29).
            #
            # YENI KURAL: stop yalnizca "kapanis" slotunda degerlendirilir. O kosu
            # 18:40 TR'de calisir, BIST 18:00'de kapanir -> son bar TAM ve BUGUNKU.
            # Tetik VE fill ayni tam kapanis barindan gelir = backtest semantigi
            # (backtest.py gunde bir bar, bir kontrol). Boylece (A) ve (B) birlikte
            # kapanir; gun-ici kontroller zaten bilgi olarak bostu (ayni tam
            # kapanisa karsi ayni cevap).
            #
            # TZ NOTU: "kapanis" etiketi precise_runner.target_slot()'tan gelir
            # (tek TZ kaynagi). Stop yoluna IKINCI bir duvar-saati hesabi
            # EKLENMEDI — iki bagimsiz saat hesabinin ayrismasi bilinen bug sinifi.
            if run_label == "kapanis":
                sells = pf.check_stops(state, prices_today)
                stop_trades = pf.close_positions(state, sells, prices_today,
                                                 slippage=slippage, trade_date=trade_date)
            else:
                sells, stop_trades = [], []
            new_trades = list(stop_trades)
            # 2) Rebalance — PORTFOY-DEMIRLI takvim (her hesap kendi gecmisinden sayar)
            should_rebalance, initial_entry, rebal_elapsed, last_selection = rebal_status(
                state, prices, date)
            if should_rebalance:
                if mode == "O":
                    picks, sig_map, exc = omega_mod.select(data, signals, date)
                    weights = omega_mod.weights(picks, sig_map)
                else:
                    picks, sig_map, exc = strat_mod.select(data, signals, date, mode=mode)
                    if mode in ("B", "F"):
                        weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
                    else:
                        weights = {t: 1.0 for t in picks}
                scale = strat_mod.regime_scale(data, date)
                reason = "initial_entry" if initial_entry else "rebalance"
                pf.rebalance(state, weights, prices_today, slippage=slippage,
                             trade_date=trade_date, reason=reason, scale=scale)
                new_trades.extend((state.get("history", [])[-1] or {}).get("trades", []))
            pf.save(state, state_dir=config.STATE_DIR)
            results[acc] = {
                "value": round(pf.current_value(state, prices_today), 4),
                "n_pos": len(state["positions"]),
                "sells": sells,
                "stop_trades": stop_trades,
                "rebalance": should_rebalance,
                "initial_entry": initial_entry,
                # Takvim GORUNURLUGU — sessiz "hic tetiklenmedi" bir daha gizli kalmasin.
                "last_selection": last_selection,
                "rebal_elapsed": rebal_elapsed,
                "rebal_due_in": (config.REBAL_GUN - rebal_elapsed) if rebal_elapsed is not None else None,
                "new_trades": new_trades,
                "last_event": state.get("history", [])[-1] if state.get("history") else None,
            }
            try:
                tradelog.log_trades(acc, trade_date, new_trades)
            except Exception as e:
                print(f"[shadow] {acc} tradelog yazilamadi: {e}")
        except Exception:
            tb = traceback.format_exc()
            print(f"[shadow] Hesap {acc} HATA:\n{tb}")
            results[acc] = {"error": tb[:500]}
    g1_state = pf.load("G1", state_dir=config.STATE_DIR)
    g1_initial_entry = not g1_state.get("positions") and not g1_state.get("history")
    if g1_initial_entry:
        # DOGRU BOOTSTRAP DESENI: gec-katilan shadow, kendi (belki ince-gun) select()'i
        # yerine F'in O ANKI portfoyunu bugunku fiyattan aynalar (fractional mirror).
        # Boylece cold-start gunu tek-sinyal gunune denk gelse bile shadow dejenere
        # baslamaz. F entry gecmisi KOPYALANMAZ (look-ahead onleme). Yarin bir G2
        # eklenirse ayni tuzaga dusmez. Bkz. cold_start_from_reference / G1_DEVIR_NOTU.
        f_state = pf.load("F", state_dir=config.STATE_DIR)
        g1_state, g1_events = g1_mod.cold_start_from_reference(
            g1_state, f_state, prices_today, date, slippage=slippage,
            reason="gec-katilim cold-start, F'e senkron (bugunku fiyat)")
        g1_should_rebalance = True
    else:
        # G1 de PORTFOY-DEMIRLI (eski bar-index tetikleyicisi ayni bug'i tasiyordu)
        g1_should_rebalance, _g1_ie, _g1_elapsed, _g1_lastsel = rebal_status(g1_state, prices, date)
        # eval_stops: G1 de F ile AYNI stop semantigi (yalniz kapanis) — #0l.
        # Yarim birakilirsa G1 kiyasi hipotezi degil semantik farki olcer.
        g1_state, g1_events = g1_mod.step(
            data, signals, g1_state, date, prices_today, g1_should_rebalance,
            slippage=slippage, eval_stops=(run_label == "kapanis"))
    f_return_pct = None
    if results.get("F", {}).get("value") is not None:
        f_return_pct = (results["F"]["value"] - 1) * 100
    g1_info = g1_mod.summary(g1_state, prices_today, f_return_pct=f_return_pct)
    g1_trades = _g1_events_to_trades(g1_events)
    g1_info.update({
        "n_pos": g1_info.get("n_positions"),
        "rebalance": g1_should_rebalance,
        "initial_entry": g1_initial_entry,
        "events": g1_events,
        "new_trades": g1_trades,
        "last_event": {
            "date": trade_date,
            "event": "g1_shadow",
            "trades": g1_trades,
        } if g1_trades else None,
    })
    pf.save(g1_state, state_dir=config.STATE_DIR)
    try:
        tradelog.log_trades("G1", trade_date, g1_trades)
    except Exception as e:
        print(f"[shadow] G1 tradelog yazilamadi: {e}")
    results["G1"] = g1_info
    # STOP-DEGERLENDIRME IZI (#0l): yalniz gercekten degerlendirildiginde yaz.
    _write_stop_eval(run_label, trade_date, results)
    # Cycle-duzeyi bayrak: artik global bar-index yok -> hesaplardan turet.
    any_rebal = any(r.get("rebalance") for r in results.values() if isinstance(r, dict))
    return {"date": str(date.date()) if hasattr(date, "date") else str(date),
            "rebalance": any_rebal, "accounts": results}


def _write_stop_eval(run_label, trade_date, results):
    """docs/state/stop_eval.json — 'stop en son NE ZAMAN, HANGI BAR icin degerlendirildi'.

    NEDEN (#0l'in ACTIGI kor nokta): #0l sonrasi stop YALNIZ kapanis kosusunda
    degerlendiriliyor. Ama liveness `daemon_cycle` programini (7,12,16 UTC)
    UC SLOTU BIRLIKTE sayiyor (liveness_scan.py:82) -> yalniz kapanis kosusu
    kacarsa 11:30 kosusu damgalari tazeler ve KIRMIZI GELMEZ; oysa o gun stop
    HIC degerlendirilmemis olur. Stop = ayi korumasinin tek kolonu (#0m) ->
    bosluk tam tasiyici kolonda. Kor nokta zaten biliniyordu (liveness_scan.py:297
    yorumu: "KACAN SLOTU GIZLEYEBILIR = alarm korlugu"); #0l onu gizliden
    YUK TASIYANA cevirdi.

    TASARIM KISITLARI (bilincli):
      - Ayri artefakt: F portfoyune (portfolio_F.json) YAZILMAZ. O dosyanin
        anahtarlari [account, cash, positions, history]; uretici-damgasi eklemek
        F-state'e yazmak olurdu (schema_version dersi, dc81cb5).
      - YALNIZ IZ, KARAR DEGIL: hicbir kod bu damgaya bakip farkli davranmaz.
        "last_eval eskiyse su stop kuralini uygula" gibi bir kural F mantigina
        sizardi -> YASAK.
      - Yalniz stop GERCEKTEN degerlendirildiginde yazilir. Her kosuda yazilsa
        damga hep taze olur ve kor noktayi KAPATMAZ (izlemenin kendi kor noktasi).
      - UTC + tz 0.0 (content_sanity/watchdog deseni) -> offset matematigi yok.
    """
    if run_label != "kapanis":
        return
    try:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "state")
        os.makedirs(out_dir, exist_ok=True)
        n_stops = sum(len((r or {}).get("stop_trades") or [])
                      for r in results.values() if isinstance(r, dict))
        payload = {
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
            "tz": "UTC",
            "writer": "shadow._write_stop_eval",
            "run_label": run_label,
            "eval_bar": trade_date,
            "accounts": sorted(k for k in results if isinstance(results.get(k), dict)),
            "stops_triggered": int(n_stops),
            "opens_trade": False,
            "note": ("Stop-degerlendirme izi (#0l). YALNIZ kapanis kosusunda yazilir; "
                     "bayatlarsa 'o gun stop degerlendirilmedi' demektir. "
                     "IZ'dir, KARAR DEGIL - hicbir kod buna bakip davranis degistirmez."),
        }
        tmp = os.path.join(out_dir, "stop_eval.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(out_dir, "stop_eval.json"))
    except Exception as e:
        # Iz yazilamazsa AKIS DURMAZ (izleme, karar degil) - ama sessiz de kalmaz.
        print(f"[shadow] stop_eval izi yazilamadi: {e}")


def status():
    """Hesapların güncel durumunu göster."""
    feed = datafeed.get_feed()
    data = feed.get_latest()
    data = _attach_dynamic_universe(feed, data)
    prices = data['prices']
    date = prices.index[-1]
    prices_today = prices.loc[date].dropna().to_dict()
    print(f"=== SHADOW DURUM @ {date.date()} ===")
    for acc in ACCOUNTS:
        state = pf.load(acc, state_dir=config.STATE_DIR)
        val = pf.current_value(state, prices_today)
        ret = (val - 1) * 100
        print(f"\nHesap {acc}: değer {val:.3f} (getiri %{ret:.1f}), {len(state['positions'])} pozisyon")
        for t, p in list(state["positions"].items())[:12]:
            st = pf.stop_level(p)
            cur = prices_today.get(t, p['entry'])
            print(f"   {t:7s} giriş {p['entry']:.1f} | güncel {cur:.1f} | stop {st:.1f}")


def main():
    ap = argparse.ArgumentParser(description="Shadow mode A/B/F/O runner")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        status()
        return
    feed = datafeed.get_feed()
    data = feed.get_latest()
    data = _attach_dynamic_universe(feed, data)
    signals = sig_mod.compute_signals(data)
    r = step(data, signals)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    notice = _format_trade_notice(r)
    if notice:
        notifier.notify_all("📌 BIST Alpha Shadow İşlem", notice)


if __name__ == "__main__":
    sys.exit(main())
