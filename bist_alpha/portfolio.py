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


def usable_price(raw):
    """Ham degeri KULLANILABILIR FIYAT'a cevirir ya da REDDIN SEBEBINI soyler.

    Doner: (fiyat, None)  |  (None, sebep)

    TEK OTORITE (P0.3 adim 2b): `check_stops` ve `g1_account` ayni kapiyi
    cagirir. Ikisi zaten `stop_level`i paylasiyordu; fiyat dogrulamasini iki
    yerde ayri yazmak, kayitta "IKIZI ama BIREBIR DEGIL" diye gecen ayrismayi
    buyuturdu.

    NUMPY NORMALIZASYONU ONCE (olculdu 2026-09-10): fiyatlar pandas/numpy'den
    gelir ve `isinstance(np.bool_(True), bool)` FALSE'tur -> cikplak bool
    kontrolu numpy bool'u KACIRIR ve `float()` onu 1.0 yapar; sonuc 1.00'dan
    SATIS. `.item()` once cagrilinca np.bool_ -> python bool olur ve yakalanir.
    (`_py` de tam bu yuzden bool'u ilk sirada ele aliyor.)

    Sebepler tek kelime hazinesi: fiyat_yok · fiyat_sayi_degil ·
    fiyat_gecersiz (NaN/inf) · fiyat_pozitif_degil.
    """
    if raw is None:
        return None, "fiyat_yok"
    item = getattr(raw, "item", None)      # numpy/pandas scalar -> native
    if callable(item):
        try:
            raw = item()
        except Exception:
            pass
    if isinstance(raw, bool):
        # float(True) == 1.0 -> bool her kapidan gecip 1.00'dan SATIS uretirdi.
        return None, "fiyat_sayi_degil"
    try:
        p = float(raw)
    except (TypeError, ValueError):
        return None, "fiyat_sayi_degil"
    if not math.isfinite(p):
        return None, "fiyat_gecersiz"
    if p <= 0:
        return None, "fiyat_pozitif_degil"
    return p, None


def check_stops(state, prices_today):
    """
    Güncel fiyatlarla stop kontrolü. SAT edilmesi gerekenleri döner.
    prices_today: {ticker: price}

    Returns: (sells, unchecked)
      sells     = [{'ticker', 'price', 'reason', 'giveback'}]
      unchecked = [(ticker, sebep), ...] — stop'u OLCULEMEYEN pozisyonlar

    P0.3 — KURAL: KULLANILABILIR SAYI OLMAYAN SEY FIYAT DEGILDIR.
    Olculen davranis (2026-09-10, yama oncesi) DORT ayri kusur gosterdi:
      fiyat yok  -> sessizce `continue`; stop KACIRILIR ve kimse bilmez
      NaN        -> `NaN < stop` her zaman False -> sessizce "stop yok"
      0 / negatif-> GERCEK SATIS uretiyordu; veri arizasi uydurma fiyattan emir
      metin      -> yakalanmayan TypeError, kosumu dusuruyordu
    Dordu de artik `unchecked`e gider. Hicbiri satis uretmez, hicbiri sessizce
    dusmez.

    FAIL-SAFE YONU (koddan ONCE yazildi): bilinmiyor != guvenli, ama bilinmiyor
    != breached de DEGIL. "Breached varsay" veri bosluğundan SATIS uretirdi ki
    en kotusu odur. Dogru davranis: OLCEMEDIGINI SOYLE, karari cagirana birak.

    TUPLE DONUSU BILINCLI: opsiyonel out-parametre sessizce gecilebilirdi ve
    bu, "sessizce kaybolan bilgi" kusurunun opt-in halini uretirdi. Tek uretim
    cagirani var (shadow.py) -> maliyeti bir satir.
    """
    sells = []
    unchecked = []
    for tic, pos in state["positions"].items():
        pt, sebep = usable_price((prices_today or {}).get(tic))
        if sebep:
            unchecked.append((tic, sebep))
            continue
        if "peak" not in pos or not pos["peak"]:  # eski JSON koruması
            pos["peak"] = pos.get("entry", pt)
        if pt > pos['peak']:
            pos['peak'] = pt          # peak güncelle (kalıcı)
        st = stop_level(pos)
        if pt < st:
            giveback = (pos['peak'] - pt) / pos['peak'] * 100
            sells.append({"ticker": tic, "price": round(pt, 2),
                          "reason": "stop", "giveback": round(giveback, 2)})
    return sells, unchecked


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


def rebalance(state, picks_with_weights, prices_today, slippage=0.0, trade_date=None, reason="rebalance", scale=1.0):
    """
    Portföyü yeni pick'lere göre günceller (sat + weighted al).
    picks_with_weights: {ticker: lot_weight}
    prices_today: {ticker: price}
    scale: yatırılan sermaye oranı (1.0=tümü, 0.5=yarısı — sideways modu).
           Kalan (1-scale) nakit olarak tutulur.
    Pozisyon state'i KALICI olarak günceller.
    """
    friction = config.COMMISSION / 2 + slippage
    scale = max(0.0, min(1.0, scale))  # [0, 1] sınır
    trades = []
    # Toplam değer — `_valuation` ile AYNI hesap (ikinci uygulama dogmasin).
    # P0.3 adim 4: eskiden ham `prices.get(tic, entry)` idi; NaN girdiginde
    # `total` nan olur, `deployed` nan olur ve state'e `shares: nan` YAZILIRDI.
    # Birincil koruma shadow.py fill kapisidir (eksik fiyatta fill ERTELENIR);
    # bu satir IKINCI KILIT — kapi bir gun atlanirsa bozuk state yazilmasin.
    total, _reb_unpriced = _valuation(state, prices_today)
    # Tümünü sat
    for tic, pos in list(state["positions"].items()):
        p, _sebep = usable_price(prices_today.get(tic))
        if _sebep:
            p, _esebep = usable_price(pos.get("entry"))
            if _esebep:
                p = 0.0
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
    # Weighted al — scale ile kısmi yatırım (kalan nakit olarak kalır)
    deployed = total * scale
    tw = sum(picks_with_weights.values())
    if tw > 0:
        for tic, w in picks_with_weights.items():
            ep = prices_today.get(tic)
            if ep and ep > 0:
                alloc = deployed * (w / tw) * (1 - friction)
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


def _valuation(state, prices_today):
    """(toplam, unpriced) — degerlemenin TEK hesabi.

    `current_value` ve `value_coverage` ikisi de burayi cagirir; ayri yazilsalar
    ayni sayiyi iki farkli yerde hesaplayan ikinci uygulama dogardi.

    P0.3 adim 3 — olculen davranis (2026-09-10, yama oncesi), bes ayri sonuc:
      fiyat yok  -> `entry` yazilir, SESSIZ. Ornek: gercek 310.0 yerine 210.0
      NaN        -> TUM portfoy degeri `nan` olur
      0          -> pozisyon 0 degerlenir
      negatif    -> deger DUSER (10 + 2*(-5) = 0.0)
      cop metin  -> TypeError, kosumu dusurur
    NaN'in bedeli en agiri: `daemon.py` dashboard'i duz `json.dump` ile yazar
    (`allow_nan` kapatilmamis) -> dosyaya cikplak `NaN` girer -> `JSON.parse`
    ECMA-404 geregi SyntaxError atar -> PANELIN TAMAMI olur. 120 surum tarandi,
    gecmiste HIC olmamis: gerceklesmemis gizli risk.

    KARAR: `entry` FALLBACK'I KORUNUYOR ama artik ETIKETLI.
    Atlamak pozisyonun TAMAMINI silerdi (daha buyuk hata); `entry` o pozisyon
    icin bilinen son GERCEKLESMIS fiyattir. Uc secenegin de kusurlu oldugu bir
    yerde en az yanlis olani secip ADINI KOYMAK, sessizce uydurmaktan iyidir.
    NaN/inf/0/negatif/metin ARTIK `entry`ye duser — yani deger asla NaN olmaz
    ve asla dusurulmez.
    """
    total = state["cash"]
    unpriced = []
    for tic, pos in state["positions"].items():
        p, sebep = usable_price((prices_today or {}).get(tic))
        if sebep:
            # FALLBACK'IN KENDISI DE DOGRULANIR (olculdu 2026-09-10):
            # `entry` NaN ise deger YINE `nan` oluyordu, None/metin ise
            # TypeError ile kosum dusuyordu. Fiyat yolunu kapatip fallback
            # yolunu acik birakmak, ayni kusurun ikinci kopyasiydi.
            p, entry_sebep = usable_price(pos.get("entry"))
            if entry_sebep:
                # Ne fiyat ne entry kullanilabilir -> pozisyonun degeri
                # GERCEKTEN bilinmiyor. 0 eksik gosterir, NaN her seyi zehirler,
                # istisna kosumu dusurur; en az yanlis olan 0 ve AYRI etiket
                # (salt fiyat eksikligiyle karistirilmasin: bu BOZUK STATE'tir).
                unpriced.append((tic, "fiyat_ve_entry_gecersiz"))
                p = 0.0
            else:
                unpriced.append((tic, sebep))
        total += pos["shares"] * p
    return total, unpriced


def current_value(state, prices_today):
    """Portföyün güncel toplam değeri. Imza DEGISMEDI (alti cagiran var)."""
    return _valuation(state, prices_today)[0]


def value_coverage(state, prices_today):
    """Degerlemede fiyatlanamayan pozisyonlar: [(ticker, sebep), ...].

    Deger tek basina "eksiksiz mi" sorusunu cevaplamaz; bu fonksiyon cevaplar.
    Yayimlayan cagiranlar (rapor/dashboard) ikisini BIRLIKTE tasimali.
    """
    return _valuation(state, prices_today)[1]


def held_tickers(state):
    return set(state["positions"].keys())
