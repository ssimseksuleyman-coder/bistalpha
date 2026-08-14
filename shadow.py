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
    """Gerçekleşen shadow işlemleri + CORPORATE-ACTION düzeltmeleri için bildirim.

    #0k GORUNURLUK (2026-08-06): CA duzeltmesi ISLEM URETMEZ (entry/peak yerinde
    degisir) -> eski surumde `if not trades: continue` onu YAPISAL olarak
    eliyordu. Sonuc: dedektor ilk gercek CA'da dogru calissa bile bildirim
    kanalinda GORUNMEZ; kanit yalniz ham state'te (entry_original/ca_ratio) ve
    Actions log'unda kalirdi. "Olan ama duyurulmayan olayin da imzasi yok" —
    "yoklugun imzasi yok" yasasinin simetrigi. `#0k`'yi "wire edildi"den
    "calisti"ya tasiyan teyit bu kanaldan gecer.

    F ve G1 SIMETRIK: G1 de `results["G1"]` ile accounts'a giriyor -> tek dongu
    ikisini de kapsar, ayri kol GEREKMEZ.

    TETIKLEYICI YALNIZ `ca_fixed` — `ca_unchecked` DEGIL (bilincli): "kontrol
    edilemedi" KALICI bir durum olabilir (ornegin giris tarihi feed penceresi
    disinda -> her kosuda tekrarlar) -> tetikleyici yapilirsa HER GUN mesaj =
    yeni gurultu kaynagi. Bu oturum sahte-sari gurultusunden bir kez yandi
    (#3-EK). Unchecked yalniz ZATEN mesaj yazilirken EK BILGI olarak eklenir.
    """
    lines = []
    for acc, info in result.get("accounts", {}).items():
        event = info.get("last_event") or {}
        trades = info.get("new_trades") or []
        ca_fixed = info.get("ca_fixed") or []
        if not trades and not ca_fixed:
            continue
        # Baslik etiketi: islem YOKKEN "islem" yazmak yanlis okunur — ilk gercek
        # CA mesaji tam da o an okunacak, etiket dogru olmali.
        etiket = event.get("event", "islem") if trades else "corporate-action"
        lines.append(f"Hesap {acc} | {etiket} | değer {info.get('value')} | pozisyon {info.get('n_pos')}")
        for ca in ca_fixed[:6]:
            e, p = (ca.get("entry") or [None, None]), (ca.get("peak") or [None, None])
            lines.append(
                f"  ⚠ CORPORATE-ACTION DÜZELTME {ca.get('ticker')} oran={ca.get('ratio')}"
                f" | entry {e[0]}→{e[1]} | peak {p[0]}→{p[1]} (giriş {ca.get('entry_date')})")
        if len(ca_fixed) > 6:
            lines.append(f"  ... {len(ca_fixed) - 6} CA düzeltmesi daha")
        # "kontrol edilemedi" YALNIZ burada (zaten mesaj yaziliyor) — tek basina
        # mesaj TETIKLEMEZ. "temiz" ile "kontrol EDILEMEDI" ayri kalir.
        cu = info.get("ca_unchecked") or []
        if ca_fixed and cu:
            ozet = ", ".join(f"{x.get('ticker')}({x.get('reason')})" for x in cu[:4])
            lines.append(f"  (CA kontrol edilemedi: {len(cu)} — {ozet})")
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


# IZLEME ARTEFAKT DIZINI — kuru-kosuda YONLENDIRILEBILIR olmali (2026-08-01).
#
# NEDEN: `portfolio.save(state_dir=...)` override edilebiliyor, bu yuzden kuru
# kosular gercek `portfolios/`'u kirletmiyor. Ama `_write_stop_eval` sabit gercek
# yolu kullaniyordu -> `run_label="kapanis"` ile kosan HER kuru-kosu gercek
# `docs/state/stop_eval.json`'i TAZELIYORDU. Sonuc kozmetik degil: liveness'in
# 14. uyesi (close_only) o damgayi okur ve "stop degerlendirildi" sanar =>
# SAHTE YESIL. Yani test, izlemenin gordugunu bozuyordu.
# Ayni sinifin tersi: #0l'de "kosmadigini fark etmiyoruz" idi; burada
# "kosmadigi halde kostu saniyoruz".
# NOT: config.STATE_DIR ("portfolios") AYRI dizin — docs/state yayinlanan
# artefakt yeri; bu yuzden kendi sabiti gerekiyor, STATE_DIR yeniden kullanilamaz.
DOCS_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "state")


# #0i-② — pending OMRU: D+1'de doldurulamazsa (backstop/veri) D+2 tekrar dener;
# daha bayat picks ile DOLDURMA -> iptal + gorunur log, sayac sifirlanmadigi icin
# sonraki dongu TAZE yeniden karar verir.
PENDING_MAX_AGE_DAYS = 2


# ── #0e-GUARD — INCE-SECIM ERTELEME (2026-08-07, olcumle tasarlandi) ─────────
#
# SORUN: tatil deligi (#0e) karar gununu ZEHIRLER. `strategy.score()` yalniz
# idx / idx-5 / idx-30 / idx-252 barlarini okur; birinde delik varsa TUM evren
# gecersiz olur. OLCULDU (2026-08-07, fiyat matrisinden): 2026-07-22 bar-dolu
# 612/614 (TAM GUN) ama valid=3 -> `idx-5` = 07-15 tatili. Yani KAPANIS kosusu
# tam bar okusa DA cop secim yapardi; "kapanis yapisal temiz" hipotezi CURUDU.
#
# TETIKLEYICI: `len(picks)` — `valid` DEGIL. Bu FARK OLCULDU (10y Yahoo, gercek
# delikler, +30g ileri getiri, olay-calismasi):
#   AGIR  (secilen <=3 isim; 4 olayda da TEK isim): cop +1.49% / ertele +12.94%
#         -> ertele +11.45pp, 4/4 tutarli
#   HAFIF (secilen 8-10 isim):                      cop +10.19% / ertele -1.14%
#         -> ertele -11.33pp, yani ERTELE ZARAR VERIYOR
# `valid < esik` tetikleyicisi HAFIF vakalari da yakalar ve F'e ZARAR verirdi.
# Zarar mekanizmasi valid sayisi degil KONSANTRASYON (portfoy tek hisseye
# cokuyor) -> tetikleyici CIKTIDA olmali, girdide degil.
# Esik guvenli: gozlemde AGIR=1 isim, HAFIF=8-10 -> arada genis bosluk.
# SINIR: AGIR n=4 (yon guclu 4/4 ama ornek ince), 10y-Yahoo evreni
# (golden-master datapath'i DEGIL), getiri modeli basit (+30g esit-agirlik,
# stop modellenmedi). Yon icin yeterli, kesinlik icin degil.
THIN_PICKS_MAX = 3

# ⚠️ "3 GUN SONRA ATLA" BILINCLI OLARAK YAZILMADI — gerekce:
# Ertelemenin maliyeti PORTFOYUN BAYATLAMASI (stoplar calismaya devam eder,
# konsantrasyon riski YOK). Ince-rebalansi kabul etmenin maliyeti OLCULDU:
# -11.45pp ve tek-hisse konsantrasyonu. Yani "N gun sonra zorla kabul et"
# emniyet supabi, korudugundan DAHA BUYUK bir riski geri getirir.
# Ayrica ertelemek saati DONDURMUYOR: history'ye olay yazilmadigi icin
# `_last_selection_date` eskide kalir -> `rebal_elapsed` BUYUMEYE devam eder
# -> ertesi kapanista otomatik yeniden denenir (sonsuz bekleme degil, gunluk
# yeniden deneme). Gozlenen en uzun ardisik zehirli seri = 2 GUN.
# Bunun yerine: ERTELEME SAYACI gorunur yapilir ve esigi asinca RAPORDA
# yukselir (izleme meselesi, ticaret kurali degil). Zorla-kabul isteniyorsa
# AYRI ve BILINCLI bir karar olmali.
THIN_DEFER_LOUD_AFTER = 3


# ── #0i-5 — FILL KONVANSIYON DAMGASI ────────────────────────────────────────
#
# NEDEN (kayit `#0i` madde 5, tarihli: "2. rebalanstan ONCE bit"): C1'in 5
# penceresi TEK konvansiyonla olculmeli; olculmezse degil, KARISTIRILMAMALI.
# Iki konvansiyon fiilen var:
#   07-17 rebalansi  -> karar ve fill AYNI gun kapanisinda (#0b olctu: DSTKF
#                       2522 kitaplandi, gercek yurutme 07-20'de 2271 olurdu
#                       = %10 fark)
#   #0i sonrasi      -> karar D kapanisi, fill D+1 ACILISI (`opens_today`)
# Damga olmazsa ileride iki pencere farkinda olmadan kiyaslanir — bugun `#0q`da
# birebir bu yasandi (belgelenmemis state sonradan yanlis okundu).
#
# NEREYE: history KAYDININ ICINE -> pencere verisiyle birlikte seyahat eder.
# NEDEN BURADA (shadow.py), portfolio.py'de DEGIL: konvansiyonu shadow SECIYOR
# (`pf.rebalance`e `opens_today` mi `prices_today` mi gectigi), portfolio.py
# kendisine verilen seriye doldurur — konvansiyon-agnostiktir. Dolayisiyla
# damga da burada durur ve **F-datapath'in 5 dosyasi HIC DEGISMEZ** (golden-
# master SHA-katiligi korunur; "davranis degismiyor" yargisina bel baglamaya
# gerek kalmaz).
FILL_CONV_NEXT_OPEN = "next_open_deferred"   # #0i: karar D kapanis, fill D+1 open
FILL_CONV_SAME_DAY = "same_day_close"        # #0i oncesi + TUM stop'lar (prices_today)


def _stamp_fill_convention(state):
    """Alani OLMAYAN her history kaydina `same_day_close` yazar (idempotent).

    Zaten damgali kayda DOKUNMAZ -> fill yerinde vurulan `next_open_deferred`
    ezilmez, ve yeniden kosum sonucu degistirmez.
    `same_day_close` dogru varsayilan: (a) #0i oncesi tum fill'ler oyleydi,
    (b) stop'lar `close_positions(..., prices_today)` ile HALA ayni-gun doluyor
    (#0i stop yolunu degistirmedi).
    """
    n = 0
    for h in state.get("history") or []:
        if isinstance(h, dict) and "fill_convention" not in h:
            h["fill_convention"] = FILL_CONV_SAME_DAY
            n += 1
    return n


# ── #0k — CORPORATE-ACTION (bedelsiz/bolunme) TESPITI + ATOMIK DUZELTME ──────
#
# MEKANIZMA (2026-07-31 olculdu, YEOTK canli vakasi): Yahoo bolunme/bedelsizde
# TUM GECMISI geriye donuk boler (`auto_adjust=False` bunu ENGELLEMEZ — o yalniz
# temettu duzeltmesini kontrol eder). Seride KOPUKLUK OLUSMAZ, bu yuzden
# "limit-asan hareket" imzasi bu vakayi YAKALAYAMAZ. Phantom-stop seriden degil
# STATE<->FEED UYUMSUZLUGUNDAN dogar: state.entry alim gunundeki HAM fiyatta
# DONUK kalir, feed ise geriye donuk bolunur -> F duzeltilmemis peak'i
# duzeltilmis fiyatla kiyaslar -> %57 cokus gorur -> phantom stop.
#
# DEDEKTOR: state.entry / feed[giris_tarihi]. Esik-tabanli DEGIL, oran-tabanli.
# OLCUM (2026-08-05, 92 gozlem): temiz vakalar oran = 1.000000 (12/12 acik
# pozisyon + 80/80 gecmis alim, 1e-6 ustu sapma SIFIR); YEOTK bedelsiz orani
# 2.338 -> marj ~134x. Bu yuzden tolerans %1 fazlasiyla guvenli.
# NOT: onceki bir olcumde %4.3 sapma gorulmustu — onlar SATIS (stop) kayitlariydi,
# yani #0l'in duzelttigi gun-ici kitaplama artefakti; GIRIS fiyatlari temiz.
CA_RATIO_TOL = 0.01


def _entry_dates(state, acc):
    """Pozisyonlarin GIRIS TARIHI — kaynak HESABA GORE FARKLI (G1 F'in ikizi DEGIL).

    F/A/B/O : history[].trades  (pf.rebalance/close_positions trade listesi yazar)
    G1      : trades[]          (g1 history'si {date,total,n_pos} tutar, ticker YOK;
                                 giris izi _log -> state["trades"]'te, ve G1'de
                                 REENTRY de bir giristir)
    """
    out = {}
    if acc == "G1":
        for t in (state.get("trades") or []):
            if t.get("type") in ("BUY", "REENTRY") and t.get("ticker"):
                out[str(t["ticker"])] = t.get("date")
    else:
        for e in (state.get("history") or []):
            for t in (e.get("trades") or []):
                if t.get("type") != "SELL" and t.get("ticker"):
                    out[str(t["ticker"])] = e.get("date")
    return out


def _ca_detect_and_fix(state, acc, prices, trade_date):
    """Geriye donuk duzeltme tespit et; bulursa entry VE peak'i ATOMIK duzelt.

    ATOMIKLIK KRITIK: yalniz entry bolunurse peak eski (bolunmemis) yuksek
    fiyatta kalir -> stop seviyesi (peak-tabanli trailing) SACMALAR.
    Ornek: OZATD entry=2695 peak=3770 — CA olsa IKISI de bolunmeli.

    "KONTROL EDILEMEDI" != "TEMIZ" (yok != kirik != yanlis-olculen'in dedektor
    hali): sebebi AYRI AYRI raporlanir, sessizce atlanmaz.

    Returns: (fixed:list, unchecked:list, checked:dict)

    `checked` = POZITIF DAMGA (#0k artigi, 2026-08-06): `ca_fixed: null` IKI
    ANLAMA geliyordu — "kostu, temiz" ve "HIC KOSMADI" (gun-ici kosuda dedektor
    calismaz; ya da hesap dongusu CA'dan once patlarsa). Ucu de ayni gorunuyordu.
    `stop_eval.json` bunu KAPATMIYOR: o dongunun DISINDA yazilir (satir ~623), yani
    bir hesap CA'ya varmadan patlasa bile damga tazelenir -> okuyan "CA bakildi"
    sanar. Bu yuzden damga HESAP BASINA ve dedektorun KENDI icinden uretilir.
    Sinif: "sinyal yoklugu != sorun yoklugu" (bkz #4-EK, ayni gun runner kesintisi).
    YALNIZ IZ, KARAR DEGIL — hicbir kod buna bakip farkli davranmaz (stop_eval kurali).
    """
    ed = _entry_dates(state, acc)
    fixed, unchecked = [], []
    for tic, pos in list((state.get("positions") or {}).items()):
        d = ed.get(tic)
        if not d:
            unchecked.append((tic, "giris_tarihi_yok")); continue
        try:
            k = pd.Timestamp(d)
        except Exception:
            unchecked.append((tic, "tarih_parse_edilemedi")); continue
        if tic not in prices.columns:
            unchecked.append((tic, "ticker_feedde_yok")); continue
        if k not in prices.index:
            # feed penceresi 2 yil (YahooFeed period="2y") -> daha eski giris
            unchecked.append((tic, "tarih_feed_penceresi_disinda")); continue
        f = prices.loc[k, tic]
        if pd.isna(f) or float(f) <= 0:
            unchecked.append((tic, "feed_fiyati_bos")); continue
        e = float(pos.get("entry") or 0)
        if e <= 0:
            unchecked.append((tic, "entry_gecersiz")); continue
        ratio = e / float(f)
        if abs(ratio - 1.0) <= CA_RATIO_TOL:
            continue                      # TEMIZ — dokunma
        # --- CORPORATE ACTION: ATOMIK duzeltme (entry VE peak ayni oranla) ---
        old_e = e
        old_p = float(pos.get("peak") or e)
        pos["entry"] = old_e / ratio
        pos["peak"] = old_p / ratio
        # GERI ALINABILIR + DENETLENEBILIR: eski degerler saklanir, sessiz degisim YOK
        pos["entry_original"] = old_e
        pos["peak_original"] = old_p
        pos["ca_ratio"] = ratio
        pos["ca_adjusted_at"] = trade_date
        fixed.append({"ticker": tic, "ratio": round(ratio, 6),
                      "entry": [round(old_e, 4), round(pos["entry"], 4)],
                      "peak": [round(old_p, 4), round(pos["peak"], 4)],
                      "entry_date": str(d)})
        print(f"[shadow] {acc} CORPORATE-ACTION duzeltmesi: {tic} oran={ratio:.4f} "
              f"entry {old_e:.2f}->{pos['entry']:.2f} peak {old_p:.2f}->{pos['peak']:.2f} "
              f"(giris {d})")
    n_pos = len(state.get("positions") or {})
    checked = {"n_positions": n_pos, "n_fixed": len(fixed),
               "n_unchecked": len(unchecked),
               "n_clean": n_pos - len(fixed) - len(unchecked)}
    return fixed, unchecked, checked


def _thin_defer(state, acc, picks, trade_date):
    """picks INCE ise ertele. True donerse KARAR VERILMEZ (pending yazilmaz).

    Sayac state'te tutulur (`_rebal_defer`) -> ardisik erteleme GORUNUR olur.
    Saat DONMAZ: history'ye olay yazilmadigi icin rebal_elapsed buyumeye devam
    eder ve ertesi kapanista otomatik yeniden denenir.
    """
    if len(picks) > THIN_PICKS_MAX:
        if state.pop("_rebal_defer", None):
            print(f"[shadow] {acc} ince-secim BITTI ({len(picks)} pick) -> karar verilebilir")
        return False
    dfr = state.get("_rebal_defer") or {"count": 0, "first_at": trade_date}
    dfr["count"] = int(dfr.get("count", 0)) + 1
    dfr["last_at"] = trade_date
    dfr["n_picks"] = len(picks)
    state["_rebal_defer"] = dfr
    yuksek = " ** ARDISIK %d GUN — VERI SORUNU SURUYOR **" % dfr["count"]         if dfr["count"] >= THIN_DEFER_LOUD_AFTER else ""
    print(f"[shadow] {acc} INCE-SECIM ({len(picks)} pick <= {THIN_PICKS_MAX}) "
          f"-> rebalans ERTELENDI, sayac={dfr['count']}{yuksek}")
    return True


def _pending_age_days(decided_at, today):
    """Karar tarihinden bugune TAKVIM gunu. Parse edilemezse None (iptal etme)."""
    try:
        d0 = pd.Timestamp(str(decided_at)).normalize()
        d1 = pd.Timestamp(str(today)).normalize()
        return int((d1 - d0).days)
    except Exception:
        return None


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
    # #0i: FILL FIYATI = o barin OPEN'i (kapanis DEGIL). Bar TAM oldugu icin
    # (kapanis kosusu 18:40 TR, BIST 18:00'de kapandi) open KESIN ve revize
    # olmaz. DIKKAT: "tam barin open ALANI" != "acilis KOSUSUNUN bayat bari".
    opens = data.get('opens')
    opens_today = (opens.loc[date].dropna().to_dict()
                   if opens is not None and date in opens.index else {})

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
            #
            # ⚠️ SIRA (#0i-①, 2026-08-01): bu blok FILL'DEN SONRA calisir.
            #    Onceki hali fill'den ONCE calisiyordu ve tasarimla CELISIYORDU:
            #    rebalans TAM DEVIR (portfolio.rebalance: "tumunu sat" -> positions={}
            #    -> hedefi al; delta DEGIL, kodla dogrulandi) => fill gununde eski
            #    pozisyonlari REBALANS cikarir, ayri on-stop GEREKSIZ. Dahasi
            #    zamansal olarak IMKANSIZDI: on-stop D+1 CLOSE'dan satar (18:00),
            #    rebalans ayni gun D+1 OPEN'dan alir (10:00).
            #    Yeni sira: CA-DUZELTME -> FILL (varsa) -> STOP -> KARAR.
            sells, stop_trades, new_trades = [], [], []
            # 0) #0k — CORPORATE-ACTION duzeltmesi, STOP'tan ONCE.
            # Neden once: geriye donuk bolunme entry/peak'i feed'le uyumsuz
            # birakir; duzeltilmeden stop'a girilirse phantom-stop DOGAR.
            # Fill'den de once: fill bloklanirsa mevcut pozisyonlar tasinir ve
            # yine duzeltilmis olmalari gerekir.
            # ca_checked=None -> "bu kosuda BAKILMADI" (gun-ici kosu). Dolu ->
            # "bakildi", sayilarla. `ca_fixed: null`in iki-anlamliligi boylece biter.
            ca_fixed, ca_unchecked, ca_checked = ([], [], None)
            if run_label == "kapanis":
                ca_fixed, ca_unchecked, ca_checked = _ca_detect_and_fix(state, acc, prices, trade_date)
            # #0i FAZ-5 (2026-08-01): "rebalance" bayragi ARTIK ICRA demek.
            # BULGU: eskiden `rebalance = should_rebalance` idi. Karar/icra ayrilinca
            # bu bayrak TERS bilgi vermeye basladi:
            #   karar gunu -> True  ama 0 islem, 0 pozisyon degisimi
            #   fill  gunu -> False ama 10 pozisyon ALINDI (cunku fill sayaci
            #                 sifirladi, should_rebalance artik False)
            # Yani "10 pozisyon alindi" gunu bayrak False diyordu = yanlis okuma.
            # COZUM: iki anlami AYIR — `rebalance` = ICRA EDILDI (fill bu kosuda
            # kitaplandi), `rebalance_decided` = KARAR VERILDI (pending yazildi).
            # Asagi-akis tuketiciler (dashboard/any_rebal) "islem oldu mu" bekler.
            filled_now = False
            decided_now = False
            # 2) KARAR/ICRA AYRIMI (#0i) — karar D-kapanista, ICRA D+1 OPEN'dan.
            #
            # ESKI: karar ve fill AYNI ani (prices_today = karar-kosusu kapanisi)
            #       -> shadow, gercekte erisilemeyen bir fiyattan kitapliyordu
            #       (karar 18:40'ta verilir, o gunun kapanisindan alim IMKANSIZ).
            # YENI: D kapanis -> _pending_rebalance (fill YOK)
            #       D+1 kapanis -> pending'i D+1 OPEN fiyatindan doldur.
            #       Ekonomik an: karar 18:00, icra ertesi 10:00 = gercek davranis.
            #
            # SIRA (#0i-①, 2026-08-01 duzeltmesi): fill gununde FILL -> STOP.
            #   fill  = D+1 open  (10:00) | stop = D+1 close (18:00)
            #   stop->fill olsaydi "18:00'da sat, ayni gun 10:00'da al" = imkansiz.
            #   Fill olmayan gunlerde degisiklik yok (yalniz stop, yukarida).
            # NOT: rebalans TAM DEVIR -> fill gununde eski pozisyonlar rebalansla
            #      cikar; ayri stop gereksiz.
            pending = state.get("_pending_rebalance")
            if run_label == "kapanis" and pending and pending.get("status") == "pending":
                age = _pending_age_days(pending.get("decided_at"), trade_date)
                if age is not None and age > PENDING_MAX_AGE_DAYS:
                    # OMUR ASIMI (#0i-②): 2 gunden bayat picks ile doldurma.
                    state.pop("_pending_rebalance", None)
                    print(f"[shadow] {acc} pending IPTAL (yas={age}g > {PENDING_MAX_AGE_DAYS}g) "
                          f"decided_at={pending.get('decided_at')}")
                else:
                    # ── KAPSAMA KONTROLU (2026-08-01, kuru-kosu bulgusu) ──────────
                    # BULGU: hedef ticker'in D+1 open'i yoksa, eski kod close'a
                    # ikame ediyordu. Kuru-kosuda fiyatlanamayan hedefle fill
                    # "basarili" sayildi: 0 pozisyon alindi AMA "rebalance" history
                    # olayi yazildi -> sayac sifirlandi, pending tuketildi, hesap
                    # nakitte kaldi, hicbir sey isaretlemedi = SESSIZ BOZULMA.
                    # Kismi durumda daha sinsi: hedef agirliklardan sessizce sapilir.
                    #
                    # OLCUM (2021+ modern rejim, 47 rebalans gunu):
                    #   fill-tarafi kapsama : 47/47 TAM (%100), min=medyan=ort=%100
                    #   karar-tarafi        : 47/47 TAM (10 pick), eksik 0, bos 0
                    # -> Ayarlanacak bir DAGILIM YOK. Kademeli yuzde esigi
                    #    (ör. "%90 altinda ertele") olculemez, uydurma olurdu.
                    #
                    # KURAL (esik degil, KATI): %100 norm oldugu icin HER SAPMA
                    # anomalidir. Eksik varsa fill KITAPLANMAZ; pending KORUNUR,
                    # omur sayaci isler (>2 gun -> mevcut iptal kurali, #0i-②).
                    # Ayri kacis yolu GEREKMIYOR - omur kurali dogal backstop.
                    #
                    # CLOSE IKAMESI KALDIRILDI: fill fiyatini sessizce degistirmek
                    # #0i'nin OLCMEK ISTEDIGI seyi (D+1 open'dan gercekci fill)
                    # kirletir. Olcum gosterdi ki ikameye ihtiyac YOK.
                    hedef = list((pending.get("weights") or {}).keys())
                    eksik = [t for t in hedef if t not in opens_today]
                    if eksik:
                        pending["fill_blocked"] = {
                            "at": trade_date,
                            "missing_n": len(eksik),
                            "missing_sample": eksik[:5],
                        }
                        print(f"[shadow] {acc} FILL ERTELENDI — hedefin {len(eksik)}/{len(hedef)} "
                              f"tickerinda D+1 open YOK: {eksik[:5]} | pending KORUNDU "
                              f"(decided_at={pending.get('decided_at')})")
                    else:
                        pf.rebalance(state, pending["weights"], opens_today, slippage=slippage,
                                     trade_date=trade_date, reason=pending.get("reason", "rebalance"),
                                     scale=pending.get("scale", 1.0))
                        # #0i-5: bu fill D+1 OPEN'dan yapildi -> kaydi HEMEN damgala.
                        # `[-1]` guvenli: `pf.rebalance` tam BIR history kaydi ekler ve
                        # append oncesi erken donusu YOKTUR (AST ile dogrulandi), ayrica
                        # asagidaki satir zaten ayni varsayima dayaniyor. Stop blogu
                        # (`close_positions`) BUNDAN SONRA calisir; damga once vurulmali
                        # ki `[-1]` stop kaydina kaymasin.
                        if state.get("history"):
                            state["history"][-1]["fill_convention"] = FILL_CONV_NEXT_OPEN
                        new_trades.extend((state.get("history", [])[-1] or {}).get("trades", []))
                        state.pop("_pending_rebalance", None)
                        pending = None
                        filled_now = True

            # 2b) STOP — TEK BLOK, fill'den SONRA (#0i-①, 2026-08-01 duzeltmesi).
            #
            # Eskiden IKI stop blogu vardi (fill oncesi + fill sonrasi "ekstra").
            # Fill-oncesi olan tasarimla celisiyordu (yukari bak) ve kaldirildi;
            # bu tek blok her iki durumu da dogru kapsiyor:
            #   FILL OLDU  -> pozisyonlar TAZE (rebalans hepsini yeniledi),
            #                 stop onlara D+1 CLOSE'dan bakar. Modern rejimde
            #                 yapisal olarak tetiklenemez: taze pozisyon peak=entry
            #                 -> WIDE %15 esik, gunluk taban ise sert %10 (#0m⑥)
            #                 => en fazla %10 dusus < %15 esik. Derinlik savunmasi
            #                 olarak korunuyor (limit degisirse / eski rejim).
            #   FILL YOK   -> mevcut pozisyonlara normal stop (#0l davranisi aynen).
            if run_label == "kapanis":
                sells = pf.check_stops(state, prices_today)
                if sells:
                    stop_trades = pf.close_positions(state, sells, prices_today,
                                                     slippage=slippage, trade_date=trade_date)
                    new_trades.extend(stop_trades)

            # 3) KARAR — sayac FILL'de sifirlandigi icin (history olayi fill'de yazilir)
            #    burada rebal_status FILL SONRASI durumu gorur.
            should_rebalance, initial_entry, rebal_elapsed, last_selection = rebal_status(
                state, prices, date)
            thin_deferred = False
            # Karar YALNIZ: kapanis kosusu + zamani geldi + pending YOK (#0i-②, spam yok)
            if run_label == "kapanis" and should_rebalance and not state.get("_pending_rebalance"):
                if mode == "O":
                    picks, sig_map, exc = omega_mod.select(data, signals, date)
                    weights = omega_mod.weights(picks, sig_map)
                else:
                    picks, sig_map, exc = strat_mod.select(data, signals, date, mode=mode)
                    if mode in ("B", "F"):
                        weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
                    else:
                        weights = {t: 1.0 for t in picks}
                # #0e-GUARD: ince secim -> KARAR VERME, ertele (pending YAZILMAZ).
                # Yer bilincli: select() CAGRILDI (strategy.py DOKUNULMAZ, ciktisi
                # okunuyor), karar ondan SONRA veriliyor -> F-datapath degismiyor.
                # NOT: istisna KULLANILMAZ — hesap dongusu `except Exception` ile
                # sarili, istisna results[acc]={"error":..} olarak YUTULURDU.
                thin_deferred = _thin_defer(state, acc, picks, trade_date)
            if (run_label == "kapanis" and should_rebalance
                    and not state.get("_pending_rebalance") and not thin_deferred):
                scale = strat_mod.regime_scale(data, date)
                reason = "initial_entry" if initial_entry else "rebalance"
                # HEDEF BIRIMI = AGIRLIK (#0i-2b), lot DEGIL. Lot D+1 fill aninda
                # hesaplanir (pf.rebalance: alloc = deployed*w/tw; shares = alloc/fiyat)
                # -> D+1'de stop olduysa toplam-deger dusmustur, agirlik uyarlanir.
                # weights + scale KARAR aninda DONUK; deger + fiyat D+1 fill'de.
                state["_pending_rebalance"] = {
                    "decided_at": trade_date,
                    "decided_run": run_label,
                    "picks": list(picks),
                    "weights": {str(k): float(v) for k, v in weights.items()},
                    "scale": float(scale),
                    "reason": reason,
                    "status": "pending",
                }
                pending = state["_pending_rebalance"]
                decided_now = True
                print(f"[shadow] {acc} KARAR verildi ({len(picks)} pick) -> pending, "
                      f"fill D+1 open'da")
            # #0i-5: kaydetmeden ONCE, bu kosumda yazilan her sey dahil, damgasiz
            # kalan history kayitlarini geriye donuk isaretle (idempotent).
            _stamp_fill_convention(state)
            pf.save(state, state_dir=config.STATE_DIR)
            results[acc] = {
                "value": round(pf.current_value(state, prices_today), 4),
                "n_pos": len(state["positions"]),
                "sells": sells,
                "stop_trades": stop_trades,
                # #0i: ICRA edildi mi (fill bu kosuda kitaplandi). Karar icin
                # "rebalance_decided" / "pending_rebalance" alanlarina bak.
                "rebalance": filled_now,
                "rebalance_decided": decided_now,
                "rebalance_due": should_rebalance,
                "initial_entry": initial_entry,
                # Takvim GORUNURLUGU — sessiz "hic tetiklenmedi" bir daha gizli kalmasin.
                "last_selection": last_selection,
                "rebal_elapsed": rebal_elapsed,
                "rebal_due_in": (config.REBAL_GUN - rebal_elapsed) if rebal_elapsed is not None else None,
                # #0i-③ GORUNURLUK: pending EYLEMI yalniz kapanista, ama HER kosuda
                # RAPORLANIR. Eylemsiz+gorunmez olsaydi takilan pending gorunmezdi
                # ve "omur<=2 gun" kurali denetlenemezdi ("yoklugun imzasi yok").
                # #0k GORUNURLUK: "kontrol edildi-temiz" ile "kontrol EDILEMEDI"
                # ayri raporlanir (yok != kirik != yanlis-olculen, dedektor hali).
                # #0e-GUARD gorunurlugu: ertelendiyse SEBEBI ve SAYACI raporlanir
                # (sessiz erteleme = "yoklugun imzasi yok"in yeni bir hali olurdu).
                "rebal_thin_deferred": (state.get("_rebal_defer") or None),
                "ca_checked": ca_checked,
                "ca_fixed": ca_fixed or None,
                "ca_unchecked": ([{"ticker": t, "reason": r} for t, r in ca_unchecked]
                                 if ca_unchecked else None),
                "pending_rebalance": ({
                    "decided_at": pending.get("decided_at"),
                    "picks_n": len(pending.get("picks") or []),
                    "age_days": _pending_age_days(pending.get("decided_at"), trade_date),
                    "status": pending.get("status"),
                    # kapsama-kontrolu fill'i bloklarsa GORUNUR olsun (sessiz kalmasin)
                    "fill_blocked": pending.get("fill_blocked"),
                } if pending else None),
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
        # #0e-GUARD G1 SIMETRISI: G1 de strat_mod.select(mode="F") kullaniyor
        # (g1_account.py:387) ama `is_rebal`i BURADAN aliyor -> guard'i burada
        # uygulamak yeterli, g1_account.py DOKUNULMAZ kalir.
        g1_gate = g1_should_rebalance          # kapi (guard uygulanir), VADE ayri
        if run_label == "kapanis" and g1_should_rebalance and not g1_state.get("_pending_rebalance"):
            try:
                _g1_picks, _, _ = strat_mod.select(data, signals, date, mode="F")
            except Exception:
                _g1_picks = []
            if _thin_defer(g1_state, "G1", _g1_picks, trade_date):
                # KAPIYI kapat ama VADEYI bozma: `rebalance_due` raporu VADE
                # demek, "guard'dan gecti" demek DEGIL. g1_should_rebalance'i
                # ezersek rapor "vade gelmedi" der -> TERS BILGI (#0i'nin
                # duzelttigi bayrak-sinifi). Ayri degisken kullanilir.
                g1_gate = False
        # #0k — G1 icin de CA duzeltmesi, step'ten ONCE (F ile simetrik).
        # G1 giris tarihleri trades[]'ten cozulur (history'sinde ticker YOK).
        g1_ca_fixed, g1_ca_unchecked, g1_ca_checked = ([], [], None)
        if run_label == "kapanis":
            g1_ca_fixed, g1_ca_unchecked, g1_ca_checked = _ca_detect_and_fix(
                g1_state, "G1", prices, trade_date)
        # eval_stops: G1 de F ile AYNI stop semantigi (yalniz kapanis) — #0l.
        # Yarim birakilirsa G1 kiyasi hipotezi degil semantik farki olcer.
        g1_state, g1_events = g1_mod.step(
            data, signals, g1_state, date, prices_today, g1_gate,
            slippage=slippage, eval_stops=(run_label == "kapanis"),
            opens_today=(opens_today if run_label == "kapanis" else {}))
    f_return_pct = None
    if results.get("F", {}).get("value") is not None:
        f_return_pct = (results["F"]["value"] - 1) * 100
    g1_info = g1_mod.summary(g1_state, prices_today, f_return_pct=f_return_pct)
    g1_trades = _g1_events_to_trades(g1_events)
    g1_info.update({
        "n_pos": g1_info.get("n_positions"),
        # #0i FAZ-5 (F ile SIMETRIK): "rebalance" = ICRA EDILDI (bu kosuda fill
        # kitaplandi), vade DEGIL. G1'de icra izi = events["buys"] (fill BUY uretir;
        # karar gunu 0 uretir). Eskiden `g1_should_rebalance` (vade) yazilıyordu ->
        # karar gunu True/0-islem, fill gunu vade-dustugu icin yanlis okuma.
        "rebal_thin_deferred": (g1_state.get("_rebal_defer") or None),
        "ca_checked": g1_ca_checked,
        "ca_fixed": g1_ca_fixed or None,
        "ca_unchecked": ([{"ticker": t, "reason": r} for t, r in g1_ca_unchecked]
                         if g1_ca_unchecked else None),
        "rebalance": bool((g1_events or {}).get("buys")),
        "rebalance_decided": bool(g1_state.get("_pending_rebalance")),
        "rebalance_due": g1_should_rebalance,
        "pending_rebalance": ({
            "decided_at": (g1_state.get("_pending_rebalance") or {}).get("decided_at"),
            "targets_n": len((g1_state.get("_pending_rebalance") or {}).get("targets") or {}),
            "fill_blocked": (g1_state.get("_pending_rebalance") or {}).get("fill_blocked"),
        } if g1_state.get("_pending_rebalance") else None),
        "pending_reentry": ({
            "decided_at": (g1_state.get("_pending_reentry") or {}).get("decided_at"),
            "targets_n": len((g1_state.get("_pending_reentry") or {}).get("targets") or {}),
            "re_factor": (g1_state.get("_pending_reentry") or {}).get("re_factor"),
            "fill_blocked": (g1_state.get("_pending_reentry") or {}).get("fill_blocked"),
        } if g1_state.get("_pending_reentry") else None),
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
        out_dir = DOCS_STATE_DIR      # kuru-kosuda yonlendirilebilir (yukari bak)
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
