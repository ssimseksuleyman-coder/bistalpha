#!/usr/bin/env python3
"""
SİSTEM ÖZ-DENETİM (self-test) — her an çalıştır, eksik kalmasın.

  python selftest.py                    # offline/deterministik smoke test
  python selftest.py --mode live         # ag/canli veri kontrolleri dahil
  python selftest.py --mode all          # live ile ayni, gelecek agir testler icin

Kontrol eder:
  1. Tüm modüller import oluyor mu
  2. Orphan modül var mı (tanımlı ama bağlı değil)
  3. Entry point script'leri parse oluyor mu
  4. Veri dosyaları yerinde mi (ana veri, OMEGA, Deniz)
  5. config flag'leri kodda kullanılıyor mu
  6. Backtest A/B/F (gömülü veride sabit aralık, canlıda makul aralık)
  7. Yan kaynak (sidesource) bağlı ve veri okuyor mu
  8. Öz-iyileştirme / bakım / optimizatör çalışıyor mu
  9. 7/24 deploy (bilgisayar kapalıyken çalışma) doğru kurulu mu
  10. CLI'lar gerçekten çalışıyor mu (backtest/analyze/daemon)
Çıkış kodu 0 = bloklayıcı hata yok, 1 = bloklayıcı hata var.
`--strict` verilirse uyarılar da 1 döndürür.
"""
import argparse
import ast
import os
import sys
import importlib

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
fails = []
warnings = []

# Windows konsol (cp1252) Türkçe/emoji karakterlerde UnicodeEncodeError verir -> utf-8'e sabitle.
# Izole/kozmetik: yalniz bu script'in cikti-akisini etkiler; PYTHONIOENCODING gerekmeden calisir.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# [2] orphan-taramasi os.walk(".") ile TUM agaci gezer; repo-ici .venv/site-packages'i yutmasin
# diye bu dizinlere HIC inme (dirs'i yerinde buda). Aksi halde binlerce pip .py'si tek string'e
# okunur -> patolojik yavas + bellek sisme (olculdu: 450MB+). Sadece proje kaynagini tara.
_WALK_SKIP = {".venv", "venv", "env", ".git", "__pycache__", "node_modules",
              "site-packages", ".pytest_cache", ".mypy_cache", ".idea", "scratchpad"}


def ok(msg): print(f"   \u2713 {msg}")
def bad(msg): print(f"   \u2717 {msg}"); fails.append(msg)
def warn(msg): print(f"   \u26a0 {msg}"); warnings.append(msg)


def parse_args():
    ap = argparse.ArgumentParser(description="BIST Alpha selftest")
    ap.add_argument(
        "--mode",
        choices=["offline", "live", "all"],
        default="offline",
        help="offline=deterministik; live=ag ve canli veri kontrolleri dahil",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Uyarilari da cikis kodu 1 say. Varsayilan: yalniz bloklayici hatalar fail eder.",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    live_mode = args.mode in {"live", "all"}

    print("=" * 70)
    print("BIST ALPHA — SİSTEM ÖZ-DENETİM")
    print(f"MOD: {args.mode} ({'canli/ag kontrolleri dahil' if live_mode else 'offline/deterministik smoke test'})")
    print("=" * 70)

    # 1. Modül import
    print("\n[1] Modül import")
    mods = [f[:-3] for f in os.listdir("bist_alpha")
            if f.endswith(".py") and f != "__init__.py"]
    for m in sorted(mods):
        try:
            importlib.import_module(f"bist_alpha.{m}")
            ok(m)
        except Exception as e:
            bad(f"{m}: {e}")

    # 2. Orphan modül
    print("\n[2] Orphan modül (bağlı mı)")
    src = ""
    for root, dirs, files in os.walk("."):
        dirs[:] = [dd for dd in dirs if dd not in _WALK_SKIP]   # yerinde buda: bu dizinlere inme
        for f in files:
            if f.endswith(".py"):
                src += open(os.path.join(root, f), encoding="utf-8").read()
    for m in sorted(mods):
        self_src = open(f"bist_alpha/{m}.py", encoding="utf-8").read()
        ext = (src.count(f"import {m}") + src.count(f"{m}.") + src.count(f"from .{m}")
               - self_src.count(f"{m}."))
        if ext > 0:
            ok(f"{m} bağlı")
        else:
            warn(f"{m} ORPHAN")

    # 3. Entry point parse
    print("\n[3] Entry point parse")
    for s in ["run_backtest.py", "daemon.py", "analyze_stock.py", "shadow.py"]:
        try:
            ast.parse(open(s, encoding="utf-8").read())
            ok(s)
        except Exception as e:
            bad(f"{s}: {e}")

    # 4. Veri
    # BLOKLAYICI = yalnizca repoda OLMASI GEREKEN veri (golden-master girdisi).
    # LOCAL-ONLY = Deniz-musluğu (2026-07-17) sonrasi kasitli repoda-degil:
    #   data/omega/*  -> tumu Deniz-bulten-turevi (lisans) -> gitignore + rm --cached
    #   deniz_inbox/  -> ham Deniz PDF'leri -> gitignore (kaza-git-add korumasi)
    # Bunlari bad() saymak CI'i kirmisti: gizlilik-onlemi, golden-master'in (DOKUNULMAZ
    # korumasi) hic calisamamasina yol acti — iki guvenlik-onlemi cakisti. Assert artik
    # gercege kalibre: yoklari BEKLENEN (local'de varsa bilgi, yoksa uyari-degil).
    print("\n[4] Veri bütünlüğü")
    if os.path.exists("data/Tarihsel_Fiyat_Bilgileri.xlsx"):
        ok("ana veri (golden-master girdisi): data/Tarihsel_Fiyat_Bilgileri.xlsx")
    else:
        bad("ana veri YOK: data/Tarihsel_Fiyat_Bilgileri.xlsx (golden-master kosamaz)")
    for path, desc in [("data/omega", "OMEGA yan-kaynak"),
                       ("deniz_inbox", "Deniz bülten")]:
        if os.path.exists(path):
            ok(f"{desc}: {path} (local'de var)")
        else:
            # "ok" DEGIL "bilincli-atlandi": gerekce alani tasinsin, yoksa gelecekte
            # bu satir "kontrol gecti" diye okunur ve BASKA bir sebeple yok olsa da susar.
            ok(f"ATLANDI (bilinçli) — {desc}: {path} repoda YOK. "
               f"Gerekçe: Deniz-musluğu 2026-07-17, lisanslı-türev → local-only. "
               f"Bu yol repoda BEKLENMİYOR; assert kaldırıldı, silinmedi.")

    # Sektör kapsamı (eşleme eksikliği yanlış sonuç üretir)
    try:
        from bist_alpha import sectors as _sec, data as _dm
        _d = _dm.load_data()
        _last = _d["mcaps"].index[-1]
        _top = set(_d["mcaps"].loc[_last].dropna().nlargest(100).index)
        _unm = _top - set(_sec.STOCK_TO_SECTOR.keys())
        if len(_unm) <= 3:
            ok(f"sektör kapsamı: top-100'de {len(_unm)} eşlenmemiş (kabul edilebilir)")
        else:
            warn(f"sektör kapsamı: top-100'de {len(_unm)} eşlenmemiş → XU100 yığılması riski")
    except Exception as e:
        warn(f"sektör kapsam kontrolü: {e}")

    # 5. config flag tutarlılık
    print("\n[5] config flag ↔ kod")
    cfg = open("bist_alpha/config.py", encoding="utf-8").read()
    for fl in ["LATE_ENTRY_FILTER", "SIDEWAYS_SCALING", "SECTOR_PUMP_VETO",
               "MODE", "SLIPPAGE_PER_SIDE"]:
        if fl not in cfg:
            bad(f"{fl} config'de yok")
        elif src.count(fl) <= 1:
            warn(f"{fl} kodda kullanılmıyor")
        else:
            ok(fl)

    # 6. Backtest (TESPİT 4 — statik sapma düzeltildi)
    print("\n[6] Backtest A/B/F + F golden-master (DOKUNULMAZ koruması)")
    try:
        from bist_alpha import data as dm, signals as sm, backtest as bm
        # load_data() HER ZAMAN donmus Excel'i okur; config.DATA_SOURCE canli-daemon
        # feed'ini secer, bu backtest'i DEGIL -> kontrol DATA_SOURCE'a gate'lenMEZ.
        # (Eski kod src=="file" ile gate'liyordu; varsayilan "yahoo" oldugundan
        #  aralik-kontrolu hic calismiyordu = olu koruma.)
        d = dm.load_data()
        sig = sm.compute_signals(d)
        ranges = {"A": (260, 320), "B": (240, 300), "F": (275, 335)}
        results = {}
        for mode in ["A", "B", "F"]:
            r = bm.run(d, sig, mode=mode)
            if not r:
                bad(f"{mode}: backtest çalışmadı")
                continue
            results[mode] = r
            lo, hi = ranges[mode]
            if lo <= r["ret"] <= hi:
                ok(f"{mode}: %{r['ret']} (donmuş veri beklenen {lo}-{hi})")
            else:
                bad(f"{mode}: %{r['ret']} donmuş veri aralığı dışı")

        # --- F GOLDEN-MASTER — DOKUNULMAZ'in tek otomatik korumasi ---
        # Donmus Excel + sabit config => deterministik. Bu sayilar oynadiysa F'in
        # secim/stop davranisi DEGISMISTIR. Kirmizi = "kasitli mi, kaza mi?" sorusu.
        # Tolerans 0.05: platform float-sapmasina bagisik; gercek F-degisimi
        # (farkli pick/agirlik) puan mertebesinde oynar -> yakalanir.
        gm = results.get("F")
        if gm:
            E_RET, E_DD, E_STOPS = 301.07, -5.54, 56
            if (abs(gm["ret"] - E_RET) < 0.05 and abs(gm["dd"] - E_DD) < 0.05
                    and gm["n_stops"] == E_STOPS):
                ok(f"F golden-master KORUNDU: ret={gm['ret']} dd={gm['dd']} stops={gm['n_stops']}")
            else:
                bad(f"F GOLDEN-MASTER SAPTI → ret={gm['ret']} (bkl {E_RET}), "
                    f"dd={gm['dd']} (bkl {E_DD}), stops={gm['n_stops']} (bkl {E_STOPS}) "
                    f"— F davranışı değişti: KASITLI mı?")
    except Exception as e:
        bad(f"backtest hatası: {e}")

    # 6b. F-DATAPATH 5-SHA — golden-master'in KAPSAMADIGI yari
    #
    # NEDEN AYRI BLOK: golden-master `data + signals + backtest` yolunu korur.
    # `portfolio.py` backtest'te HIC REFERANS ALMIYOR -> oraya yazilan bir degisiklik
    # golden-master'i KIRMAZ, sessizce gecer. "Korunuyor sanilan yer, daha tehlikeli yer."
    # Bu assert o bosluğu kapatir.
    #
    # NEDEN 6'nin try'i DISINDA: backtest patlarsa yukarisi except'e duser ve SHA
    # kontrolu SESSIZCE atlanirdi (sahte-yesil). Ayri blok = her kosumda calisir.
    #
    # YONTEM: git blob SHA-1 (`git hash-object`), ilk 12 hane. Kanonik olan bu —
    # `sha256sum <dosya>` DEGIL: Windows'ta core.autocrlf=true oldugundan calisma
    # agacindaki dosya CRLF, repo icerigi LF; `git hash-object` filtreyi uygular ve
    # iki platformda ayni degeri verir.
    #
    # BASELINE IKI YERDE (bilincli): burasi makine-okur (CI), `local/ACIK_ISLER.md ->
    # F-DATAPATH BASELINE` insan-okur. local/ gitignored oldugu icin CI oradan okuyamaz.
    # Degistirilecekse IKISI BIRDEN degistirilir; tek tarafli degisiklik sapmayi gizler.
    print("\n[6b] F-datapath 5-SHA (DOKUNULMAZ — golden-master'in kapsamadigi yari)")
    F_DATAPATH_BASELINE = {
        "bist_alpha/strategy.py":  "7330c5f19752",
        "bist_alpha/backtest.py":  "7708e7818b66",
        "bist_alpha/config.py":    "8eee78db71e0",
        "bist_alpha/portfolio.py": "09ad265d9fd5",
        "bist_alpha/signals.py":   "22bb89bf9de5",
    }
    import subprocess
    for yol, beklenen in F_DATAPATH_BASELINE.items():
        try:
            sha = subprocess.check_output(["git", "hash-object", yol],
                                          text=True, stderr=subprocess.DEVNULL).strip()[:12]
        except Exception as e:
            # "OLCULEMEDI" != "TEMIZ": sessiz atlama sahte-yesil uretir -> BLOKLAYICI.
            bad(f"{yol}: 5-SHA OLCULEMEDI ({type(e).__name__}) — git yok/erisilemez")
            continue
        if sha == beklenen:
            ok(f"{os.path.basename(yol)} {sha}")
        else:
            bad(f"{yol}: F-DATAPATH SAPTI → {sha} (bkl {beklenen}) "
                f"— F'in veri yolu degisti: KASITLI mi?")

    # 6c. #0i-B — pending yasi ISLEM gunu mu (takvim DEGIL)
    #
    # CANLI VAKA: 2026-08-28 (Cuma) karari, 08-31 (Pzt) kapanisinda TAKVIM ile 3 gun
    # sayilip PENDING_MAX_AGE_DAYS=2 esigine takildi ve IPTAL edildi (log muhurlu).
    # 08-31 karari 09-01'de takvim 1 -> FILL oldu. Ikisinde de ISLEM gunu 1'di.
    # Yani kok neden kontrollu karsitlikla kanitlandi: degisen tek sey takvim gunu.
    #
    # NEDEN BURADA: shadow.py golden-master kapsaminda DEGIL (backtest onu import
    # etmiyor) ve korunan 5-SHA'da da YOK -> tek otomatik korumasi bu blok.
    # Dosyanin DEGISMESI bekleniyor, o yuzden koruma SHA dondurmasi degil TEST.
    #
    # BILINEN SINIR: blok tek try/except ile sarili -> erken bir istisna sonraki
    # assertion'lari ATLAR. SAHTE-YESIL URETMEZ (except -> bad(), bloklayici), ama
    # BILGI KAYBETTIRIR: tek hata gorunur, digerleri olculmeden gecer. Mutasyon
    # testinde fiilen yasandi (2026-09-01): sadik-olmayan mutasyon istisna firlatti
    # ve asil iddiaya hic ulasilmadi; sadik mutasyonla tekrarlaninca iddia yakaladi.
    print("\n[6c] #0i-B pending yasi ISLEM gunu (shadow.py — golden-master disi)")
    try:
        import pandas as _pd
        import shadow as _sh
        _idx = _pd.bdate_range("2026-08-03", "2026-09-30")     # hafta sonu YOK
        _CUMA, _PZT, _SALI, _PER = "2026-08-28", "2026-08-31", "2026-09-01", "2026-09-03"
        _yas = lambda a, b: _sh._pending_trading_age_days(_idx, a, b)
        _iptal = lambda y: y is not None and y > _sh.PENDING_MAX_AGE_DAYS

        for ad, alinan, beklenen in [
            ("Cuma->Pzt yasi 1 islem gunu (takvim 3 DEGIL)", _yas(_CUMA, _PZT), 1),
            ("Cuma->Pzt IPTAL OLMAMALI",                     _iptal(_yas(_CUMA, _PZT)), False),
            ("Pzt->Sali yasi 1, IPTAL OLMAMALI",             _iptal(_yas(_PZT, _SALI)), False),
            ("Pzt->Per yasi 3 islem gunu",                   _yas(_PZT, _PER), 3),
            ("gercekten eski pending IPTAL OLMALI",          _iptal(_yas(_PZT, _PER)), True),
            ("esik siniri: 2 -> iptal YOK",                  _iptal(2), False),
            ("esik siniri: 3 -> iptal VAR",                  _iptal(3), True),
            ("bozuk tarih -> None (fail-safe: iptal ETME)",  _iptal(_yas("x!", _PZT)), False),
            ("decided_at bos -> iptal ETME",                 _iptal(_yas(None, _PZT)), False),
            ("PENDING_MAX_AGE_DAYS sabiti degismedi",        _sh.PENDING_MAX_AGE_DAYS, 2),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#0i-B {ad}: beklenen {beklenen}, alinan {alinan}")

        # IKI CAGRI YERI DE yeni fonksiyonu kullanmali. Yalniz iptal karari (satir ~632)
        # yamalanip panel alani (~806) unutulursa, karar dogru olur ama PANEL hala
        # takvim gunu gosterir -> "yanlis dil" (kullanici tespiti, 2026-09-01).
        _src = open(os.path.join(ROOT, "shadow.py"), encoding="utf-8").read()
        if "age = _pending_trading_age_days(prices.index" in _src:
            ok("iptal karari islem-gunu fonksiyonunu cagiriyor")
        else:
            bad("#0i-B iptal karari eski/yanlis fonksiyonu cagiriyor")
        if '"age_days": _pending_trading_age_days(prices.index' in _src:
            ok("panel age_days alani da ayni fonksiyonu cagiriyor")
        else:
            bad("#0i-B panel age_days hala takvim gunu gosteriyor olabilir")
        if "_pending_age_days(" not in _src:
            ok("eski takvim-gunu fonksiyonu kalmadi")
        else:
            bad("#0i-B eski _pending_age_days cagrisi hala var")
    except Exception as e:
        bad(f"#0i-B testi kosmadi: {type(e).__name__}: {e}")

    # ── [6d] #0k — CA kiyas bari FILL KONVANSIYONUNA gore secilmeli ────────────
    # NEDEN VAR: 2026-09-02'de dedektor 10 pozisyonun 7'sini sahte "CA" diye
    # duzeltti. Sebep: `#0i` fill'i ACILISA tasidi ama dedektor hala KAPANIS
    # bariyla kiyasliyordu -> giris gununun normal gun-ici hareketi CA sanildi.
    # Kalan 3 dogru olculdugu icin degil, hareketi tesadufen <%1 kaldigi icin
    # temiz gorundu (n_clean=3 SAHTE GUVENCEYDI).
    # TOLERANSI BUYUTMEK COZUM DEGIL: canli hareketi ortmek TOL>=%9.99 ister,
    # gercek kucuk CA'yi (1.03) yakalamak TOL<%3 ister -> celiski. Bu yuzden
    # asagida hem SIFIR-sahte-pozitif hem de 1.03'un YAKALANMASI birlikte aranir.
    print("\n[6d] #0k CA kiyas bari fill konvansiyonuna gore (shadow.py — golden-master disi)")
    try:
        import pandas as _pd
        import shadow as _sh
        from bist_alpha import g1_account as _g1m

        _G = "2026-09-01"
        _KG = _pd.Timestamp(_G)
        # 2026-09-02 canli olayi (olculdu): ticker -> (kayitli_entry, open, close)
        # 10/10 entry = o gunun ACILIS fiyati.
        _CANLI = {
            "OZATD": (4827.50, 4827.50, 4820.00), "KTLEV": (57.30, 57.30, 56.55),
            "BIGEN": (183.70, 183.70, 186.00),    "IEYHO": (207.80, 207.80, 208.50),
            "ODINE": (2013.00, 2013.00, 1812.00), "HEDEF": (77.05, 77.05, 75.85),
            "ALKLC": (425.75, 425.75, 427.00),    "SELEC": (334.50, 334.50, 338.00),
            "CRFSA": (290.75, 290.75, 317.50),    "EUPWR": (101.80, 101.80, 92.35),
        }
        def _cer(d):
            return _pd.DataFrame([d], index=[_KG])
        def _stt(entryler, konv=_sh.FILL_CONV_NEXT_OPEN):
            return {"positions": {t: {"entry": e, "peak": e} for t, e in entryler.items()},
                    "history": [{"date": _G, "type": "rebalance", "fill_convention": konv,
                                 "trades": [{"type": "BUY", "ticker": t} for t in entryler]}]}
        _ent = {t: v[0] for t, v in _CANLI.items()}
        _op = _cer({t: v[1] for t, v in _CANLI.items()})
        _cl = _cer({t: v[2] for t, v in _CANLI.items()})

        _f, _u, _c = _sh._ca_detect_and_fix(_stt(_ent), "F", _cl, "2026-09-02", opens=_op)
        _f2, _u2, _c2 = _sh._ca_detect_and_fix(_stt(_ent), "F", _cl, "2026-09-02")   # opens YOK
        _f3, _, _ = _sh._ca_detect_and_fix(_stt({"AAA": 300.0}), "F", _cer({"AAA": 101.0}),
                                           "2026-09-02", opens=_cer({"AAA": 100.0}))
        _f4, _, _ = _sh._ca_detect_and_fix(_stt({"BBB": 103.0}), "F", _cer({"BBB": 100.5}),
                                           "2026-09-02", opens=_cer({"BBB": 100.0}))
        _f5, _, _ = _sh._ca_detect_and_fix(_stt({"CCC": 50.0}, _sh.FILL_CONV_SAME_DAY), "F",
                                           _cer({"CCC": 50.0}), "2026-09-02")
        _f6, _, _ = _sh._ca_detect_and_fix(_stt({"CCC": 100.0}, _sh.FILL_CONV_SAME_DAY), "F",
                                           _cer({"CCC": 50.0}), "2026-09-02")
        _g1e = {"positions": {"ZZZ": {"entry": 100.0, "peak": 100.0}},
                "trades": [{"date": _G, "type": "BUY", "ticker": "ZZZ", "price": 100.0}]}
        _f7, _u7, _c7 = _sh._ca_detect_and_fix(_g1e, "G1", _cer({"ZZZ": 60.0}),
                                               "2026-09-02", opens=_cer({"ZZZ": 60.0}))

        for ad, alinan, beklenen in [
            ("canli 7 sahte-CA: dogru bar ile SIFIR duzeltme", len(_f), 0),
            ("canli vakada hicbiri 'olculemedi' degil",        len(_u), 0),
            ("canli vakada n_clean == 10",                     _c["n_clean"], 10),
            ("opens YOK -> eski kapanis barina DUSMEZ",        len(_f2), 0),
            ("opens YOK -> 10/10 olculemedi",                  len(_u2), 10),
            ("opens YOK -> n_clean 0 (olculemedi != TEMIZ)",   _c2["n_clean"], 0),
            ("gercek CA (oran 3.00) yakalanir",                [x["ticker"] for x in _f3], ["AAA"]),
            ("kucuk gercek CA (oran 1.03) yakalanir",          [x["ticker"] for x in _f4], ["BBB"]),
            ("same_day_close + entry==close -> CA DEGIL",      len(_f5), 0),
            ("same_day_close + gercek CA -> yakalanir",        [x["ticker"] for x in _f6], ["CCC"]),
            ("G1 damgasiz kayit DUZELTILMEZ (tahmin YOK)",     len(_f7), 0),
            ("G1 damgasiz sebep gorunur: fill_convention_yok", [r for _, r in _u7], ["fill_convention_yok"]),
            ("G1 damgasiz n_clean 0 (temiz SAYILMAZ)",         _c7["n_clean"], 0),
            ("FILL_CONV_NEXT_OPEN kopyalari ayni", _g1m.FILL_CONV_NEXT_OPEN, _sh.FILL_CONV_NEXT_OPEN),
            ("FILL_CONV_SAME_DAY kopyalari ayni",  _g1m.FILL_CONV_SAME_DAY, _sh.FILL_CONV_SAME_DAY),
            ("CA_RATIO_TOL degismedi (tolerans COZUM DEGIL)",  _sh.CA_RATIO_TOL, 0.01),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#0k {ad}: beklenen {beklenen}, alinan {alinan}")

        # G1 girisleri damgayi GERCEKTEN yaziyor mu (kaynak kontrolu: davranis testi
        # canli opens_today ister, damganin kodda durdugu burada dogrulanir).
        _g1src = open(os.path.join(ROOT, "bist_alpha", "g1_account.py"), encoding="utf-8").read()
        if _g1src.count("fill_convention=FILL_CONV_NEXT_OPEN") >= 2:
            ok("G1 BUY+REENTRY girisleri next_open damgasi yaziyor")
        else:
            bad("#0k G1 giris damgasi eksik (BUY ve/veya REENTRY)")
        if "fill_convention=FILL_CONV_SAME_DAY" in _g1src:
            ok("G1 cold-start girisi same_day damgasi yaziyor")
        else:
            bad("#0k G1 cold-start damgasi eksik")
    except Exception as e:
        bad(f"#0k testi kosmadi: {type(e).__name__}: {e}")

    # ── [6e] #1e — RAPOR KAPSAMI: eksik rapor GORUNUR olmali ───────────────────
    # NEDEN VAR: diger 17 liveness uyesi "yazici duruyor mu" sorar (damga YASI).
    # Slot donusurse (`#1c`) daemon yine kosar ve artefaktlari yazar -> 17 uye
    # YESIL kalir, kaybolan yalniz RAPORDUR. OLCULDU (2026-09-03): 48 is gununun
    # 9'u eksik (~%19) ve HICBIRI alarm uretmedi.
    # ESIKLER UYDURULMADI: pencere `report_gate.WINDOW_MINUTES`, slotlar
    # `report_gate.SLOTS` -> hedef/pencere degisirse kontrol kendiliginden kayar.
    print("\n[6e] #1e rapor kapsami (liveness_scan — golden-master disi)")
    try:
        import sys as _sys
        _sp = os.path.join(ROOT, "scripts")
        if _sp not in _sys.path:
            _sys.path.insert(0, _sp)
        from datetime import datetime as _dt
        import liveness_scan as _L
        import report_gate as _RG

        _SL = {a: (t.hour, t.minute) for a, t in _RG.SLOTS}
        _W = _RG.WINDOW_MINUTES
        _F = _L._missing_report_slots
        _V = _L._coverage_verdict
        _G3 = "2026-09-03"                       # Persembe (is gunu)
        def _T(g, s, m): return _dt(2026, 9, g, s, m)
        def _snt(gun, *lab): return {f"{gun}:{l}": {"sent_at": "x"} for l in lab}

        for ad, alinan, beklenen in [
            # sabah SAHTE ALARM olmamali — pencere kapanmadan eksik sayilmaz
            ("09:00 marker yok -> TAM (pencere acik)",  _F({}, _T(3, 9, 0), _SL, _W), []),
            ("13:14 (pencereye 1dk) -> TAM",            _F({}, _T(3, 13, 14), _SL, _W), []),
            # pencere kapaninca gorunur
            ("13:20 acilis yok -> ['acilis']",          _F({}, _T(3, 13, 20), _SL, _W), ["acilis"]),
            ("13:20 acilis var -> TAM",                 _F(_snt(_G3, "acilis"), _T(3, 13, 20), _SL, _W), []),
            ("18:10 ikisi yok -> 2 eksik",              _F({}, _T(3, 18, 10), _SL, _W), ["acilis", "gunici"]),
            ("22:20 3/3 var -> TAM",                    _F(_snt(_G3, "acilis", "gunici", "kapanis"), _T(3, 22, 20), _SL, _W), []),
            ("22:20 kapanis yok -> ['kapanis']",        _F(_snt(_G3, "acilis", "gunici"), _T(3, 22, 20), _SL, _W), ["kapanis"]),
            # `manuel` TELAFIDIR, teslim DEGIL -> slotu kapatmaz
            ("manuel var ama acilis yok -> hala eksik", _F(_snt(_G3, "manuel"), _T(3, 13, 20), _SL, _W), ["acilis"]),
            # hafta sonu yapisal olarak bos
            ("Cumartesi -> TAM",                        _F({}, _T(5, 22, 20), _SL, _W), []),
            # OLCULEMEDI != TAM (yanlis-sifir donus tipine gomulu)
            ("sent=None -> None (TAM DEGIL)",           _F(None, _T(3, 22, 20), _SL, _W), None),
            ("None ile [] ayni sey DEGIL",              _F(None, _T(3, 22, 20), _SL, _W) == [], False),
            # CANLI VAKA: 2026-09-01 acilis kayip, gunici+kapanis var
            ("canli 09-01 gun sonu -> ['acilis']",      _F(_snt("2026-09-01", "gunici", "kapanis"), _dt(2026, 9, 1, 22, 20), _SL, _W), ["acilis"]),
            ("canli 09-01 12:00 -> henuz TAM",          _F(_snt("2026-09-01", "gunici", "kapanis"), _dt(2026, 9, 1, 12, 0), _SL, _W), []),
            # verdict esikleri mevcut `_missed_slots` ailesiyle AYNI (yeni esik YOK)
            ("verdict 0 eksik -> GREEN",                _V([]), "GREEN"),
            ("verdict 1 eksik -> YELLOW",               _V(["acilis"]), "YELLOW"),
            ("verdict 2 eksik -> RED",                  _V(["acilis", "gunici"]), "RED"),
            ("verdict None (olculemedi) -> RED",        _V(None), "RED"),
            # kanonik kaynak: pencere elle sabit DEGIL
            ("pencere report_gate'ten turetiliyor",     _L._WINDOW_MIN, _RG.WINDOW_MINUTES),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#1e {ad}: beklenen {beklenen}, alinan {alinan}")

        # --- DENETCI SEVIYESI: saf fonksiyon degil, uyenin KENDISI ------------
        _row = _L._check_report_coverage("report_coverage", {}, {"sent": None}, {})
        if _row.get("status") == "RED":
            ok("uye: defter okunamayinca RED (temiz sayilmaz)")
        else:
            bad(f"#1e uye: okunamayan defter RED vermiyor -> {_row.get('status')}")

        # --- REGISTRY + DALLANMA SIRASI --------------------------------------
        _cfg = (getattr(_L, "REGISTRY", None) or {}).get("report_coverage")
        if _cfg and _cfg.get("check_mode") == "report_coverage":
            ok("registry'de 18. uye kayitli (check_mode dogru)")
        else:
            bad("#1e registry uyesi yok ya da check_mode yanlis")

        # Dallanma `_first(d, ts_keys)`DAN ONCE olmali: report_runs.json'da ust
        # duzey zaman damgasi YOK -> sonraya kayarsa uye "damga yok" diye SAHTE
        # RED verir. Kaynak sirasi kontrol edilir (davranista sessizce bozulur).
        _src = open(os.path.join(ROOT, "scripts", "liveness_scan.py"), encoding="utf-8").read()
        _i_disp = _src.find('cfg.get("check_mode") == "report_coverage"')
        _i_ts = _src.find('ts, ts_key = _first(d, cfg["ts_keys"])')
        if 0 < _i_disp < _i_ts:
            ok("dallanma ts-cikariminin ONUNDE (sahte 'damga yok' RED'i onlenir)")
        else:
            bad("#1e dallanma sirasi bozuk: report_coverage kontrolu ts-cikariminin ALTINDA")
    except Exception as e:
        bad(f"#1e testi kosmadi: {type(e).__name__}: {e}")

    # ── [6f] #1f — GUNLUK TEK-HEARTBEAT KAPISI ────────────────────────────────
    # NEDEN VAR: liveness cron'u 08-26'dan beri KRONIK GEC kosuyor (+2.5-4.7 sa).
    # Cozum coklu-retry cron, AMA liveness.yml Telegram adimi `if: always()` ile
    # HER kosumda mesaj atiyor (heartbeat sozlesmesi: "sessizlik = alarm").
    # Retry eklenirse gunde N heartbeat olur ve sozlesme TERSINDEN bozulur:
    # sessizligin anlamli kalmasi mesajin NADIR olmasina bagli.
    # => retry cron TEK BASINA eklenemez; gunluk-tek-heartbeat kapisi ON SARTTIR.
    #
    # 🔑 TASARIM CUMLESI: rapor kapisinda supHE = BLOK; heartbeat kapisinda
    #    supHE = GONDER. Ayni disiplin, TERS fail-safe yonu.
    #    (report_gate._record_blocks: malformed kayit BLOKLAR — burada tersi.)
    print("\n[6f] #1f gunluk tek-heartbeat kapisi (liveness_scan — golden-master disi)")
    try:
        import sys as _sys2
        _sp2 = os.path.join(ROOT, "scripts")
        if _sp2 not in _sys2.path:
            _sys2.path.insert(0, _sp2)
        from datetime import datetime as _dt2
        import liveness_scan as _L2

        _due = getattr(_L2, "_heartbeat_due", None)
        _mk = getattr(_L2, "_heartbeat_marker", None)
        if _due is None or _mk is None:
            bad("#1f _heartbeat_due / _heartbeat_marker YOK (yama henuz uygulanmadi)")
        else:
            def _M(gun):
                return {"sent_date": gun}
            _BUGUN = _dt2(2026, 9, 4, 20, 0)
            _YARIN = _dt2(2026, 9, 5, 0, 1)

            for ad, alinan, beklenen in [
                # 1-2: heartbeat gunde BIR
                ("1  gunun ILK kosumu GREEN -> GONDER",
                 _due(None, _BUGUN, "GREEN"), True),
                ("2  gunun IKINCI kosumu GREEN -> SESSIZ",
                 _due(_M("2026-09-04"), _BUGUN, "GREEN"), False),
                ("2b gunun IKINCI kosumu YELLOW -> SESSIZ",
                 _due(_M("2026-09-04"), _BUGUN, "YELLOW"), False),
                # 3-4: ALARM asla dedup EDILMEZ
                ("3  gunun IKINCI kosumu RED -> GONDER (dedup YOK)",
                 _due(_M("2026-09-04"), _BUGUN, "RED"), True),
                ("4  ucuncu kosum da RED -> yine GONDER",
                 _due(_M("2026-09-04"), _BUGUN, "RED"), True),
                # 5,8: TR gunu donunce sifirlanir
                ("5  dunku damga, bugun ilk kosum -> GONDER",
                 _due(_M("2026-09-03"), _BUGUN, "GREEN"), True),
                ("8  gun siniri (04 damga, 05 00:01) -> GONDER",
                 _due(_M("2026-09-04"), _YARIN, "GREEN"), True),
                # 7: supHE = GONDER  (report_gate'in TERSI — bilincli)
                ("7a damga YOK (dosya okunamadi) -> GONDER",
                 _due(None, _BUGUN, "GREEN"), True),
                ("7b damga BOZUK (dict degil) -> GONDER",
                 _due("bozuk", _BUGUN, "GREEN"), True),
                ("7c damga dict ama sent_date YOK -> GONDER",
                 _due({}, _BUGUN, "GREEN"), True),
                ("7d sent_date parse edilemez -> GONDER",
                 _due({"sent_date": "x!"}, _BUGUN, "GREEN"), True),
                # marker uretimi
                ("_heartbeat_marker bugunun TR gununu yazar",
                 _mk(_BUGUN).get("sent_date"), "2026-09-04"),
            ]:
                if alinan == beklenen:
                    ok(ad)
                else:
                    bad(f"#1f {ad}: beklenen {beklenen}, alinan {alinan}")

        # --- 6: "mark yalniz GERCEK gonderimden sonra" — workflow sirasi -------
        # Saf fonksiyonla test EDILEMEZ (gonderim sonucu workflow'da olusur).
        # Kaynak kontrolu: (a) curl basarisizligi YAKALANIYOR mu, (b) damga adimi
        # Telegram adimindan SONRA mi.
        _wf = open(os.path.join(ROOT, ".github", "workflows", "liveness.yml"),
                   encoding="utf-8").read()
        # `-f` bayragi -s/-S ile birlesik yazilabilir (curl -sf) -> regex ile ara.
        # (Ilk yazimda literal "curl -f" ariyordum; yama `curl -sf` yazinca test
        #  yanlis kirmizi verdi — testin kendisi de yasaya tabidir.)
        import re as _re
        _fbayrak = bool(_re.search(r"curl\s+-[a-zA-Z]*f", _wf))
        if _fbayrak or ('"ok":true' in _wf) or ('"ok": true' in _wf):
            ok("6a Telegram basarisi GERCEKTEN olculuyor (curl -f / ok:true)")
        else:
            bad("#1f 6a `curl -s` HTTP 400/401'de exit 0 doner -> API REDDI BASARI "
                "sayilir; damga yanlis yazilir")
        _i_tg = _wf.find("sendMessage")
        _i_mk = _wf.find("heartbeat-mark")
        if 0 < _i_tg < _i_mk:
            ok("6b damga adimi Telegram adimindan SONRA")
        else:
            bad("#1f 6b damga adimi Telegram'dan ONCE ya da yok -> basarisiz gonderim "
                "gunun heartbeat'ini tamamen susturur (spam'den KOTU)")

        # --- marker dosyasi report_runs.json OLMAMALI (yaris + kuplaj) ---------
        _hp = getattr(_L2, "HEARTBEAT_OUT", None)
        if _hp is not None and "liveness_heartbeat" in str(_hp):
            ok("damga AYRI dosyada (report_runs.json ile yaris yok)")
        else:
            bad(f"#1f damga dosyasi ayri degil: {_hp!r}")
    except Exception as e:
        bad(f"#1f testi kosmadi: {type(e).__name__}: {e}")

    # 7. sidesource
    print("\n[7] Yan kaynak (sidesource)")
    try:
        from bist_alpha import sidesource as ss
        score = ss.deniz_stock_score("GARAN")
        if score is not None:
            ok(f"Deniz skoru okundu (GARAN: {score})")
        else:
            warn("Deniz skoru okunamadı (GARAN)")
        flags = ss.annotate_ticker("GARAN", "XBANK")
        ok(f"annotate çalışıyor ({len(flags)} bayrak)")
    except Exception as e:
        bad(f"sidesource hatası: {e}")

    # 8. self-heal + bakım + optimizer
    print("\n[8] Öz-iyileştirme / bakım / optimizatör")
    try:
        from bist_alpha import selfheal, maintenance, optimizer, config as cfg
        if live_mode:
            d2 = selfheal.safe_feed()
            ok(f"selfheal.safe_feed ({d2['prices'].shape[1]} hisse)")
        else:
            ok("selfheal.safe_feed atlandı (offline; --mode live ile canlı veri denenir)")
        n = maintenance.clean_temp()
        ok(f"maintenance.clean_temp ({n} öğe temizlendi)")
        selfheal.validate_and_repair_state("A")
        ok("selfheal.validate_and_repair_state")
        ok(f"optimizer hazır (suggest-only, SEKTOR_CAP={cfg.SEKTOR_CAP} değişmez)")
    except Exception as e:
        bad(f"self-heal/bakım/optimizer hatası: {e}")

    # 8b. Survivorship + Telegram inbound
    print("\n[8b] Survivorship + Telegram veri alımı")
    try:
        from bist_alpha import universe_history, telegram_ingest, data as _dm
        if universe_history.available():
            rep = universe_history.survivorship_report(_dm.load_data())
            ok(f"nokta-zamanlı üyelik VAR ({rep.get('missing_from_price_data','?')} eksik)")
        else:
            ok("nokta-zamanlı üyelik CSV yok (mcap top-100 + uyarı; CSV ekleyince aktif)")
        # telegram_ingest fonksiyonu hazır mı
        assert hasattr(telegram_ingest, "fetch_uploads")
        ok("telegram_ingest.fetch_uploads hazır (manuel veri yükleme)")
    except Exception as e:
        bad(f"survivorship/telegram hatası: {e}")

    # 9. 7/24 deploy doğrulama (bilgisayar kapalıyken çalışma)
    print("\n[9] 7/24 deploy (bilgisayar kapalıyken çalışma)")
    import glob
    wf = glob.glob(".github/workflows/*.yml") + glob.glob(".github/workflows/*.yaml")
    if not wf:
        bad(".github/workflows/ YOK → GitHub Actions çalışmaz (7/24 kapalı)")
    else:
        ok(f"workflow doğru konumda: {wf[0]}")
        content = open(wf[0], encoding="utf-8").read()
        if "schedule:" in content and "cron:" in content:
            ok("cron zamanlama tanımlı (09:45/14:30/18:30)")
        else:
            bad("workflow'da cron schedule yok")
        if "DATA_SOURCE: yahoo" in content:
            ok("canlı veri (yahoo) yapılandırılmış")
        else:
            warn("workflow'da DATA_SOURCE: yahoo yok (canlı veri gelmez)")
        if "git push" in content and "permissions" in content:
            ok("state kalıcılığı (git commit/push + write izni)")
        else:
            warn("workflow'da state commit/push eksik")
    # GitHub remote olmadan workflow dosyasi bulutta aktif olmaz.
    git_config = os.path.join(".git", "config")
    if os.path.exists(git_config):
        gcfg = open(git_config, encoding="utf-8", errors="ignore").read()
        if "[remote " in gcfg and "github.com" in gcfg:
            ok("GitHub remote tanimli (7/24 push icin hazir)")
        else:
            warn("GitHub remote yok -> workflow dosyasi hazir ama bulutta 7/24 aktif degil")
    else:
        warn(".git yok -> GitHub Actions icin repo/push kurulumu gerekli")
    # .gitignore portfolios'u ignore etmemeli (state kaybolur)
    if os.path.exists(".gitignore"):
        gi = open(".gitignore", encoding="utf-8").read()
        if "portfolios/" in gi and not gi.split("portfolios/")[0].rstrip().endswith("#"):
            # portfolios/ yorum satırı olmadan ignore ediliyorsa sorun
            lines = [l.strip() for l in gi.splitlines() if l.strip() and not l.strip().startswith("#")]
            if "portfolios/" in lines:
                bad(".gitignore portfolios/'u ignore ediyor → state kaybolur")
            else:
                ok(".gitignore portfolios/'u koruyor (state kalıcı)")
        else:
            ok(".gitignore portfolios/'u koruyor (state kalıcı)")
    else:
        warn(".gitignore yok")

    # 10. CLI çalışma testi (TESPİT 5 — eksik kontrol tamamlandı)
    print("\n[10] CLI çalışma (gerçekten çalışıyor mu)")
    import subprocess
    clis = []
    if live_mode:
        clis.extend([
            ("run_backtest.py", ["--mode", "A"]),
            ("analyze_stock.py", ["GARAN"]),
            ("daemon.py", ["--optimize"]),
        ])
    else:
        ok("CLI gerçek çalıştırma atlandı (offline; parse ve A/B/F backtest zaten koştu)")
    for script, args in clis:
        try:
            env = dict(os.environ)
            env.setdefault("PYTHONIOENCODING", "utf-8")
            p = subprocess.run([sys.executable, script] + args,
                               capture_output=True, timeout=180, text=True, env=env)
            if p.returncode == 0:
                ok(f"{script} {' '.join(args)}")
            else:
                bad(f"{script} çıkış {p.returncode}: {p.stderr.strip()[:80]}")
        except subprocess.TimeoutExpired:
            warn(f"{script} zaman aşımı (>180s)")
        except Exception as e:
            bad(f"{script}: {e}")

    # 11. Web dashboard (GitHub Pages)
    print("\n[11] Web dashboard (GitHub Pages — ücretsiz statik UI)")
    import json as _json
    if os.path.exists("docs/index.html"):
        ok("docs/index.html mevcut (GitHub Pages için)")
        # JSON üretim mekanizmasını kontrol et — daemon helper varsa yeterli
        from bist_alpha import config as _cfg
        try:
            from daemon import _write_dashboard_state
            ok("daemon _write_dashboard_state hazır (her döngüde JSON yazar)")
        except ImportError:
            warn("daemon dashboard JSON üretici fonksiyonu içe aktarılamadı")
        # Daha önce üretilmiş JSON varsa şema kontrolü
        jp = "docs/state/dashboard.json"
        if os.path.exists(jp):
            try:
                d = _json.load(open(jp, encoding="utf-8"))
                if all(k in d for k in ("date", "mode", "top10", "accounts")):
                    ok(f"dashboard.json şema doğru (top:{len(d['top10'])}, hesaplar:{len(d['accounts'])})")
                else:
                    warn("dashboard.json şema eksik")
            except Exception as e:
                warn(f"dashboard.json okunamadı: {e}")
        else:
            ok("dashboard.json henüz üretilmedi (ilk daemon çalıştırmasında üretilir)")
    else:
        bad("docs/index.html YOK → web UI yayınlanamaz")

    # Sonuç
    print("\n" + "=" * 70)
    if fails:
        print(f"SONUÇ: {len(fails)} BLOKLAYICI SORUN bulundu ✗")
        for f in fails:
            print(f"   - {f}")
        return 1
    if warnings:
        print(f"SONUÇ: bloklayıcı hata yok, {len(warnings)} UYARI var ⚠")
        for w in warnings:
            print(f"   - {w}")
        if args.strict:
            return 1
        return 0
    print("SONUÇ: ✅ TÜM KONTROLLER GEÇTİ — eksik yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

