"""
G1 hesabi (SHADOW / paper) — F secimi + stop-sonrasi yeniden-giris.

Karar (Analiz): F = primary/production; G1 = shadow/canli-kanit; F motoru AYNI kalir.
G1 getiri SATIN ALIR (bedava alpha degil): backtest +%445 vs F +%301 ama DD artar.
F'in yerine GECMEZ; "gec giris / erken cikis" pismanligini olcer.

Etiket: role="shadow", labels=["return_candidate","drawdown_watch"]
Yanlis-kirilim baz cizgisi (tarihsel 550g): re-entry->tekrar-stop %31.2, zararla %22.9.
Canli oran bunu asarsa summary() watch_triggered=True doner -> drawdown_watch aktif.

F'e SIFIR dokunus: ayri portfolio_G1.json, ayri hesap, ayri mantik.
"""
from datetime import datetime
from . import config
from . import portfolio as pf
from . import strategy as strat_mod
from .signals import lot_multiplier

ROLE = "shadow"
LABELS = ["return_candidate", "drawdown_watch"]
BASELINE_FB_RATE = 31.2       # tarihsel re-entry->tekrar-stop orani (%)
BASELINE_FB_LOSS_RATE = 22.9  # tarihsel zararla tekrar-stop (%)
FB_MIN_SAMPLE = 5             # watch tetigi icin min re-entry sayisi
# --- ROLLING THROTTLE (mitigator): son K re-entry kapanisinin basarisizlik orani ---
RE_THROTTLE_K = 8             # rolling pencere
RE_THROTTLE_RATE = 0.50       # rolling fail > bu -> lot %50
RE_PAUSE_RATE = 0.70          # rolling fail > bu -> re-entry DUR
RE_THROTTLE_FACTOR = 0.5      # kisma carpani
# Terfi kapilari (Analiz): bir canli donem F'i getiride gecerken AYNI ANDA saglanmali
PROMO_MAX_DD = -10.0          # max_dd_pct bundan SIG (daha dar) olmali
PROMO_FB_RATE = 31.2          # false_breakout_rate_pct <= bu
PROMO_FB_LOSS = 22.9          # false_breakout_loss_rate_pct <= bu
_STAT_KEYS = ("buys", "stops", "reentries", "reentry_restops", "reentry_restop_loss",
              "reentry_closed", "reentry_wins", "reentry_total_pnl_pct", "reentry_rebalance_loss_count",
              "reentry_throttled", "reentry_paused")
_EQUITY_CAP = 120             # gunluk deger serisi (sparkline), ust sinir
_TRADES_CAP = 500            # trade log ust siniri (sinirsiz buyumeyi onler)
_HISTORY_CAP = 250           # rebalance snapshot ust siniri


def _new_state(account="G1"):
    s = {"account": account, "cash": 1.0, "positions": {}, "history": [],
         "trades": [], "watch": {}, "equity_daily": [], "reentry_recent": [],
         "stats": {k: 0 for k in _STAT_KEYS}, "role": ROLE, "labels": LABELS}
    s["stats"]["peak_value"] = 1.0
    s["stats"]["max_dd_pct"] = 0.0
    return s


def _ensure(state):
    """Eski/yarim state dosyasini guvene al — her alt-anahtari tek tek tamamla (FIX 2)."""
    state.setdefault("cash", 1.0)
    state.setdefault("positions", {})
    state.setdefault("history", [])
    state.setdefault("trades", [])
    state.setdefault("watch", {})
    state.setdefault("reentry_recent", [])
    state.setdefault("equity_daily", [])
    stats = state.setdefault("stats", {})
    for k in _STAT_KEYS:
        stats.setdefault(k, 0)
    stats.setdefault("peak_value", None)   # ilk degerde set edilir
    stats.setdefault("max_dd_pct", 0.0)
    state.setdefault("role", ROLE)
    state["labels"] = LABELS               # her zaman guncel
    return state


def _close_reentry(state, pnl, via):
    """Bir re-entry pozisyonu kapandiginda (stop VEYA rebalance) tum cohort'u kaydet.
       reentry_restops sadece stop tarafiydi; bu, rebalance'da zararda kapananlari da yakalar."""
    st = state["stats"]
    st["reentry_closed"] += 1
    st["reentry_total_pnl_pct"] += pnl
    if pnl > 0:
        st["reentry_wins"] += 1
    if via == "stop":
        st["reentry_restops"] += 1
        if pnl < 0:
            st["reentry_restop_loss"] += 1
    elif via == "rebalance" and pnl < 0:
        st["reentry_rebalance_loss_count"] += 1
    rec = state.setdefault("reentry_recent", [])
    rec.append(1 if pnl < 0 else 0)
    if len(rec) > RE_THROTTLE_K:
        del rec[:-RE_THROTTLE_K]


def _value(state, prices_today):
    return state["cash"] + sum(p["shares"] * prices_today.get(t, p["entry"])
                               for t, p in state["positions"].items())


def _py(x):
    """numpy/pandas scalar -> native Python (JSON guvenli). Native zaten ise dokunmaz."""
    if isinstance(x, bool):
        return x
    item = getattr(x, "item", None)   # numpy/pandas scalar -> .item() native doner
    if callable(item):
        try:
            return x.item()
        except Exception:
            return x
    return x


def _log(state, date, typ, tic, price, **extra):
    rec = {"date": str(date.date()) if hasattr(date, "date") else str(date),
           "type": typ, "ticker": str(tic), "price": round(_py(price), 2)}
    for k, v in extra.items():
        rec[k] = v if isinstance(v, (str, bool)) else _py(v)
    state["trades"].append(rec)
    if len(state["trades"]) > _TRADES_CAP:
        state["trades"] = state["trades"][-_TRADES_CAP:]


def cold_start_from_reference(state, ref_state, prices_today, date, slippage=0.0, reason=""):
    """DOGRU BOOTSTRAP DESENI (gec-katilan shadow icin).

    Gec-katilan bir shadow'u referans hesabin (F) O ANKI portfoyune BUGUNKU
    fiyatlardan senkronlar (FRACTIONAL MIRROR): F'in yatirim-orani + goreli
    piyasa-degeri agirliklari korunur; boylece cold-start gunu tek-sinyal gunune
    denk gelse bile shadow dejenere (tek-isim) baslamaz.

    LOOK-AHEAD ONLEME: F'in entry GECMISI KOPYALANMAZ. G1 entry = reconcile gunu
    fiyati (F'in gerceklesmis kari retroaktif yazilmaz).

    Neden select() degil: select() cold-start gununun (belki ince) ciktisini verir;
    F'in TASIDIGI sepet ise onceki rebalanstan gelir. Shadow "F'i aynalamak" istiyorsa
    F'in pozisyonlarini okumali, o gunun select()'ini degil.

    Acik 'cold_start_reconcile' history kaydi birakir (gizli reconcile = sessiz
    look-ahead kadar kotu). (state, events) doner; step() ile ayni events formati."""
    _ensure(state)
    friction = config.COMMISSION / 2 + slippage
    events = {"buys": [], "sells": [], "reentries": []}

    # G1 toplam sermayesi (mevcut dejenere tohum dahil, bugunku fiyattan)
    total = float(state["cash"])
    for tic, pos in state["positions"].items():
        total += float(pos["shares"] * float(_py(prices_today.get(tic, pos["entry"]))))

    # F'in mevcut yatirim degeri + goreli piyasa-degeri agirliklari (BUGUNKU fiyat)
    ref_pos = ref_state.get("positions", {})
    ref_cash = float(ref_state.get("cash", 0.0))
    ref_val = {}
    for tic, pos in ref_pos.items():
        p = prices_today.get(tic)
        if p is None or float(_py(p)) <= 0:
            continue
        ref_val[str(tic)] = float(pos["shares"]) * float(_py(p))
    ref_invested = sum(ref_val.values())
    ref_total = ref_cash + ref_invested
    invested_frac = (ref_invested / ref_total) if ref_total > 0 else 0.0

    # mevcut (dejenere) tohumu bugunku fiyattan tasfiye et — izi trades'e dusur
    for tic, pos in list(state["positions"].items()):
        p = float(_py(prices_today.get(tic, pos["entry"])))
        pnl = float((p / pos["entry"] - 1) * 100)
        state["cash"] = float(state["cash"] + pos["shares"] * p * (1 - friction))
        del state["positions"][tic]
        _log(state, date, "SELL", tic, p, reason="cold_start_reconcile", pnl_pct=round(pnl, 2))
        events["sells"].append({"ticker": str(tic), "price": round(_py(p), 2),
                                "reason": "cold_start_reconcile", "pnl_pct": round(_py(pnl), 2)})

    # F'in yatirim-orani kadarini, F'in goreli agirliklariyla, BUGUNKU fiyattan yerlestir
    deploy = total * invested_frac
    mirrored = []
    if ref_invested > 0 and deploy > 0:
        for tic, mv in ref_val.items():
            ep = float(_py(prices_today.get(tic)))
            if ep <= 0:
                continue
            w = mv / ref_invested
            alloc = float(deploy * w * (1 - friction))
            state["positions"][tic] = {"entry": ep, "peak": ep,
                                       "shares": float(alloc / ep), "w": float(w)}
            state["cash"] = float(state["cash"] - alloc)
            state["stats"]["buys"] += 1
            _log(state, date, "BUY", tic, ep, reason="cold_start_reconcile", weight=round(w, 3))
            events["buys"].append({"ticker": str(tic), "price": round(_py(ep), 2)})
            mirrored.append(str(tic))

    state["history"].append({
        "type": "cold_start_reconcile",
        "date": str(date.date()) if hasattr(date, "date") else str(date),
        "reason": reason or "gec-katilim cold-start, F'e senkron (bugunku fiyat, F entry gecmisi KOPYALANMADI)",
        "mirrored": mirrored,
        "invested_frac": round(invested_frac, 4),
        "total": round(float(total), 4),
        "n_pos": len(state["positions"]),
    })
    if len(state["history"]) > _HISTORY_CAP:
        state["history"] = state["history"][-_HISTORY_CAP:]
    return state, events


def step(data, signals, state, date, prices_today, is_rebal, slippage=0.0,
         eval_stops=False):
    """G1 gunluk adim. state yerinde guncellenir. (state, events) doner.

    eval_stops: stop degerlendirilsin mi. YALNIZ kapanis kosusunda True olmali
      (cagiran: shadow.step -> run_label == "kapanis"). Bkz #0l.
      Varsayilan False = F tarafiyla SIMETRIK muhafazakar secim
      (shadow.step'te de run_label=None -> stop yok). Tek cagri yeri var
      (shadow.py) ve o acikca geciriyor.
    """
    friction = config.COMMISSION / 2 + slippage
    _ensure(state)
    events = {"buys": [], "sells": [], "reentries": []}

    # 1) STOP (+ watch). Re-entry pozisyonu tekrar stop olursa yanlis-kirilim say.
    #
    # #0l KAPSAM GENISLEMESI (2026-07-30, Faz-5 bulgusu): F'i kapanis-only yapip
    # G1'i her-kosu birakmak, G1 kiyasini BOZARDI — kiyas "stop sonrasi hemen gir
    # (G1) vs rebalansi bekle (F)" hipotezini olcuyor; iki kol farkli stop
    # semantiginde olursa olculen sey hipotez degil SEMANTIK FARK olur.
    # Bu blok F'teki portfolio.check_stops'un IKIZI ama BIREBIR DEGIL:
    # stop_level ortak (pf.stop_level), peak-circiri ayni; ama F'teki
    # "peak yoksa entry'den doldur" korumasi burada YOK ve burada re-entry
    # muhasebesi (origin/yanlis-kirilim) FAZLADAN var -> ayri kuru-kosu sart.
    # NOT: (2) YENIDEN-GIRIS bilincli olarak KAPILANMADI — o bir GIRIS/fill
    # karari ve #0i'nin (fill konvansiyonu) alanina girer; #0i, F'in rebalansi
    # kadar G1'in re-entry'sini de kapsamalidir.
    if eval_stops:
        for tic, pos in list(state["positions"].items()):
            pt = prices_today.get(tic)
            if pt is None:
                continue
            pt = float(_py(pt))
            if pt > pos["peak"]:
                pos["peak"] = float(pt)
            if pt < pf.stop_level(pos):
                pnl = float((pt / pos["entry"] - 1) * 100)
                giveback = float((pos["peak"] - pt) / pos["peak"] * 100)
                state["cash"] = float(state["cash"] + pos["shares"] * pt * (1 - friction))
                is_re = pos.get("origin") == "reentry"
                if is_re:
                    _close_reentry(state, pnl, "stop")
                state["watch"][tic] = {"exit": float(pt), "cash": float(pos["shares"] * pt * (1 - friction)),
                                       "w": float(pos.get("w", 1.0))}
                del state["positions"][tic]
                state["stats"]["stops"] += 1
                _log(state, date, "SELL", tic, pt, reason="stop", pnl_pct=round(pnl, 2),
                     giveback=round(giveback, 2), was_reentry=is_re)
                events["sells"].append({"ticker": str(tic), "price": round(_py(pt), 2), "reason": "stop",
                                        "pnl_pct": round(_py(pnl), 2), "was_reentry": bool(is_re)})

    # 2) YENIDEN-GIRIS (cikis ustune kapanis). origin=reentry.
    #    ROLLING THROTTLE: son re-entry'ler kume halinde basarisizsa lot kis / dur (mitigator).
    rec = state.get("reentry_recent", [])
    roll = (sum(rec) / len(rec)) if len(rec) >= 4 else 0.0
    re_factor = 0.0 if roll > RE_PAUSE_RATE else (RE_THROTTLE_FACTOR if roll > RE_THROTTLE_RATE else 1.0)
    for tic, w in list(state["watch"].items()):
        if tic in state["positions"]:
            state["watch"].pop(tic, None); continue
        pt = prices_today.get(tic)
        if pt is None:
            continue
        pt = float(_py(pt))
        if pt > w["exit"] and re_factor == 0.0:
            state["stats"]["reentry_paused"] += 1
            continue
        if pt > w["exit"] and state["cash"] >= w["cash"] * 0.4 * re_factor:
            spend = float(min(w["cash"], state["cash"]) * re_factor)
            state["positions"][tic] = {"entry": float(pt), "peak": float(pt),
                                       "shares": float(spend * (1 - friction) / pt),
                                       "w": float(w["w"]), "origin": "reentry"}
            state["cash"] = float(state["cash"] - spend)
            state["watch"].pop(tic, None)
            state["stats"]["reentries"] += 1
            if re_factor < 1.0:
                state["stats"]["reentry_throttled"] += 1
            _log(state, date, "REENTRY", tic, pt, prev_exit=round(w["exit"], 2),
                 throttle=(round(re_factor, 2) if re_factor < 1.0 else None))
            events["reentries"].append({"ticker": str(tic), "price": round(_py(pt), 2),
                                        "throttle": (round(re_factor, 2) if re_factor < 1.0 else None)})

    # 3) REBALANCE (F secimi; watch sifirla). Rebalance satislari da events'e (FIX 3).
    if is_rebal:
        state["watch"].clear()
        total = float(state["cash"])
        for tic, pos in state["positions"].items():
            total += float(pos["shares"] * prices_today.get(tic, pos["entry"]))
        for tic, pos in list(state["positions"].items()):
            p = float(_py(prices_today.get(tic, pos["entry"])))
            pnl = float((p / pos["entry"] - 1) * 100)
            state["cash"] = float(state["cash"] + pos["shares"] * p * (1 - friction))
            if pos.get("origin") == "reentry":
                _close_reentry(state, pnl, "rebalance")
            _log(state, date, "SELL", tic, p, reason="rebalance", pnl_pct=round(pnl, 2))
            events["sells"].append({"ticker": str(tic), "price": round(_py(p), 2),
                                    "reason": "rebalance", "pnl_pct": round(_py(pnl), 2),
                                    "was_reentry": bool(pos.get("origin") == "reentry")})
        state["positions"] = {}
        picks, sig_map, _ = strat_mod.select(data, signals, date, mode="F")
        weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
        scale = strat_mod.regime_scale(data, date) if hasattr(strat_mod, "regime_scale") else 1.0
        if scale != 1.0:
            weights = {t: w * scale for t, w in weights.items()}
        tw = sum(weights.values())
        if tw > 0:
            for tic, w in weights.items():
                ep = prices_today.get(tic)
                if ep and ep > 0:
                    ep = float(_py(ep))
                    w = float(_py(w))
                    alloc = float(total * (w / tw) * (1 - friction))
                    state["positions"][tic] = {"entry": float(ep), "peak": float(ep), "shares": float(alloc / ep), "w": float(w)}
                    state["cash"] = float(state["cash"] - alloc)
                    state["stats"]["buys"] += 1
                    _log(state, date, "BUY", tic, ep, weight=round(w, 2))
                    events["buys"].append({"ticker": str(tic), "price": round(_py(ep), 2)})
        state["history"].append({"date": str(date.date()) if hasattr(date, "date") else str(date),
                                 "total": round(float(total), 4), "n_pos": len(state["positions"])})
        if len(state["history"]) > _HISTORY_CAP:
            state["history"] = state["history"][-_HISTORY_CAP:]

    # 4) GUNLUK DEGER + ARTIMLI DD — rebalance'a degil HER gune dayali (native float, JSON guvenli)
    st = state["stats"]
    valf = float(_value(state, prices_today))
    if st.get("peak_value") is None:
        st["peak_value"] = valf
    st["peak_value"] = float(max(st["peak_value"], valf))
    dd = (valf - st["peak_value"]) / st["peak_value"] * 100 if st["peak_value"] else 0.0
    st["max_dd_pct"] = float(min(st.get("max_dd_pct", 0.0), dd))
    state["equity_daily"].append(round(valf, 4))
    if len(state["equity_daily"]) > _EQUITY_CAP:
        state["equity_daily"] = state["equity_daily"][-_EQUITY_CAP:]

    return state, events


def summary(state, prices_today, f_return_pct=None):
    """Dashboard/karar ozeti. max_dd_pct artik GUNLUK izlenen (FIX 1)."""
    _ensure(state)
    val = float(_value(state, prices_today))
    st = state["stats"]
    re = st["reentries"]
    fb_rate = float(st["reentry_restops"] / re * 100) if re else None
    fb_loss = float(st["reentry_restop_loss"] / re * 100) if re else None
    # FIX 4: yanlis-kirilim baz cizgiyi asarsa drawdown_watch otomatik tetiklenir
    watch_triggered = bool(re >= FB_MIN_SAMPLE and fb_rate is not None and fb_rate > BASELINE_FB_RATE)
    rec_s = state.get("reentry_recent", [])
    roll_s = (sum(rec_s) / len(rec_s)) if len(rec_s) >= 4 else 0.0
    throttle_state = "paused" if roll_s > RE_PAUSE_RATE else ("throttled" if roll_s > RE_THROTTLE_RATE else "normal")
    closed = st.get("reentry_closed", 0)
    re_win_rate = (st.get("reentry_wins", 0) / closed * 100) if closed else None
    re_total = st.get("reentry_total_pnl_pct", 0.0)
    re_avg = (re_total / closed) if closed else None
    dd_now = round(float(st.get("max_dd_pct", 0.0)), 2)
    ret_pct = round((val - 1) * 100, 2)
    vs_f = round(float(ret_pct - f_return_pct), 2) if f_return_pct is not None else None
    promo = {
        "beats_f": bool(vs_f > 0) if vs_f is not None else None,
        "dd_ok": bool(dd_now > PROMO_MAX_DD),
        "fb_rate_ok": bool((fb_rate is None) or (fb_rate <= PROMO_FB_RATE)),
        "fb_loss_ok": bool((fb_loss is None) or (fb_loss <= PROMO_FB_LOSS)),
    }
    promo["all_pass"] = bool(promo["beats_f"] and promo["dd_ok"]
                             and promo["fb_rate_ok"] and promo["fb_loss_ok"])
    # Dashboard yerlesimi (Analiz): 3 ana sinyal one cikar, gerisi alt detay
    display = {
        "primary": [
            {"key": "g1_vs_f_return_pct", "label": "G1/F getiri farki",
             "value": vs_f, "unit": "%"},
            {"key": "max_dd_pct", "label": "Max DD (gunluk)", "value": dd_now, "unit": "%"},
            {"key": "false_breakout_rate_pct", "label": "Yanlis-kirilim orani",
             "value": round(fb_rate, 1) if fb_rate is not None else None,
             "unit": "%", "baseline": BASELINE_FB_RATE},
        ],
        "secondary": [
            {"key": "reentry_avg_pnl_pct", "label": "Re-entry ort PnL",
             "value": round(re_avg, 2) if re_avg is not None else None, "unit": "%"},
            {"key": "reentry_win_rate", "label": "Re-entry win%",
             "value": round(re_win_rate, 1) if re_win_rate is not None else None, "unit": "%"},
            {"key": "reentry_rebalance_loss_count", "label": "Rebalance-zarar adedi",
             "value": st.get("reentry_rebalance_loss_count", 0), "unit": ""},
        ],
        "notes": {
            "reentry_total_pnl_pct": "cohort toplami (islem-bazli pnl% toplami) - PORTFOY KATKISI DEGIL",
        },
    }
    return {
        "account": "G1", "role": state["role"], "labels": state["labels"],
        "value": round(val, 4), "return_pct": round((val - 1) * 100, 2),
        "max_dd_pct": round(st.get("max_dd_pct", 0.0), 2),
        "n_positions": len(state["positions"]), "n_watch": len(state["watch"]),
        "buys": st["buys"], "stops": st["stops"], "reentries": re,
        "reentry_restops": st["reentry_restops"],
        "false_breakout_rate_pct": round(fb_rate, 1) if fb_rate is not None else None,
        "false_breakout_loss_rate_pct": round(fb_loss, 1) if fb_loss is not None else None,
        "baseline_fb_rate_pct": BASELINE_FB_RATE,
        "reentry_closed": closed,
        "reentry_total_pnl_pct": round(re_total, 2),
        "reentry_avg_pnl_pct": round(re_avg, 2) if re_avg is not None else None,
        "reentry_win_rate": round(re_win_rate, 1) if re_win_rate is not None else None,
        "reentry_rebalance_loss_count": st.get("reentry_rebalance_loss_count", 0),
        "g1_vs_f_return_pct": vs_f,
        "promotion_gates": promo,
        "display": display,
        "watch_triggered": watch_triggered,
        "status": "drawdown_watch_AKTIF" if watch_triggered else "izlemede",
        "throttle_state": throttle_state,
        "reentry_recent_fail_rate_pct": round(roll_s * 100, 1),
        "reentry_throttled": st.get("reentry_throttled", 0),
        "reentry_paused": st.get("reentry_paused", 0),
    }
