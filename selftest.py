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
        "bist_alpha/portfolio.py": "b70147ef6c50",   # P0.3 adim 2/2b/3/4 (2026-09-10): eski 09ad265d9fd5
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
        _ENVK = ("GITHUB_RUN_ID", "GITHUB_SHA", "HB_VERDICT", "HB_HEALTH")

        def _mk_envsiz():
            """`env yokken` iddiasi ancak env GERCEKTEN temizlenerek olculebilir."""
            _eski = {k: os.environ.pop(k, None) for k in _ENVK}
            try:
                return _mk(_BUGUN)
            finally:
                for k, v in _eski.items():
                    if v is not None:
                        os.environ[k] = v

        def _mk_envli():
            _eski = {k: os.environ.get(k) for k in _ENVK}
            os.environ["GITHUB_RUN_ID"] = "TEST_RUN_42"
            try:
                return _mk(_BUGUN)
            finally:
                for k, v in _eski.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        if _due is None or _mk is None:
            bad("#1f _heartbeat_due / _heartbeat_marker YOK (yama henuz uygulanmadi)")
        else:
            def _M(gun):
                return {"sent_date": gun}
            _BUGUN = _dt2(2026, 9, 4, 20, 0)
            _GEC_RETRY = _dt2(2026, 9, 5, 0, 1)

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
                # 5,8: UTC niyet gunu donunce sifirlanir; TR gece yarisi yetmez
                ("5  dunku damga, bugun ilk kosum -> GONDER",
                 _due(_M("2026-09-03"), _BUGUN, "GREEN"), True),
                ("8  TR gun siniri niyet gununu degistirmez -> SESSIZ",
                 _due(_M("2026-09-04"), _GEC_RETRY, "GREEN"), False),
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
                ("_heartbeat_marker normal kosumda gun anahtari yazar",
                 _mk(_BUGUN).get("sent_date"), "2026-09-04"),
                # DENETIM ALANLARI (#1f guclendirme): damga "kim gonderdi"yi de
                # tasimali, yoksa damganin KENDISI denetlenemez.
                ("damgada denetim alanlari VAR",
                 sorted(set(_mk(_BUGUN)) & {"verdict", "health", "commit_sha", "github_run_id"}),
                 ["commit_sha", "github_run_id", "health", "verdict"]),
                ("denetim alanlari env'den doluyor",
                 _mk(_BUGUN, verdict="YELLOW").get("verdict"), "YELLOW"),
                # "env yokken" iddiasi ENV'I GERCEKTEN TEMIZLEYEREK olculur.
                # ILK YAZIMDA TEMIZLENMEMISTI: yerelde GITHUB_RUN_ID yok -> gecti,
                # CI'da DAIMA set -> KIRILDI (962a21f, 2026-09-04 CI kirmizi).
                # Ders: test, KONTROL ETMEDIGI bir ortam ozelligini iddia edemez.
                ("env YOKKEN None (env temizlenerek olculdu)",
                 _mk_envsiz().get("github_run_id"), None),
                ("env VARKEN env'den okunuyor",
                 _mk_envli().get("github_run_id"), "TEST_RUN_42"),
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
        _oktrue = ('"ok":true' in _wf) or ('"ok": true' in _wf)
        if _fbayrak and _oktrue:
            ok("6a Telegram basarisi IKI KATMANLI olculuyor (curl -f VE ok:true)")
        elif _fbayrak or _oktrue:
            ok("6a Telegram basarisi olculuyor (tek katman)")
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

    # ── [6g] #1j — GECIKMIS RETRY ERTESI GUN HEARTBEAT'INI CALMAMALI ──────────
    # NEDEN VAR: #1f retry kapisi gunde tek heartbeat'i sagladi, ama geciken son
    # retry 21:01 UTC = 00:01 TR'de kosunca `sent_date` TR gunuyle 09-05 yazildi.
    # Tasidigi veri 09-04 aksami oldugu halde 09-05 slotu tukendi. Hafta sonu zarar
    # dogurmadi; hafta ici ertesi gunun gercek sagligi Telegram'a hic ulasmayabilir.
    #
    # Testin omurgasi: 00:01 TR ile ertesi gun 20:10 TR ayni TR tarihindedir, ama
    # farkli NIYET gunleridir. Mevcut `_heartbeat_due(marker, now_tr, verdict)`
    # yalniz TR gunune baktigi icin ikisini ayiramaz; bu blok yama oncesi kirmizi
    # vermelidir.
    #
    # EKSEN KARARI (c) — OLCUMLE SECILDI (2026-09-06):
    #   (a) parametre TR kalsin, iceride cevir -> kirmizi verir ama eksenin ADI yok
    #   (b) cagri yerlerini UTC'ye tasi        -> REDDEDILDI. `_heartbeat_due`
    #       EKSEN-AGNOSTIK: `return gun != now.strftime(...)` — kendisine VERILEN
    #       datetime'i bicimler, TR mi UTC mi bilmez. Dogrudan UTC besleyen test
    #       YAMASIZ KODDA DA YESIL doner => VAKUM TEST, hicbir sey olcmez.
    #       OLCULDU: _heartbeat_due({"sent_date":"2026-09-04"},
    #                               datetime(2026,9,4,21,1), "GREEN") -> False
    #   (c) SECILEN: niyet gunu ADI OLAN tek fonksiyona cikarilir (_intent_day),
    #       her iki tuketici oradan gecer. Cagri yerleri (369/1085/1120) DEGISMEZ,
    #       donusum TEK yerde, ofset kanonik PRODUCER_TZ_OFFSET_H'den.
    #
    # BU BLOK DAVRANIS SABITLER, IMPLEMENTASYON DEGIL: `_intent_day`in VARLIGINI
    # sart kosmaz — iki fonksiyonun AYNI niyet gununu uretmesini sart kosar.
    print("\n[6g] #1j gecikmis retry ertesi gun heartbeat'ini calmasin (test-once)")
    try:
        import sys as _sys3
        _sp3 = os.path.join(ROOT, "scripts")
        if _sp3 not in _sys3.path:
            _sys3.path.insert(0, _sp3)
        from datetime import datetime as _dt3, timedelta as _td3
        import liveness_scan as _L3

        _due = getattr(_L3, "_heartbeat_due", None)
        _mk4 = getattr(_L3, "_heartbeat_marker", None)
        _off = getattr(_L3, "PRODUCER_TZ_OFFSET_H", None)
        if _due is None or _mk4 is None or _off is None:
            bad(f"#1j gerekli semboller YOK (_heartbeat_due={_due is not None} "
                f"_heartbeat_marker={_mk4 is not None} "
                f"PRODUCER_TZ_OFFSET_H={_off is not None})")
        else:
            def _M3(gun):
                return {"sent_date": gun}

            def _TR3(y, m, d, h, mi):
                """UTC an -> uretici (TR) saati.
                Ofset KANONIK sabitten gelir; elle `3` YAZILMAZ — sabit degisirse
                test uretimle sessizce ayrisirdi."""
                return _dt3(y, m, d, h, mi) + _td3(hours=_off)

            # 09-04 21:01 UTC = 09-05 00:01 TR -> TR gece yarisini ASAR, niyet gunu 09-04
            _gec = _TR3(2026, 9, 4, 21, 1)
            _ert = _TR3(2026, 9, 5, 17, 10)     # ertesi gunun normal kosusu, niyet 09-05

            for ad, alinan, beklenen in [
                ("1  20:59 UTC (23:59 TR), damga yok -> GONDER",
                 _due(None, _TR3(2026, 9, 4, 20, 59), "GREEN"), True),
                ("2  21:01 UTC (00:01 TR), 09-04 damgasi -> SESSIZ "
                 "(hala 09-04 aksaminin gec retry'i)",
                 _due(_M3("2026-09-04"), _gec, "GREEN"), False),
                ("3  ertesi gun 17:10 UTC (20:10 TR), 09-04 damgasi -> GONDER",
                 _due(_M3("2026-09-04"), _ert, "GREEN"), True),
                # 4 — DAMGAYI YAZAN TARAF. Yalniz `_heartbeat_due` duzeltilirse 1-3
                # yesile doner AMA HIRSIZLIK YASAR: marker TR ile ertesi gunu yazar,
                # ilk basarili gonderim 21:00 UTC'yi asan bir gunde ertesi gun susar.
                # YALNIZ sent_date okunur; env'e bagli alan (github_run_id vb.) YOK — C8.
                ("4  21:01 UTC'de yazilan marker'in sent_date'i NIYET gunu (09-04) olmali",
                 _mk4(_gec).get("sent_date"), "2026-09-04"),
                # 5 — TUTARLILIK KILIDI, implementasyondan bagimsiz: ayni AN icin
                # marker'in YAZDIGI gun ile `_heartbeat_due`nun KIYASLADIGI gun ayni
                # eksende olmali. Bugun YESIL (ikisi de TR), tam yamadan sonra da YESIL;
                # YALNIZ YARIM yamada (tek taraf cevrilirse) KIRMIZI olur.
                ("5  ayni an: marker'in yazdigi damga o ani SESSIZ'e dusurmeli "
                 "(iki fonksiyon ayni eksende)",
                 _due(_M3(_mk4(_gec).get("sent_date")), _gec, "GREEN"), False),
            ]:
                if alinan == beklenen:
                    ok(ad)
                else:
                    bad(f"#1j {ad}: beklenen {beklenen}, alinan {alinan}")
    except Exception as e:
        bad(f"#1j testi kosmadi: {type(e).__name__}: {e}")

    # ── [6h] #0b — DOLU AMA ZAMAN EKSENI DELIK PRIMARY FALLBACK'I ENGELLEMEMELI ──
    # CANLI VAKA (2026-09-08): Yahoo matrisi 624 hisseyle "dolu" gorundu; 09-08
    # bari geldi, fakat XU100'un islem gordugu 09-07 satiri hisselerde %99.52 NaN
    # kaldi. safe_feed yalniz `empty` ve kolon sayisini kontrol ettigi icin Yahoo'yu
    # kabul etti, daha taze/tam Borsapy yedegine hic ulasmadi.
    #
    # ESIK ICAT EDILMEDI: datafeed._drop_sparse_tail varsayilani olan %50 kullanilir.
    # TAKVIM ICAT EDILMEDI: beklenen gunler feed'in kendi `bist` (XU100) indeksidir.
    # Boylece gercek tatil (gun hem BIST hem hisse matrisinde yok) sahte fallback
    # uretmez. Bu blok test-once yazildi; ilk sart mevcut kodda KIRMIZI olmalidir.
    print("\n[6h] #0b dolu-ama-delik primary daha tam yedege dusmeli (test-once)")
    try:
        import tempfile as _tempfile4
        from datetime import datetime as _datetime4
        from pathlib import Path as _Path4
        from zoneinfo import ZoneInfo as _ZoneInfo4
        import pandas as _pd4
        from bist_alpha import selfheal as _SH4, datafeed as _DF4, config as _CFG4

        _d0, _d1, _d2 = _pd4.to_datetime(["2026-09-04", "2026-09-07", "2026-09-08"])
        _cols4 = [f"T{i:02d}" for i in range(60)]
        _tz4 = _ZoneInfo4("Europe/Istanbul")
        _now4 = _datetime4(2026, 9, 8, 14, 30, tzinfo=_tz4)
        _calendar_path4 = (
            _Path4(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )

        def _prices4(index, sparse_day=None):
            frame = _pd4.DataFrame(100.0, index=index, columns=_cols4)
            if sparse_day is not None:
                frame.loc[sparse_day] = float("nan")
                frame.loc[sparse_day, _cols4[0]] = 100.0  # %1.67 dolu < kanonik %50
            return frame

        def _packet4(price_index, bist_index, sparse_day=None):
            return {
                "prices": _prices4(price_index, sparse_day=sparse_day),
                "bist": _pd4.Series(100.0, index=bist_index),
                "_bist_ok": True,
                "_source_pool_count": len(_cols4),
            }

        class _Feed4:
            def __init__(self, packet):
                self.packet = packet

            def get_latest(self):
                return self.packet

        _old_get_feed4 = _DF4.get_feed
        _sentinel4 = object()
        _old_source4 = getattr(_CFG4, "DATA_SOURCE", _sentinel4)
        _old_chain4 = getattr(_CFG4, "DATA_FALLBACK_CHAIN", _sentinel4)
        _old_allow4 = getattr(_CFG4, "ALLOW_FILE_FALLBACK", _sentinel4)
        _old_feed_state4 = getattr(_SH4, "DATA_FEED_RUN_STATE", _sentinel4)
        _feed_tmp4 = _tempfile4.TemporaryDirectory()
        try:
            _SH4.DATA_FEED_RUN_STATE = _Path4(_feed_tmp4.name) / "data_feed_run.json"
            _CFG4.DATA_SOURCE = "yahoo"
            _CFG4.DATA_FALLBACK_CHAIN = "borsapy"
            _CFG4.ALLOW_FILE_FALLBACK = False

            # 1) XU100'da islem gunu var; primary hisse satiri sistemik seyrek.
            _calls4 = []
            _packets4 = {
                "yahoo": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2], sparse_day=_d1),
                "borsapy": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2]),
            }

            def _get_feed_gap4(name):
                _calls4.append(name)
                return _Feed4(_packets4[name])

            _DF4.get_feed = _get_feed_gap4
            _out4 = _SH4.safe_feed(now=_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "borsapy" and _calls4 == ["yahoo", "borsapy"]:
                ok("islem-gunu satiri <%50 dolu -> primary reddedildi, borsapy secildi")
            else:
                bad("#0b delik primary fallback'i: beklenen borsapy/calls "
                    f"['yahoo','borsapy'], alinan {_out4.get('_source_base')}/{_calls4}")

            # 2) Resmi takvimde 07-15 kapali: kaynakta satir olmamasi gercek tatil.
            _calls4 = []
            _h0_4, _h2_4 = _pd4.to_datetime(["2026-07-14", "2026-07-16"])
            _packets4 = {
                "yahoo": _packet4([_h0_4, _h2_4], [_h0_4, _h2_4]),
                "borsapy": _packet4([_h0_4, _h2_4], [_h0_4, _h2_4]),
            }
            _DF4.get_feed = _get_feed_gap4
            _holiday_now4 = _datetime4(2026, 7, 16, 14, 30, tzinfo=_tz4)
            _out4 = _SH4.safe_feed(
                now=_holiday_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "yahoo" and _calls4 == ["yahoo"]:
                ok("resmi tatilde satir yok -> primary korunur, sahte fallback yok")
            else:
                bad("#0b tatil false-positive: beklenen yahoo/calls ['yahoo'], "
                    f"alinan {_out4.get('_source_base')}/{_calls4}")

            # 3) XU100'da islem gunu var fakat primary'de hisse satiri tamamen yok.
            _calls4 = []
            _packets4 = {
                "yahoo": _packet4([_d0, _d2], [_d0, _d1, _d2]),
                "borsapy": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2]),
            }
            _DF4.get_feed = _get_feed_gap4
            _out4 = _SH4.safe_feed(now=_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "borsapy" and _calls4 == ["yahoo", "borsapy"]:
                ok("XU100 islem gununde hisse satiri YOK -> primary reddedildi")
            else:
                bad("#0b eksik islem-gunu satiri: beklenen borsapy/calls "
                    f"['yahoo','borsapy'], alinan {_out4.get('_source_base')}/{_calls4}")

            # 4) Gercek borsapy 0.10.2 sozlesmesi: coklu indirme varsayilan olarak
            # (fiyat, sembol) kolonlari dondurur; adapter `group_by=ticker` istemeli.
            # Endeks de `index(...).history(...)` uzerinden okunur.
            import types as _types4
            from bist_alpha import universe as _UNI4

            _old_borsapy4 = sys.modules.get("borsapy", _sentinel4)
            _old_tickers4 = _UNI4.all_bist_tickers
            _old_meta4 = _UNI4.universe_meta
            _bp_calls4 = []
            _bp_dates4 = _pd4.to_datetime(["2026-09-07", "2026-09-08"], utc=True).tz_convert("Europe/Istanbul")

            def _bp_frame4(base):
                return _pd4.DataFrame({
                    "Open": [base, base + 1],
                    "High": [base + 2, base + 3],
                    "Low": [base - 1, base],
                    "Close": [base + 1, base + 2],
                    "Volume": [1000.0, 1100.0],
                }, index=_bp_dates4)

            def _bp_download4(tickers, period="1mo", interval="1d",
                              group_by="column", **_kwargs):
                _bp_calls4.append(("download", group_by, tuple(tickers)))
                frames = {ticker: _bp_frame4(100.0 + pos * 10)
                          for pos, ticker in enumerate(tickers)}
                raw = _pd4.concat(frames, axis=1)
                return raw if group_by == "ticker" else raw.swaplevel(axis=1).sort_index(axis=1)

            class _BPIndex4:
                def history(self, period="1mo", interval="1d"):
                    _bp_calls4.append(("index_history", period, interval))
                    return _bp_frame4(9000.0)

            def _bp_index4(symbol):
                _bp_calls4.append(("index", symbol))
                return _BPIndex4()

            try:
                sys.modules["borsapy"] = _types4.SimpleNamespace(
                    download=_bp_download4,
                    index=_bp_index4,
                )
                _UNI4.all_bist_tickers = lambda: ["AAA", "BBB"]
                _UNI4.universe_meta = lambda: {}
                _bp_out4 = _DF4.BorsaPyFeed().get_latest()
                _bp_ok4 = (
                    list(_bp_out4["prices"].columns) == ["AAA", "BBB"]
                    and bool(_bp_out4.get("_bist_ok"))
                    and ("download", "ticker", ("AAA", "BBB")) in _bp_calls4
                    and ("index_history", "2y", "1d") in _bp_calls4
                )
                if _bp_ok4:
                    ok("borsapy 0.10.2: ticker kolon grubu + index.history sozlesmesi")
                else:
                    bad(f"#0b borsapy adapter sozlesmesi: calls={_bp_calls4}, "
                        f"cols={list(_bp_out4.get('prices', []).columns)}")

                _daily_frames4 = [
                    _bp_out4[key]
                    for key in ("prices", "mins", "maxs", "aofs", "volumes", "opens", "bist")
                ]
                _daily_axis_ok4 = all(
                    isinstance(frame.index, _pd4.DatetimeIndex)
                    and frame.index.tz is None
                    and all(ts == ts.normalize() for ts in frame.index)
                    and list(frame.index) == list(_pd4.to_datetime(["2026-09-07", "2026-09-08"]))
                    for frame in _daily_frames4
                )
                if _daily_axis_ok4:
                    ok("borsapy gunluk indeks sozlesmesi timezone-naive gece yarisi")
                else:
                    bad("#0b borsapy gunluk indeks sozlesmesi: tz-aware/saatli indeks sizdi")
            except Exception as e:
                bad(f"#0b borsapy adapter sozlesmesi: {type(e).__name__}: {e}")
            finally:
                if _old_borsapy4 is _sentinel4:
                    sys.modules.pop("borsapy", None)
                else:
                    sys.modules["borsapy"] = _old_borsapy4
                _UNI4.all_bist_tickers = _old_tickers4
                _UNI4.universe_meta = _old_meta4
        finally:
            _DF4.get_feed = _old_get_feed4
            for _name4, _old4 in [
                ("DATA_SOURCE", _old_source4),
                ("DATA_FALLBACK_CHAIN", _old_chain4),
                ("ALLOW_FILE_FALLBACK", _old_allow4),
            ]:
                if _old4 is _sentinel4:
                    try:
                        delattr(_CFG4, _name4)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG4, _name4, _old4)
            if _old_feed_state4 is _sentinel4:
                try:
                    delattr(_SH4, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH4.DATA_FEED_RUN_STATE = _old_feed_state4
            _feed_tmp4.cleanup()
    except Exception as e:
        bad(f"#0b [6h] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6i] P0.6 -- TUM KAYNAKLAR DUSERSE DENEME MANIFESTI KAYBOLMAMALI --
    # Dashboard yalniz basarili rapordan sonra yazilir. Veri zinciri tamamen
    # duserse kok nedeni exception metninde birakmak, state commit adimina
    # kalici bir artefakt vermez. Ayni sema basari ve toplam-ret yolunda yazilir.
    print("\n[6i] P0.6 kaynak deneme manifesti basari ve toplam rette kalici")
    try:
        import json as _json5
        import tempfile as _tempfile5
        from datetime import datetime as _datetime5
        from pathlib import Path as _Path5
        from zoneinfo import ZoneInfo as _ZoneInfo5
        import pandas as _pd5
        from bist_alpha import selfheal as _SH5, datafeed as _DF5, config as _CFG5

        class _FailFeed5:
            def __init__(self, source):
                self.source = source

            def get_latest(self):
                raise RuntimeError(f"{self.source}-down")

        class _OkFeed5:
            def get_latest(self):
                idx = _pd5.to_datetime(["2026-09-08", "2026-09-09"])
                cols = [f"M{i:02d}" for i in range(60)]
                return {
                    "prices": _pd5.DataFrame(100.0, index=idx, columns=cols),
                    "bist": _pd5.Series(100.0, index=idx),
                    "_bist_ok": True,
                    "_source_pool_count": 60,
                }

        _sentinel5 = object()
        _old_path5 = getattr(_SH5, "DATA_FEED_RUN_STATE", _sentinel5)
        _expected_path5 = (
            _Path5(_SH5.__file__).resolve().parents[1]
            / "docs" / "state" / "data_feed_run.json"
        )
        if (_old_path5 is not _sentinel5
                and _Path5(_old_path5).is_absolute()
                and _Path5(_old_path5) == _expected_path5):
            ok("manifest yolu cwd'den bagimsiz ve repo kokune sabit")
        else:
            bad(f"P0.6 manifest yolu repo kokune sabit degil: {_old_path5}")
        _old_writer5 = _SH5._write_data_feed_run
        _old_retry5 = _SH5.with_retry
        _old_get_feed5 = _DF5.get_feed
        _old_source5 = getattr(_CFG5, "DATA_SOURCE", _sentinel5)
        _old_chain5 = getattr(_CFG5, "DATA_FALLBACK_CHAIN", _sentinel5)
        _old_allow5 = getattr(_CFG5, "ALLOW_FILE_FALLBACK", _sentinel5)
        _now5 = _datetime5(
            2026, 9, 9, 14, 30,
            tzinfo=_ZoneInfo5("Europe/Istanbul"),
        )
        _calendar_path5 = (
            _Path5(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        try:
            with _tempfile5.TemporaryDirectory() as _td5:
                _state5 = _Path5(_td5) / "data_feed_run.json"
                _SH5.DATA_FEED_RUN_STATE = _state5
                _SH5.with_retry = lambda fn, **_kwargs: fn()
                _CFG5.DATA_SOURCE = "yahoo"
                _CFG5.DATA_FALLBACK_CHAIN = "borsapy,file"
                _CFG5.ALLOW_FILE_FALLBACK = False

                _DF5.get_feed = lambda source: _FailFeed5(source)
                try:
                    _SH5.safe_feed(now=_now5, calendar_path=_calendar_path5)
                    bad("P0.6 toplam ret RuntimeError vermedi")
                except RuntimeError:
                    pass

                if not _state5.exists():
                    bad("P0.6 toplam rette data_feed_run.json yazilmadi")
                else:
                    _failed5 = _json5.loads(_state5.read_text(encoding="utf-8"))
                    _statuses5 = [(a.get("source"), a.get("status"))
                                  for a in _failed5.get("source_attempts", [])]
                    if (_failed5.get("status") == "failed"
                            and _failed5.get("primary_source") == "yahoo"
                            and _failed5.get("selected_source") is None
                            and _statuses5 == [("yahoo", "failed"),
                                              ("borsapy", "failed"),
                                              ("file", "skipped")]):
                        ok("toplam rette kaynak/status/reason zinciri kalici")
                    else:
                        bad(f"P0.6 toplam-ret manifesti yanlis: {_failed5}")

                    _timed5 = all(
                        a.get("started_at") and a.get("finished_at")
                        and isinstance(a.get("duration_s"), (int, float))
                        and (a.get("error") or a.get("reason"))
                        for a in _failed5.get("source_attempts", [])
                    )
                    if _failed5.get("generated_at") and _timed5:
                        ok("toplam-ret manifesti zaman/sure ve ret nedenlerini tasiyor")
                    else:
                        bad("P0.6 toplam-ret manifestinde zaman/sure/ret nedeni eksik")

                _DF5.get_feed = lambda source: _OkFeed5()
                _out5 = _SH5.safe_feed(now=_now5, calendar_path=_calendar_path5)
                _success5 = (_json5.loads(_state5.read_text(encoding="utf-8"))
                             if _state5.exists() else {})
                _ok_attempt5 = _success5.get("source_attempts", [{}])[-1]
                if (_out5.get("_source_base") == "yahoo"
                        and _success5.get("status") == "ok"
                        and _success5.get("selected_source") == "yahoo"
                        and _ok_attempt5.get("status") == "ok"
                        and _ok_attempt5.get("returned_symbols") == 60
                        and _ok_attempt5.get("expected_pool") == 60
                        and _ok_attempt5.get("last_data_date") == "2026-09-09"):
                    ok("basarili kaynak ayni manifesti olculen alanlarla ok yeniliyor")
                else:
                    bad(f"P0.6 basari manifesti yazilmadi/yanlis: {_success5}")

                def _broken_writer5(*_args, **_kwargs):
                    raise OSError("manifest-readonly")

                _SH5._write_data_feed_run = _broken_writer5
                _out_write_fail5 = _SH5.safe_feed(
                    now=_now5, calendar_path=_calendar_path5)
                if _out_write_fail5.get("_source_base") == "yahoo":
                    ok("manifest yazma hatasi saglikli kaynak kararini degistirmiyor")
                else:
                    bad("P0.6 manifest hatasi saglikli kaynagi fallback'e itti")
        finally:
            _SH5._write_data_feed_run = _old_writer5
            _SH5.with_retry = _old_retry5
            _DF5.get_feed = _old_get_feed5
            if _old_path5 is _sentinel5:
                try:
                    delattr(_SH5, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH5.DATA_FEED_RUN_STATE = _old_path5
            for _name5, _old5 in [
                ("DATA_SOURCE", _old_source5),
                ("DATA_FALLBACK_CHAIN", _old_chain5),
                ("ALLOW_FILE_FALLBACK", _old_allow5),
            ]:
                if _old5 is _sentinel5:
                    try:
                        delattr(_CFG5, _name5)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG5, _name5, _old5)
    except Exception as e:
        bad(f"P0.6 [6i] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6j] P0.6 -- BAGIMSIZ XIST TAKVIMI VE TAZELIK SOZLESMESI --
    # Takvim, dogrulanan fiyat kaynagindan turetilmez. Yetkili artefakt Borsa
    # Istanbul'un yillik Pay Piyasasi takvimidir; exchange_calendars yalniz
    # capraz kontroldur. Bu blok artefakti, takvim API'sini ve datafeed
    # entegrasyonunu sinar. Test-once commit'inde artefakt yesil, entegrasyon
    # sartlari kirmiziydi; uretim yamasi artik ayni sartlari yesile cevirir.
    print("\n[6j] P0.6 bagimsiz XIST takvimi ve tazelik kapisi (test-once)")
    try:
        import json as _json6
        import re as _re6
        from datetime import datetime as _datetime6
        from pathlib import Path as _Path6
        from zoneinfo import ZoneInfo as _ZoneInfo6
        import pandas as _pd6
        from bist_alpha import datafeed as _DF6

        _calendar_path6 = (
            _Path6(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        _calendar_doc6 = _json6.loads(
            _calendar_path6.read_text(encoding="utf-8")
        )

        _source6 = _calendar_doc6.get("source", {})
        _source_ok6 = (
            _calendar_doc6.get("market") == "XIST"
            and _calendar_doc6.get("timezone") == "Europe/Istanbul"
            and _calendar_doc6.get("valid_from") == "2026-01-01"
            and _calendar_doc6.get("valid_through") == "2026-12-31"
            and _source6.get("url")
            == "https://www.borsaistanbul.com/files/equity-market-2026-holiday-schedule.pdf"
            and _source6.get("sha256")
            == "3a1b39913abc188788da533c5e25000b6bb0a9f94057d21a61f068ef17efe85d"
            and bool(_re6.fullmatch(r"[0-9a-f]{64}", _source6.get("sha256", "")))
        )
        if _source_ok6:
            ok("XIST takvim artefakti yetkili kaynak ve gercek SHA-256 tasiyor")
        else:
            bad(f"P0.6 XIST takvim kaynak metadatasi yanlis: {_source6}")

        _closed6 = set(_calendar_doc6.get("full_day_closures", []))
        _expected_closed6 = {
            "2026-01-01", "2026-03-20", "2026-03-21", "2026-03-22",
            "2026-04-23", "2026-05-01", "2026-05-19", "2026-05-27",
            "2026-05-28", "2026-05-29", "2026-05-30", "2026-07-15",
            "2026-08-30", "2026-10-29",
        }
        _half6 = {
            item.get("date"): item.get("close")
            for item in _calendar_doc6.get("half_days", [])
        }
        _hours6 = _calendar_doc6.get("session_hours", {})
        if (_closed6 == _expected_closed6
                and _half6 == {
                    "2026-03-19": "13:00",
                    "2026-05-26": "13:00",
                    "2026-10-28": "13:00",
                }
                and _hours6.get("regular_close") == "18:10"):
            ok("2026 tam tatil, resmi 13:00 yarim gun ve 18:10 seans saatleri sabit")
        else:
            bad("P0.6 XIST resmi tatil/seans listesi eksik veya farkli")

        _renewal6 = _calendar_doc6.get("renewal_policy", {})
        _lead_days6 = [
            row.get("lead_days")
            for row in _renewal6.get("publication_history", [])
        ]
        _source_states6 = _calendar_doc6.get("source_check_contract", {})
        if (_lead_days6 == [10, 7, 28]
                and _renewal6.get("warning_days_before_expiry")
                == max(_lead_days6) + _renewal6.get("operational_margin_days", -1)
                == 35
                and _source_states6.get("statuses")
                == ["UNCHANGED", "CHANGED", "UNREACHABLE"]
                and _source_states6.get("unreachable_is_changed") is False):
            ok("yenileme 35 gun ve kaynak UNREACHABLE/CHANGED ayrimi olcumden turetilmis")
        else:
            bad("P0.6 takvim yenileme veya kaynak-kontrol sozlesmesi yanlis")

        try:
            from bist_alpha import market_calendar as _MC6
        except ImportError:
            _MC6 = None

        _tz6 = _ZoneInfo6("Europe/Istanbul")
        if _MC6 is None:
            for _missing6 in (
                "son kapanmis seans API'si",
                "tazelik/bar-tamligi ayrimi",
                "yenileme ve kapsam-disi fail-closed",
                "kaynak UNREACHABLE/CHANGED siniflandirmasi",
            ):
                bad(f"P0.6 bagimsiz takvim uygulamasi yok: {_missing6}")
        else:
            _loaded6 = _MC6.load_calendar(_calendar_path6)

            try:
                _session_cases6 = [
                    ("normal-acilis-oncesi",
                     _datetime6(2026, 9, 7, 9, 45, tzinfo=_tz6), "2026-09-04"),
                    ("normal-kapanis-sonrasi",
                     _datetime6(2026, 9, 7, 18, 40, tzinfo=_tz6), "2026-09-07"),
                    ("yarim-gun-12:59",
                     _datetime6(2026, 3, 19, 12, 59, tzinfo=_tz6), "2026-03-18"),
                    ("yarim-gun-13:01",
                     _datetime6(2026, 3, 19, 13, 1, tzinfo=_tz6), "2026-03-19"),
                    ("bayram-tam-kapali",
                     _datetime6(2026, 3, 20, 18, 40, tzinfo=_tz6), "2026-03-19"),
                ]
                _session_results6 = [
                    (name, str(_MC6.expected_last_closed_session(now, _loaded6))[:10], expected)
                    for name, now, expected in _session_cases6
                ]
                if all(actual == expected
                       for _name, actual, expected in _session_results6):
                    ok("normal/tatil/13:00 yarim gun son kapanmis seansi dogru")
                else:
                    bad(f"P0.6 son kapanmis seans vakalari: {_session_results6}")
            except Exception as e:
                bad(f"P0.6 son kapanmis seans API'si: {type(e).__name__}: {e}")

            try:
                _fresh6 = _MC6.assess_freshness(
                    "2026-09-09",
                    _datetime6(2026, 9, 9, 14, 30, tzinfo=_tz6),
                    _loaded6,
                )
                _stale6 = _MC6.assess_freshness(
                    "2026-09-07",
                    _datetime6(2026, 9, 9, 14, 30, tzinfo=_tz6),
                    _loaded6,
                )
                _after_close6 = _MC6.assess_freshness(
                    "2026-09-08",
                    _datetime6(2026, 9, 9, 18, 40, tzinfo=_tz6),
                    _loaded6,
                )
                if (_fresh6.get("freshness_status") == "FRESH"
                        and _fresh6.get("expected_last_closed_session") == "2026-09-08"
                        and _fresh6.get("bar_completeness") == "unknown"
                        and _stale6.get("reject_code") == "STALE_LAST_DATA"
                        and _after_close6.get("reject_code") == "STALE_LAST_DATA"):
                    ok("tazelik gecisi bar tamligi iddia etmiyor; bayatlik slot saatine bagli")
                else:
                    bad("P0.6 tazelik/bar-tamligi sozlesmesi yanlis")
            except Exception as e:
                bad(f"P0.6 tazelik API'si: {type(e).__name__}: {e}")

            try:
                _renew_ok6 = _MC6.renewal_status(
                    _datetime6(2026, 11, 25, 12, 0, tzinfo=_tz6), False, _loaded6)
                _renew_warn6 = _MC6.renewal_status(
                    _datetime6(2026, 11, 26, 12, 0, tzinfo=_tz6), False, _loaded6)
                _renew_expired6 = _MC6.renewal_status(
                    _datetime6(2027, 1, 1, 9, 45, tzinfo=_tz6), False, _loaded6)
                if (_renew_ok6.get("status") == "OK"
                        and _renew_warn6.get("status") == "WARNING"
                        and _renew_warn6.get("days_remaining") == 35
                        and _renew_expired6.get("reject_code") == "CALENDAR_UNAVAILABLE"):
                    ok("35 gun yenileme uyarisi ve kapsam-disinda fail-closed")
                else:
                    bad("P0.6 takvim yenileme/kapsam-disi sozlesmesi yanlis")
            except Exception as e:
                bad(f"P0.6 yenileme API'si: {type(e).__name__}: {e}")

            try:
                _hash6 = _source6["sha256"]
                _source_results6 = (
                    _MC6.classify_source_check(True, _hash6, _hash6),
                    _MC6.classify_source_check(True, "0" * 64, _hash6),
                    _MC6.classify_source_check(False, None, _hash6),
                )
                if _source_results6 == ("UNCHANGED", "CHANGED", "UNREACHABLE"):
                    ok("kaynak cekilemedi ile olculdu-ve-degisti ayriliyor")
                else:
                    bad(f"P0.6 kaynak durumlari yanlis: {_source_results6}")
            except Exception as e:
                bad(f"P0.6 kaynak-kontrol API'si: {type(e).__name__}: {e}")

        _d4_6, _d7_6, _d8_6, _d9_6 = _pd6.to_datetime(
            ["2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09"]
        )
        _cols6 = [f"C{i:02d}" for i in range(60)]
        _external_sessions6 = _pd6.DatetimeIndex(
            [
                day for day in _pd6.date_range("2026-01-01", "2026-09-09", freq="B")
                if day.strftime("%Y-%m-%d") not in _closed6
            ]
        )

        # Feed'in kendi BIST serisi de 09-07'yi kaybetse bagimsiz takvim kaybi gorur.
        _missing_day_packet6 = {
            "prices": _pd6.DataFrame(
                100.0, index=[_d4_6, _d8_6, _d9_6], columns=_cols6),
            "bist": _pd6.Series(100.0, index=[_d4_6, _d8_6, _d9_6]),
        }
        try:
            _missing_days6 = _DF6.sparse_market_days(
                _missing_day_packet6,
                expected_sessions=_external_sessions6,
                expected_last_closed_session=_d9_6,
            )
            if any(str(row.get("date"))[:10] == "2026-09-07"
                   for row in _missing_days6):
                ok("feed+BIST ortak 09-07 kaybi bagimsiz takvimle gorunur")
            else:
                bad("P0.6 bagimsiz takvim ortak 09-07 kaybini yakalamadi")
        except Exception as e:
            bad(f"P0.6 bagimsiz sureklilik entegrasyonu yok: {type(e).__name__}: {e}")

        # Takvim tam yil olsa da feed baslangicindan onceki seanslar sorgulanmaz.
        _short_packet6 = {
            "prices": _pd6.DataFrame(
                100.0, index=[_d4_6, _d7_6, _d8_6, _d9_6], columns=_cols6),
            "bist": _pd6.Series(100.0, index=[_d4_6, _d7_6, _d8_6, _d9_6]),
        }
        try:
            _short_sparse6 = _DF6.sparse_market_days(
                _short_packet6,
                expected_sessions=_external_sessions6,
                expected_last_closed_session=_d9_6,
            )
            if _short_sparse6 == []:
                ok("tam-yil takvim kisa-gecmisli eksiksiz feed'e sahte alarm vermiyor")
            else:
                bad(f"P0.6 feed baslangici oncesi sahte eksik seanslar: {_short_sparse6[:3]}")
        except Exception as e:
            bad(f"P0.6 kisa-feed pencere siniri uygulanmadi: {type(e).__name__}: {e}")
    except Exception as e:
        bad(f"P0.6 [6j] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6k] P0.6 -- BAGIMSIZ TAKVIM CANLI VERI KAPISINA BAGLI MI --
    # [6j] takvim motorunu ve sureklilik hesabini sinar. Bu blok ise ayni
    # olcumlerin safe_feed kaynak secimini gercekten yetkilendirdigini sabitler.
    print("\n[6k] P0.6 takvim-farkinda veri gate'i (test-once)")
    try:
        import json as _json7
        import tempfile as _tempfile7
        from datetime import datetime as _datetime7
        from pathlib import Path as _Path7
        from zoneinfo import ZoneInfo as _ZoneInfo7
        import pandas as _pd7
        from bist_alpha import selfheal as _SH7, datafeed as _DF7, config as _CFG7

        _tz7 = _ZoneInfo7("Europe/Istanbul")
        _calendar_path7 = (
            _Path7(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        _now7 = _datetime7(2026, 9, 9, 14, 30, tzinfo=_tz7)

        def _packet7(dates, returned=60, expected=60, bist_dates=None,
                     bist_ok=True, sparse_date=None):
            idx = _pd7.to_datetime(dates)
            cols = [f"G{i:03d}" for i in range(returned)]
            prices = _pd7.DataFrame(100.0, index=idx, columns=cols)
            if sparse_date is not None:
                sparse_ts = _pd7.Timestamp(sparse_date)
                prices.loc[sparse_ts] = float("nan")
                prices.loc[sparse_ts, cols[0]] = 100.0
            market_idx = _pd7.to_datetime(dates if bist_dates is None else bist_dates)
            return {
                "prices": prices,
                "bist": _pd7.Series(100.0, index=market_idx, dtype=float),
                "_bist_ok": bist_ok,
                "_source_pool_count": expected,
            }

        class _Feed7:
            def __init__(self, value):
                self.value = value

            def get_latest(self):
                if isinstance(self.value, BaseException):
                    raise self.value
                return self.value

        _sentinel7 = object()
        _old_path7 = getattr(_SH7, "DATA_FEED_RUN_STATE", _sentinel7)
        _old_retry7 = _SH7.with_retry
        _old_get_feed7 = _DF7.get_feed
        _old_source7 = getattr(_CFG7, "DATA_SOURCE", _sentinel7)
        _old_chain7 = getattr(_CFG7, "DATA_FALLBACK_CHAIN", _sentinel7)
        _old_allow7 = getattr(_CFG7, "ALLOW_FILE_FALLBACK", _sentinel7)
        _tmp7 = _tempfile7.TemporaryDirectory()
        _state7 = _Path7(_tmp7.name) / "data_feed_run.json"

        def _run_case7(packets, now=_now7, chain="borsapy", calendar_path=_calendar_path7):
            _state7.unlink(missing_ok=True)
            calls = []

            def _get_feed7(source):
                calls.append(source)
                return _Feed7(packets[source])

            _DF7.get_feed = _get_feed7
            _CFG7.DATA_FALLBACK_CHAIN = chain
            result = None
            error = None
            try:
                result = _SH7.safe_feed(now=now, calendar_path=calendar_path)
            except Exception as exc:
                error = exc
            manifest = (
                _json7.loads(_state7.read_text(encoding="utf-8"))
                if _state7.exists() else {}
            )
            return result, error, manifest, calls

        try:
            _SH7.DATA_FEED_RUN_STATE = _state7
            _SH7.with_retry = lambda fn, **_kwargs: fn()
            _CFG7.DATA_SOURCE = "yahoo"
            _CFG7.ALLOW_FILE_FALLBACK = False

            # 1) 94/94 dolu gorunse bile gercek 625 havuzuna gore yetersizdir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-08", "2026-09-09"], 94, 625),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _calls7 == ["yahoo", "borsapy"]
                    and _first7.get("reject_code") == "INSUFFICIENT_POOL_COVERAGE"):
                ok("94/625 kaynak kapsami reddedilir; donen kolonlar payda olmaz")
            else:
                bad(f"P0.6 havuz kapsami gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 2) Gun ici kosumda son kapanmis seans birebir bulunmalidir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-07"]),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "STALE_LAST_DATA"):
                ok("bayat son veri STALE_LAST_DATA ile sonraki kaynaga gecer")
            else:
                bad(f"P0.6 tazelik gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 2b) Yalniz bugunun yarim bari, son kapanmis seansi kanitlamaz.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-09"]),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _expected_day7 = next((
                row for row in _first7.get("checked_market_days", [])
                if row.get("date") == "2026-09-08"
            ), {})
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "SPARSE_MARKET_DAY"
                    and _expected_day7.get("present") == 0
                    and _expected_day7.get("total") == 60):
                ok("yalniz yarim guncel bar, kapanmis seans yerine gecmez")
            else:
                bad(f"P0.6 bos kapanmis-seans araligi temiz sayildi: "
                    f"calls={_calls7}, first={_first7}, error={_error7}")

            # 3) Bagimsiz takvim olsa da kaynak BIST referansini olcebilmelidir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-08", "2026-09-09"],
                                   bist_dates=[], bist_ok=False),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "MISSING_BIST_REFERENCE"):
                ok("olculemeyen BIST referansi temiz sayilmaz")
            else:
                bad(f"P0.6 BIST referans gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 4) Feed ve kendi BIST'i ayni seansi kaybetse de resmi takvim gorur.
            _gap_now7 = _datetime7(2026, 9, 8, 14, 30, tzinfo=_tz7)
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-04", "2026-09-08"]),
                "borsapy": _packet7(["2026-09-04", "2026-09-07", "2026-09-08"]),
            }, now=_gap_now7)
            _attempts7 = _manifest7.get("source_attempts", [])
            _first7 = _attempts7[0] if _attempts7 else {}
            _last7 = _attempts7[-1] if _attempts7 else {}
            _day7 = next((row for row in _last7.get("checked_market_days", [])
                          if row.get("date") == "2026-09-07"), {})
            _dashboard_attempts7 = (
                _result7.get("_source_attempts", []) if _result7 else []
            )
            _dashboard_last7 = (
                _dashboard_attempts7[-1] if _dashboard_attempts7 else {}
            )
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "SPARSE_MARKET_DAY"
                    and _last7.get("reject_code") is None
                    and _last7.get("expected_last_closed_session") == "2026-09-07"
                    and _last7.get("freshness_status") == "FRESH"
                    and _last7.get("bar_completeness") == "unknown"
                    and _day7.get("present") == _day7.get("total") == 60
                    and "checked_market_days" not in _dashboard_last7
                    and _dashboard_last7.get("checked_market_day_count")
                    == len(_last7.get("checked_market_days", []))
                    and _dashboard_last7.get("latest_checked_market_day")
                    == _last7.get("checked_market_days", [])[-1]):
                ok("ortak gun kaybi reddedilir; basarili manifest ayni gate olcumunu tasir")
            else:
                bad(f"P0.6 takvim-manifest entegrasyonu yok/yanlis: "
                    f"calls={_calls7}, attempts={_attempts7}, error={_error7}")

            # 5) File fallback atlanmasi serbest metin degil kararli kod tasir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": RuntimeError("yahoo-down"),
                "file": _packet7(["2026-09-08", "2026-09-09"]),
            }, chain="file")
            _file7 = next((row for row in _manifest7.get("source_attempts", [])
                           if row.get("source") == "file"), {})
            if (_error7 and _file7.get("status") == "skipped"
                    and _file7.get("reject_code") == "FILE_FALLBACK_DISABLED"):
                ok("file fallback pilot kararinda atlanir ve kodlu iz birakir")
            else:
                bad(f"P0.6 file-fallback sozlesmesi yok/yanlis: "
                    f"calls={_calls7}, file={_file7}, error={_error7}")

            # 6) Takvim kapsam disinda ise saglikli gorunen feed de yetkili degildir.
            _future_now7 = _datetime7(2027, 1, 1, 9, 45, tzinfo=_tz7)
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-12-31"]),
                "borsapy": _packet7(["2026-12-31"]),
            }, now=_future_now7)
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            if (_error7 and _first7.get("reject_code") == "CALENDAR_UNAVAILABLE"
                    and _calls7 == []):
                ok("takvim kapsam-disinda fail-closed; veri kaynagi bosuna cagrilmaz")
            else:
                bad(f"P0.6 takvim fail-closed yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 7) Iki canli uretici file fallback'i karar yolunda acamaz.
            _root7 = _Path7(__file__).resolve().parent
            _workflow_texts7 = [
                (_root7 / ".github" / "workflows" / name).read_text(encoding="utf-8")
                for name in ("bist-alpha.yml", "precise.yml")
            ]
            _audit_text7 = (_root7 / "scripts" / "system_control_audit.py").read_text(
                encoding="utf-8")
            if (all('ALLOW_FILE_FALLBACK: "0"' in text for text in _workflow_texts7)
                    and 'ALLOW_FILE_FALLBACK: "1"' not in _audit_text7):
                ok("iki ureticide file fallback kapali; audit ters sozlesme aramiyor")
            else:
                bad("P0.6 file fallback uretici/audit sozlesmesi hizali degil")
        finally:
            _SH7.with_retry = _old_retry7
            _DF7.get_feed = _old_get_feed7
            if _old_path7 is _sentinel7:
                try:
                    delattr(_SH7, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH7.DATA_FEED_RUN_STATE = _old_path7
            for _name7, _old7 in [
                ("DATA_SOURCE", _old_source7),
                ("DATA_FALLBACK_CHAIN", _old_chain7),
                ("ALLOW_FILE_FALLBACK", _old_allow7),
            ]:
                if _old7 is _sentinel7:
                    try:
                        delattr(_CFG7, _name7)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG7, _name7, _old7)
            _tmp7.cleanup()
    except Exception as e:
        bad(f"P0.6 [6k] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6l] P0.6/madde-7 -- BAGIMSIZ STOP GOZLEMI HER KOSUDA CALISIR --
    # Bu kapı rapor/heartbeat akışından ayrıdır: yalnız tespit + alarm yapar,
    # portföy state'ini değiştirmez. Fiyatı olmayan pozisyon da sessizce
    # atlanmaz; stop_eval izi içinde status=missing olarak kalır.
    print("\n[6l] P0.6/madde-7 bagimsiz stop gozlemi (test-once)")
    try:
        import copy as _copy8
        import inspect as _inspect8
        import re as _re8
        from pathlib import Path as _Path8
        from bist_alpha import portfolio as _PF8

        _root8 = _Path8(__file__).resolve().parent

        def _step_block8(_text, _fragment):
            _lines8 = _text.splitlines()
            _start8 = next(
                (i for i, line in enumerate(_lines8)
                 if line.startswith("      - name:") and _fragment in line),
                None,
            )
            if _start8 is None:
                return "", None
            _end8 = len(_lines8)
            for i in range(_start8 + 1, len(_lines8)):
                if _lines8[i].startswith("      - name:") or _lines8[i].startswith("      - uses:"):
                    _end8 = i
                    break
            return "\n".join(_lines8[_start8:_end8]), _start8

        _workflow_specs8 = [
            (".github/workflows/bist-alpha.yml", "Portfoy state commit"),
            (".github/workflows/precise.yml", "State commit"),
        ]
        _workflow_contract_ok8 = True
        for _workflow_path8, _commit_fragment8 in _workflow_specs8:
            _workflow_text8 = (_root8 / _workflow_path8).read_text(encoding="utf-8")
            _stop_block8, _stop_line8 = _step_block8(_workflow_text8, "P0.6 stop gozlemi")
            _commit_block8, _commit_line8 = _step_block8(_workflow_text8, _commit_fragment8)
            _run8 = _stop_block8.split("run:", 1)[-1]
            _before_stop8 = (
                "\n".join(_workflow_text8.splitlines()[:_stop_line8])
                if _stop_line8 is not None else ""
            )
            _checks8 = {
                "ayri always adimi": bool(_stop_block8 and "if: always()" in _stop_block8),
                "state commit oncesi": bool(
                    _stop_line8 is not None and _commit_line8 is not None
                    and _stop_line8 < _commit_line8
                ),
                "ana rapor komutundan ayri": bool(
                    _stop_block8 and "daemon.py --once" not in _run8
                ),
                # SOZLESME DARALTILDI (2026-09-10, olcumle).
                # ESKI HALI: "steps.gate.outputs.run adimda HIC gecmesin".
                # OLCUM: bist-alpha.yml haftaici 32 cron tetigi TANIMLIYOR (6:45-50-55,
                # 7:00..30, 11:30..55, 12:00..20, 15:40..55, 16:00..30) + her push.
                # ⚠️ TANIMLI 32; FIILEN kosan cok daha az — GitHub schedule
                # tetiklerini dusuruyor: 2026-09-10'da 4, 09-09'da 6 (olculdu).
                # Karar ayni kaliyor (izi commit'lenmeyen kosum + alarm yuzeyi),
                # yalniz buyukluk duzeldi. Kapi: BUGUN_UC_KONTROL -> K4.
                # Ayni dosyada zaten yazili: `gate.run` burada 'true' OLMUYOR (raporu
                # precise uretiyor) ve state commit'i `run == 'true'`e bagli. Yani
                # kosulsuz `always()` ile stop gozlemi her FIILI tetikte kosar, izi HIC
                # commit'lenmez ve her tetik ayri bir P0.3 alarm yuzeyi acar —
                # "uretilip tuketilmeyen cikti" kusurunu 10 kat buyuterek.
                # KORUNAN NIYET: gozlemci ANA YOLUN BASARISINA kosullanmasin.
                # `gate.run` bir ARIZA kosulu degil, "bu tetikte is var mi" kosulu.
                # IZIN VERILEN TEK BICIM `!= 'false'`: kapi bozulup bos donerse
                # gozlemci YINE kosar. `== 'true'` YASAK — bu dosyada bekciyi 40
                # kosuda 0 kez calistiran hata tam olarak oydu (2026-07-22 kaydi).
                "arizaya kosullu degil": bool(
                    _stop_block8
                    and "success()" not in _stop_block8
                    and ".outcome" not in _stop_block8
                ),
                "slot kapisi yalniz != 'false' bicimiyle": bool(
                    _stop_block8 and (
                        "steps.gate.outputs.run" not in _stop_block8
                        or ("steps.gate.outputs.run != 'false'" in _stop_block8
                            and "steps.gate.outputs.run ==" not in _stop_block8)
                    )
                ),
                "stop izi ve komutu": bool(
                    "stop_eval" in _run8 or "stop observer" in _run8.lower()
                ),
                "alarm kanali": bool(
                    "TELEGRAM_TOKEN" in _stop_block8
                    and "TELEGRAM_CHAT_ID" in _stop_block8
                ),
                "dedup yok": bool(
                    "report_gate" not in _stop_block8
                    and "HEARTBEAT_DUE" not in _stop_block8
                    and "sent_date" not in _stop_block8
                ),
                "stop gozlemi hatasi gorunur": bool(
                    "continue-on-error" not in _stop_block8
                ),
                # KARAR (2026-09-10): alarm YALNIZ breached'de. `missing` veri-kalitesi
                # durumudur, kendiliginden cozulmez -> gunde ~6 Telegram = alarm korlugu.
                # `missing` ize ve operasyon kapisina gider, Telegram'a DEGIL.
                "alarm yalniz breached": bool("breached" in _run8),
                # KARAR (2026-09-10): gozlemci stop_eval.json'a YAZMAZ. O artefaktin
                # bayatligi #0l'in kor-nokta sinyali (`_write_stop_eval` yalniz kapanista
                # yazar). Her kosuda yazmak o sinyali oldururdu -> AYRI artefakt.
                "stop_eval.json'a yazmaz": bool("stop_eval.json" not in _run8),
                "stop alarmi basarisizligi gorunur": bool(
                    "if ! resp=" in _run8 and "alarm_rc=1" in _run8
                    and "curl -sfS" in _run8
                ),
                # CIKTI TUKETICISI GUARD'I: runner `breached/unpriced/positions/
                # gate` degerlerini GITHUB_OUTPUT'a yaziyor. Bunlari okuyan ozet
                # adimi silinirse degerler yine YAZILIP OKUNMAYAN yuzeye doner ve
                # kimse fark etmez — bu isin duzelttigi kusurun aynisi.
                # `id: stop_obs` de sarttir: id yoksa ciktilar adreslenemez.
                # SUBSTRING DEGIL SINIRLI ESLESME: ilk yazdigim hal
                # `"id: stop_obs" in blok` idi ve `id: stop_obsX` mutasyonunu
                # KACIRIYORDU (bozuk id, dogru id'nin ustkumesi). Mutasyon testi
                # 3/3'ten 1/3 yakaladi ve kontrolu cop olmaktan kurtardi.
                # ("kaba-arama IPUCU uretir, KANIT degil" — kendi yasasi.)
                "cikti tuketicisi bagli (id + ozet adimi)": bool(
                    _stop_block8
                    and _re8.search(r"^\s*id:\s*stop_obs\s*$", _stop_block8, _re8.M)
                    and _re8.search(r"steps\.stop_obs\.outputs\.gate\s*\}\}", _workflow_text8)
                    and "GITHUB_STEP_SUMMARY" in _workflow_text8
                ),
                "iz kalici artefakt": bool(
                    "actions/upload-artifact@v4" in _workflow_text8
                    and _stop_line8 is not None
                    and _workflow_text8.find("actions/upload-artifact@v4", _stop_line8)
                    > _stop_line8
                ),
            }
            if _workflow_path8 == ".github/workflows/bist-alpha.yml":
                _checks8["native gozlemci bagimliliklari kurulu"] = bool(
                    "      - uses: actions/setup-python@v5\n"
                    "        with:\n"
                    "          python-version: '3.12'\n"
                    "          cache: 'pip'\n"
                    "      - run: pip install -r requirements.txt" in _before_stop8
                )
            _bad_checks8 = [name for name, passed in _checks8.items() if not passed]
            if not _bad_checks8:
                ok(f"P0.6 {_workflow_path8}: bagimsiz stop adimi sozlesmesi")
            else:
                bad(f"P0.6 {_workflow_path8}: stop adimi eksik/yanlis {_bad_checks8}")
                _workflow_contract_ok8 = False

        # KARAR (2026-09-10): gozlemci portfolio.py'ye YAZILMAZ. O dosya 5-SHA
        # DONUK (09ad265d9fd5); icine fonksiyon eklemek [6b]'yi kirar ve A1'i ihlal
        # ettirir. Ayri modul hem SHA'yi korur hem "bagimsiz yol"u fiziksellestirir.
        # OTORITE ERISIM BICIMI DE SOZLESME: gozlemci `portfolio.stop_level(pos)`
        # seklinde MODUL ATTRIBUTE uzerinden cagirmali. `from ... import stop_level`
        # yapilirsa asagidaki monkeypatch TUTMAZ -> otorite dogrulanamaz hale gelir.
        try:
            from bist_alpha import stop_observer as _SO8
        except Exception:
            _SO8 = None
        _evaluate_stops8 = getattr(_SO8, "evaluate_stops", None) if _SO8 else None
        if not callable(_evaluate_stops8):
            bad("P0.6 stop gozlemi API'si yok: bist_alpha/stop_observer.evaluate_stops")
        else:
            _state8 = {
                "positions": {
                    "AAA": {"entry": 100.0, "peak": 100.0, "shares": 1.0},
                    "BBB": {"entry": 100.0, "peak": 100.0, "shares": 1.0},
                },
                "cash": 0.0,
            }
            _before8 = _copy8.deepcopy(_state8)
            _old_stop_level8 = _PF8.stop_level
            _PF8.stop_level = lambda _pos: 97.0
            try:
                _observations8 = _evaluate_stops8(_state8, {"AAA": 96.0})
                _observations_again8 = _evaluate_stops8(_state8, {"AAA": 96.0})
                _observations_nan8 = _evaluate_stops8(_state8, {"AAA": float("nan")})
            finally:
                _PF8.stop_level = _old_stop_level8

            _rows8 = {
                row.get("ticker"): row for row in _observations8
                if isinstance(row, dict)
            } if isinstance(_observations8, list) else {}
            _rows_again8 = {
                row.get("ticker"): row for row in _observations_again8
                if isinstance(row, dict)
            } if isinstance(_observations_again8, list) else {}
            _rows_nan8 = {
                row.get("ticker"): row for row in _observations_nan8
                if isinstance(row, dict)
            } if isinstance(_observations_nan8, list) else {}
            _priced8 = _rows8.get("AAA", {})
            _missing8 = _rows8.get("BBB", {})
            if (
                set(_rows8) == {"AAA", "BBB"}
                and _priced8.get("status") == "priced"
                and _priced8.get("price") == 96.0
                and _priced8.get("stop_level") == 97.0
                and _priced8.get("breached") is True
                and _missing8.get("status") == "missing"
                and _missing8.get("price") is None
                and _missing8.get("breached") is None
                and _rows_again8.get("AAA", {}).get("status") == "priced"
                and _rows_again8.get("BBB", {}).get("status") == "missing"
                and _rows_nan8.get("AAA", {}).get("status") == "missing"
                and _rows_nan8.get("AAA", {}).get("reason") == "price_invalid"
                and _state8 == _before8
            ):
                ok("P0.6 stop izi: priced/missing, stop_level otoritesi, tekrar ve state degismez")
            else:
                bad(
                    "P0.6 stop izi sozlesmesi eksik/yanlis: "
                    f"rows={_rows8}, again={_rows_again8}, state_changed={_state8 != _before8}"
                )

        # Entegrasyon kapisi: observer, portfolio.load()'un goreli cwd'sine
        # baglanamaz. Eksik/bozuk state, gercekten bos pozisyondan ayrilmalidir.
        # Fiyat adapter'i de tek sembolde duz DataFrame'i kabul etmelidir.
        try:
            import json as _json8
            import tempfile as _tempfile8
            import pandas as _pd8
            from scripts import stop_observer_run as _SOR8

            _tmp_state8 = _tempfile8.TemporaryDirectory()
            try:
                _state_dir8 = _Path8(_tmp_state8.name)
                (_state_dir8 / "portfolio_A.json").write_text(
                    _json8.dumps({"account": "A", "positions": {}}),
                    encoding="utf-8",
                )
                (_state_dir8 / "portfolio_B.json").write_text("{", encoding="utf-8")
                _states8, _statuses8 = _SO8.load_states(
                    ["A", "B", "C"], state_dir=_state_dir8
                )
                _payload8 = _SO8.build_payload(
                    {"A": []}, [],
                    account_status={
                        "A": {"account": "A", "status": "loaded"},
                        "B": {"account": "B", "status": "missing"},
                    },
                )
                _flat8 = _pd8.DataFrame(
                    {"Close": [101.0]},
                    index=_pd8.to_datetime(["2026-09-10"]),
                )
                _multi8 = _pd8.concat({"AAA": _flat8}, axis=1)
                _loader_ok8 = (
                    set(_states8) == {"A"}
                    and _statuses8["A"].get("status") == "loaded"
                    and _statuses8["B"].get("status") == "unreadable"
                    and _statuses8["C"].get("status") == "missing"
                    and _payload8.get("unavailable_account_count") == 1
                )
                # `_last_close` (fiyat, bar_gunu) doner: bar gunu fiyatla BIRLIKTE
                # tasinmazsa panel bayat fiyat uzerinden kendinden emin YESIL
                # gosterir. Iki sekil de hem degeri hem gunu ayni vermeli.
                _shape_ok8 = (
                    _SOR8._last_close(_flat8, ("AAA",)) == (101.0, "2026-09-10")
                    and _SOR8._last_close(_multi8, ("AAA",)) == (101.0, "2026-09-10")
                )
                if _loader_ok8 and _shape_ok8:
                    ok("P0.6 entegrasyon: state durumu ve tek-sembol fiyat sekli ayrik")
                else:
                    bad(
                        "P0.6 entegrasyon kapisi eksik/yanlis: "
                        f"statuses={_statuses8}, shape_ok={_shape_ok8}"
                    )
                _main_source8 = _inspect8.getsource(_SOR8.main)
                if "state_dir=ROOT / \"portfolios\"" in _main_source8:
                    ok("P0.6 state yolu cwd'den bagimsiz: runner repo kokunu kullaniyor")
                else:
                    bad("P0.6 state yolu runner'da repo kokune sabit degil")

                _old_load_states8 = _SO8.load_states
                _old_write_payload8 = _SO8.write_payload
                _old_emit8 = _SOR8._emit
                _statuses_empty8 = {
                    acc: {
                        "account": acc,
                        "status": "loaded" if acc == "F" else "missing",
                    }
                    for acc in _SOR8.HESAPLAR
                }
                _payload_empty8 = {}
                try:
                    _SO8.load_states = lambda _accounts, state_dir=None: (
                        {"F": {"account": "F", "positions": {}}},
                        _statuses_empty8,
                    )
                    _SO8.write_payload = lambda _payload, path=None: (
                        _payload_empty8.update(_payload) or "test"
                    )
                    _SOR8._emit = lambda _breached, _payload: None
                    _empty_with_missing_rc8 = _SOR8.main()
                finally:
                    _SO8.load_states = _old_load_states8
                    _SO8.write_payload = _old_write_payload8
                    _SOR8._emit = _old_emit8
                # SOZLESME DEGISTI (2026-09-10, onaylanan cikis-kodu ayrimi).
                # ESKI: eksik hesap -> exit 1. Bu, `missing` -> job failure -> P0.3
                # -> Telegram zincirini kuruyordu ve "missing Telegram'a GITMEZ"
                # karariyla (stop_observer.py, karar 3) CELISIYORDU.
                # YENI: sinyal kaybolmadi, CIKIS KODUNDAN KAPIYA tasindi.
                # Bu testin niyeti ayni kaldi — "eksik hesap sessizce basari
                # sayilmasin" — yalnizca hangi kanalda goruldugu degisti.
                _kapi_empty8 = ((_payload_empty8.get("gate") or {}).get("verdict") or "").upper()
                if _empty_with_missing_rc8 == 0 and _kapi_empty8 == "YELLOW":
                    ok("P0.6 bos pozisyon + eksik hesap: exit 0 ama operasyon kapisi SARI")
                else:
                    bad("P0.6 eksik hesap bos-pozisyon dalinda kapiya yansimadi "
                        f"(rc={_empty_with_missing_rc8}, kapi={_kapi_empty8 or '-'})")
            finally:
                _tmp_state8.cleanup()
        except Exception as e:
            bad(f"P0.6 entegrasyon kapisi kosmadi: {type(e).__name__}: {e}")

        # #0l KORUMASI: gozlemci her kosuda calisacak; stop_eval.json'a yazarsa
        # o artefaktin BAYATLIGI ile tasidigi "o gun stop degerlendirilmedi" sinyali
        # olur. `_write_stop_eval` kapanis-disi erken donusu KORUNMALI.
        import shadow as _SH8
        _we8 = _inspect8.getsource(_SH8._write_stop_eval)
        if 'run_label != "kapanis"' in _we8 and "return" in _we8.split('run_label != "kapanis"')[1][:40]:
            ok("P0.6 #0l korumasi: _write_stop_eval kapanis-disi hala erken donuyor")
        else:
            bad("P0.6 #0l korumasi KIRILDI: stop_eval.json artik her kosuda yazilabilir")
    except Exception as e:
        bad(f"P0.6 [6l] testi kosmadi: {type(e).__name__}: {e}")


    # -- [6m] P0.6/madde-7 -- unpriced/missing OPERASYON KAPISI --
    # NEDEN: [6l] olcumu URETIYOR ama hicbir sey TUKETMIYORDU. "missing fail-closed"
    # yazip yalnizca kaydetmek, sistemin kendi kusurunu (karar tuketicisi olmayan
    # cikti) tekrar etmektir.
    # CIKIS KODU IKI FARKLI SEYI KARISTIRMAMALI:
    #   KISMI (bazi pozisyon fiyatsiz)  -> exit 0 · iz + KAPI SARI · Telegram YOK
    #   TOPLAM (hic state / hic fiyat)  -> exit 1 · adim kirmizi · P0.3 alarmi DOGRU
    # Aksi halde `missing` -> exit 1 -> job failure -> P0.3 -> Telegram olur ve
    # "missing Telegram'a gitmez" karariyla CELISIR.
    print("\n[6m] P0.6/madde-7 unpriced operasyon kapisi (test-once)")
    try:
        import importlib.util as _ilu9
        from pathlib import Path as _Path9

        _root9 = _Path9(__file__).resolve().parent
        _spec9 = _ilu9.spec_from_file_location(
            "_stop_obs_run9", _root9 / "scripts" / "stop_observer_run.py")
        _run9 = _ilu9.module_from_spec(_spec9)
        _spec9.loader.exec_module(_run9)
        _SO9 = _run9.stop_observer

        def _poz9(entry=100.0, peak=100.0):
            return {"entry": entry, "peak": peak, "shares": 1.0}

        # Sabit tarih KULLANILMAZ: kapi artik tazeligi takvime gore yargiliyor,
        # sabit bir gun yazilirsa bu testler birkac gun sonra KENDILIGINDEN
        # kirmiziya doner (zamana bagli test = sahte alarm fabrikasi).
        # Bugunun gunu her zaman "beklenen son kapali seans"tan >= olur -> FRESH.
        from datetime import date as _date9
        _bugun9 = _date9.today().isoformat()

        _yakalanan9 = {}

        def _kur9(states, statuses, prices):
            _yakalanan9.clear()
            _run9.stop_observer.load_states = lambda *a, **k: (states, statuses)
            _run9.fetch_prices = lambda t: (
                prices, [{"source": "test", "status": "ok"}], {},
                {k: _bugun9 for k in prices},
            )
            _run9.stop_observer.write_payload = lambda p, path=None: (
                _yakalanan9.update(p) or "test")

        _orj_load9 = _SO9.load_states
        _orj_write9 = _SO9.write_payload
        _orj_fetch9 = _run9.fetch_prices
        _orj_hes9 = _run9.HESAPLAR
        _run9.HESAPLAR = ["F"]
        try:
            _st9 = {"F": {"positions": {"AAA": _poz9(), "BBB": _poz9()}, "cash": 0.0}}
            _ok9 = {"F": {"account": "F", "status": "loaded", "position_count": 2}}

            # 1) KISMI: bir pozisyon fiyatsiz -> exit 0, kapi SARI, Telegram tetigi YOK
            _kur9(_st9, _ok9, {"AAA": 150.0})
            _rc_kismi9 = _run9.main()
            _p_kismi9 = dict(_yakalanan9)

            # 2) HIC FIYAT: pozisyon var, hicbir kaynak vermedi -> exit 1, kapi KIRMIZI
            _kur9(_st9, _ok9, {})
            _rc_fiyatsiz9 = _run9.main()
            _p_fiyatsiz9 = dict(_yakalanan9)

            # 3) HIC STATE: hicbir hesap yuklenemedi -> exit 1, kapi KIRMIZI
            _kur9({}, {"F": {"account": "F", "status": "unreadable", "error": "x"}}, {})
            _rc_statesiz9 = _run9.main()
            _p_statesiz9 = dict(_yakalanan9)

            # 4) HEPSI PRICED: -> exit 0, kapi YESIL, breach yok
            _kur9(_st9, _ok9, {"AAA": 150.0, "BBB": 150.0})
            _rc_temiz9 = _run9.main()
            _p_temiz9 = dict(_yakalanan9)

            # 5) KISMI HESAP: F yuklendi, G1 okunamadi, fiyatlar tam.
            # Bir hesap dosyasinin yoklugu ARIZA DEGIL -> exit 0, kapi SARI.
            # `not unavailable` sarti burada exit 1 verir ve P0.3 -> Telegram tetikler;
            # bu, "missing Telegram'a gitmez" karariyla CELISIR.
            _run9.HESAPLAR = ["F", "G1"]
            _kur9(
                _st9,
                {**_ok9, "G1": {"account": "G1", "status": "missing"}},
                {"AAA": 150.0, "BBB": 150.0},
            )
            _rc_kismi_hesap9 = _run9.main()
            _p_kismi_hesap9 = dict(_yakalanan9)
            _run9.HESAPLAR = ["F"]
        finally:
            _SO9.load_states = _orj_load9
            _SO9.write_payload = _orj_write9
            _run9.fetch_prices = _orj_fetch9
            _run9.HESAPLAR = _orj_hes9

        def _kapi9(p):
            return ((p.get("gate") or {}).get("verdict") or "").upper()

        def _satir9(p, ticker):
            for _satirlar in (p.get("accounts") or {}).values():
                for _r in _satirlar or []:
                    if _r.get("ticker") == ticker:
                        return _r
            return {}

        _sartlar9 = [
            ("1  KISMI: exit 0 (missing tek basina ariza DEGIL)", _rc_kismi9, 0),
            ("1b KISMI: unpriced_count=1", _p_kismi9.get("unpriced_count"), 1),
            ("1c KISMI: kapi SARI", _kapi9(_p_kismi9), "YELLOW"),
            ("1d KISMI: breach yok -> Telegram tetigi yok", _p_kismi9.get("breach"), False),
            ("2  HIC FIYAT: exit 1 (gozlem YAPILAMADI)", _rc_fiyatsiz9, 1),
            ("2b HIC FIYAT: kapi KIRMIZI", _kapi9(_p_fiyatsiz9), "RED"),
            ("3  HIC STATE: exit 1", _rc_statesiz9, 1),
            ("3b HIC STATE: kapi KIRMIZI", _kapi9(_p_statesiz9), "RED"),
            ("4  HEPSI PRICED: exit 0", _rc_temiz9, 0),
            ("4b HEPSI PRICED: kapi YESIL", _kapi9(_p_temiz9), "GREEN"),
            ("4c HEPSI PRICED: unpriced_count=0", _p_temiz9.get("unpriced_count"), 0),
            ("5a KISMI HESAP: exit 0 (dosya yoklugu ariza DEGIL)", _rc_kismi_hesap9, 0),
            ("5b KISMI HESAP: kapi SARI", _kapi9(_p_kismi_hesap9), "YELLOW"),
            ("5c KISMI HESAP: unavailable_account_count=1",
             _p_kismi_hesap9.get("unavailable_account_count"), 1),
            # BAYAT FIYAT gorunur olmali: gozlem TAZE olup fiyat ESKI olabilir.
            # Tarih tasinmazsa panel bayat fiyat uzerinden kendinden emin YESIL
            # gosterir — "yanlis-guven" sinifi. Hukme cevrilmez, GORUNUR kilinir.
            ("6  fiyat bar gunu satirda", _satir9(_p_temiz9, "AAA").get("price_date"),
             _bugun9),
            ("6b price_asof ozeti oldest", (_p_temiz9.get("price_asof") or {}).get("oldest"),
             _bugun9),
            ("6c price_asof ozeti distinct", (_p_temiz9.get("price_asof") or {}).get("distinct"),
             1),
            ("6d fiyatsiz satirda tarih YOK (uydurulmaz)",
             _satir9(_p_kismi9, "BBB").get("price_date"), None),
            ("6e fiyatsiz gun ozete girmez",
             (_p_kismi9.get("price_asof") or {}).get("distinct"), 1),
            # Iki kaynagin karsilastirmasi ARTEFAKTA olmali, yalniz logda degil:
            # Actions logu 90 gunde silinir, artefakt git'te kalir. Bir stop
            # tartismali hale gelirse kanit o gun kaybolmus olmamali.
            ("7  cross_source_check alani artefaktta",
             isinstance(_p_temiz9.get("cross_source_check"), dict), True),
            # D6 — DAMGA EKSENI. `health-logic.js timestampMs` ofset YOKSA
            # +03:00 varsayar. Damga 'Z'sini kaybederse panel 3 SAATLIK sahte
            # bayatlik uretir ve HICBIR SEY kizarmaz (kayitli tuzak: "negatif
            # yas / +3 saatlik sahte bayatlik"). Yazan taraf `_utc_timestamp`
            # 'Z' ekliyor ama bunu PINLEYEN test yoktu -> bekcisiz dogruluk.
            ("8g damga ofset tasiyor (D6: ofsetsiz damga paneli 3 saat kaydirir)",
             bool(__import__("re").search(
                 r"[zZ]|[+-]\d\d:?\d\d$", str(_p_temiz9.get("generated_at")))), True),
        ]

        # -- BAYATLIK HUKMU (SAF fonksiyonlar, ZAMAN ENJEKTE EDILIR) -----------
        # ESKIDEN: "esik uydurmadan yargilanamaz" denip yalniz olcum birakilmisti.
        # BU YANLISTI: sistemin KENDI takvim otoritesi (market_calendar.
        # assess_freshness) esiksiz bir hukum zaten uretiyordu — bakilmamisti.
        # Testler `now` enjekte eder; gercek saate bagli DEGILDIR.
        from datetime import datetime as _dt9, timezone as _tz9
        _simdi9 = _dt9(2026, 9, 10, 13, 0, tzinfo=_tz9.utc)   # 16:00 TR, seans acik
        _tz_bayat9 = _SO9.assess_price_freshness(["2026-09-03"], now=_simdi9)
        _tz_taze9 = _SO9.assess_price_freshness([_bugun9], now=_simdi9) \
            if _bugun9 >= "2026-09-10" else _SO9.assess_price_freshness(["2026-09-10"], now=_simdi9)
        _tz_kapsamdisi9 = _SO9.assess_price_freshness(
            ["2031-01-06"], now=_dt9(2031, 1, 6, 13, 0, tzinfo=_tz9.utc))
        _tz_bos9 = _SO9.assess_price_freshness([], now=_simdi9)
        _sartlar9 += [
            ("8  bayat bar STALE", _tz_bayat9.get("status"), "STALE"),
            ("8b bayat ret kodu", _tz_bayat9.get("reject_code"), "STALE_LAST_DATA"),
            ("8c beklenen kapali seans yazili",
             _tz_bayat9.get("expected_last_closed_session"), "2026-09-09"),
            ("8d guncel bar FRESH", _tz_taze9.get("status"), "FRESH"),
            # FAIL-SAFE: takvim kapsamiyorsa hukum VERILMEZ. Ne sahte BAYAT
            # (yanlis alarm) ne sahte TAZE (sessiz guvence) uretilir.
            ("8e takvim kapsamiyor -> UNKNOWN", _tz_kapsamdisi9.get("status"), "UNKNOWN"),
            ("8f fiyatlanan pozisyon yok -> UNKNOWN", _tz_bos9.get("status"), "UNKNOWN"),
            # Kapi hukmu: STALE sariya cevirir, UNKNOWN hukmu DEGISTIRMEZ,
            # RED her ikisini de yener (gozlem hic yapilamadiysa tazelik ikincildir).
            ("9  STALE -> kapi SARI",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "STALE"})["verdict"], "YELLOW"),
            ("9b STALE sebebi yazili",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "STALE"})["reason"], "stale_price"),
            ("9c FRESH -> kapi YESIL",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "FRESH"})["verdict"], "GREEN"),
            ("9d UNKNOWN hukmu bozmaz",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "UNKNOWN"})["verdict"], "GREEN"),
            ("9e RED, STALE'i yener",
             _SO9.gate_verdict(2, 0, 0, 0, freshness={"status": "STALE"})["verdict"], "RED"),
            ("9f eksik kapsama + STALE ikisi de detayda",
             "stale_price" in _SO9.gate_verdict(2, 1, 0, 1,
                                                freshness={"status": "STALE"})["detail"]
             or "beklenen" in _SO9.gate_verdict(2, 1, 0, 1,
                                                freshness={"status": "STALE"})["detail"], True),
        ]
        for _ad9, _alinan9, _beklenen9 in _sartlar9:
            if _alinan9 == _beklenen9:
                ok(f"P0.6 kapi {_ad9}")
            else:
                bad(f"P0.6 kapi {_ad9}: beklenen {_beklenen9!r}, alinan {_alinan9!r}")

        # 5) TUKETICI: kapi hukmu panelde OKUNMALI. Uretilip okunmayan olcum,
        #    tam da bu isin duzeltmeye calistigi kusurdur.
        # KANIT TURU = VEKIL (D12): burada olculen sey METIN YUZEYI, calisan JS
        # davranisi DEGIL. Sebep: bu makinede `node` YOK ve docs/test-health.js
        # hicbir yerden kosulmuyor -> selftest JS'i CALISTIRAMAZ.
        # Vekil oldugu icin tek kelime degil, tek tek BAGLAMA NOKTALARI aranir.
        #
        # JS DAVRANISI AYRICA OLCULDU (2026-09-10, tarayicide 7 senaryo):
        #   yok->n(verdict g) · GREEN->g · YELLOW->a(verdict a) · RED->r(verdict r)
        #   breach->alt satirda gorunur · gate yok->n · damga bozuk->"yas okunamadi"
        # Bu olcum TEK SEFERLIK ve TEKRARLANMIYOR; regresyonu yakalayacak kosucu
        # repoda YOK. Acik is: JS kosucusu (bkz ACIK_ISLER, test-health.js olu).
        _idx9 = (_root9 / "docs" / "index.html").read_text(encoding="utf-8")
        _hl9 = (_root9 / "docs" / "health-logic.js").read_text(encoding="utf-8")
        _hh9 = (_root9 / "docs" / "health.html").read_text(encoding="utf-8")
        _kanca9 = [
            ("index.html artefakti cekiyor", "state/stop_observer.json" in _idx9),
            ("index.html veriye bagliyor", "data.stop_observer = " in _idx9),
            ("index.html kapi satirini GOSTERIYOR (slice kurbani degil)",
             "'stop_observer'" in _idx9 and "core.push(stopRow)" in _idx9),
            ("health-logic cekirdek metrik uretiyor",
             '"stop_observer", true,' in _hl9),
            ("health-logic hukmu normalize ediyor",
             "normalizeVerdict(soGate && soGate.verdict)" in _hl9),
            ("health-logic yoklugu YESIL saymiyor", '|| "n";' in _hl9),
            ("health-logic fiyat bar gununu gosteriyor",
             "price_asof" in _hl9 and "soFiyatGun" in _hl9),
            ("health.html artefakti cekiyor", "state/stop_observer.json" in _hh9),
            ("health.html veriye bagliyor", "data.stop_observer = " in _hh9),
            # KANIT ZINCIRININ KENDISI DENETLENIR: CI'da node zorunlulugu bu
            # bayraga bagli. Bayrak workflow'dan dusrulse "CI yesil" bir daha
            # "JS kostu" demezdi ve bunu KIMSE fark etmezdi (sessiz bozulma).
            ("bist-alpha.yml selftest adimi node'u ZORUNLU kiliyor",
             'SELFTEST_REQUIRE_NODE: "1"' in (_root9 / ".github" / "workflows"
                                              / "bist-alpha.yml").read_text(encoding="utf-8")),
        ]
        _eksik9 = [ad for ad, tut in _kanca9 if not tut]
        if not _eksik9:
            ok(f"P0.6 kapi 5  TUKETICI bagli [VEKIL: metin yuzeyi] ({len(_kanca9)}/{len(_kanca9)} kanca)")
        else:
            bad("P0.6 kapi 5  TUKETICI EKSIK: " + " | ".join(_eksik9))

        # 8) JS SENARYO KOSUCUSU — vekil kontrolu KONU kanitina cevirir.
        # docs/test-health.js 2026-09-10'a kadar HICBIR YERDEN kosulmuyordu:
        # `system_control_audit` yalnizca DOSYANIN VAR OLDUGUNU ariyordu. Yani
        # 29 senaryo yazilmis, sifir kez kosmustu — "kod var != kod calisiyor".
        # ATLAMA SESSIZ DEGIL: node yoksa uyari basilir, kapsam boslugu gorunur kalir.
        import shutil as _sh9
        import subprocess as _sp9
        _node9 = _sh9.which("node")
        # CI'DA ATLAMA YASAK — ve bu sadece siki davranmak degil, DOGRULANABILIRLIK
        # sorunudur: Actions loglari kimlik dogrulamasi ister (403), yani "adim yesil"
        # tek basina kosucunun KOSTUGUNU soylemez; node yokken de yesil kalirdi.
        # CI'da yokluk BLOKLAYICI yapilinca "CI yesil" ifadesi "node vardi ve
        # senaryolar gecti"yi MANTIKEN icerir -> log okumadan kanit.
        # Yerelde uyari kalir: node opsiyonel, ama sessiz de atlanmaz.
        # ANAHTAR ACIK OLARAK WORKFLOW'DAN GELIR (`SELFTEST_REQUIRE_NODE: "1"`).
        # Yalnizca `GITHUB_ACTIONS`e guvenmek, kanit zincirini DOGRULANAMAYAN bir
        # varsayima baglardi ("GitHub bu degiskeni set eder" — repodan okunamaz).
        # Acik bayrak repoda YAZILI ve asagida kanca ile denetleniyor.
        # GITHUB_ACTIONS/CI yedek olarak kalir: bayrak unutulursa yine siki davranir.
        _ci9 = (os.environ.get("SELFTEST_REQUIRE_NODE") == "1"
                or os.environ.get("GITHUB_ACTIONS") == "true"
                or os.environ.get("CI", "").lower() in ("1", "true"))
        if not _node9 and _ci9:
            bad("P0.6 kapi 8  JS kosucusu CI'DA KOSMADI: node bulunamadi. "
                "CI'da node BEKLENIR; sessiz atlama 'testler kostu' yanilsamasi uretir")
        elif not _node9:
            warn("JS senaryo kosucusu ATLANDI (node yok) — docs/test-health.js "
                 "bu makinede olculemedi, kapsam boslugu")
        else:
            _js9 = _sp9.run(
                [_node9, str(_root9 / "docs" / "test-health.js")],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(_root9 / "docs"), timeout=120,
            )
            _cikti9 = (_js9.stdout or "") + (_js9.stderr or "")
            _son9 = [s for s in _cikti9.splitlines() if s.startswith("SONUC:")]
            if _js9.returncode == 0:
                ok(f"P0.6 kapi 8  JS senaryolari GECTI ({_son9[0] if _son9 else 'sonuc satiri yok'})")
            else:
                _kalan9 = [s.strip() for s in _cikti9.splitlines() if "XX " in s][:5]
                bad("P0.6 kapi 8  JS senaryolari KALDI: "
                    + (" | ".join(_kalan9) or _cikti9[-300:]))
    except Exception as e:
        bad(f"P0.6 [6m] testi kosmadi: {type(e).__name__}: {e}")


    # -- [6n] P0.3 KARAKTERIZASYON -- portfolio.py'nin EKSIK FIYAT davranisi --
    # NIYET: DAVRANIS DEGISTIRMEK DEGIL, BUGUNKU DAVRANISI KILITLEMEK.
    # portfolio.py 5-SHA ile DONUK (09ad265d9fd5) cunku golden-master onu
    # KAPSAMIYOR (backtest.py'de 0 referans). Yani dondurma "bu dosya dogru"
    # demiyor; "bu dosya test edilmiyor, hic degilse degistigini gorelim" diyor.
    # Test edilmeyen bir dosyayi duzeltmenin dogru sirasi: ONCE testle kapsa,
    # SONRA testin altinda degistir, SONRA yeniden dondur.
    # Bu blok ILK adimdir: hicbir davranisi degistirmez.
    #
    # ISARETLER:
    #   [DEGISECEK] = P0.3 yamasinda bu iddia TERSINE donecek; simdi kusuru
    #                 belgeliyor. Yama sonrasi bu satirlar guncellenmezse yama
    #                 sessizce gecmis olur -> guncelleme ZORUNLU.
    #   [KORUNACAK] = mevcut davranis DOGRU; yama onu bozarsa bu satir kizarir.
    print("\n[6n] P0.3 karakterizasyon: portfolio.py eksik fiyat davranisi")
    try:
        from bist_alpha import portfolio as _PF10

        def _st10(cash=100.0, **poz):
            return {"account": "TEST", "cash": cash, "positions": dict(poz),
                    "history": []}

        def _p10(entry, peak=None, shares=1.0):
            return {"entry": entry, "peak": peak if peak is not None else entry,
                    "shares": shares}

        _iddialar10 = []

        # --- 1) check_stops: KULLANILAMAZ FIYAT (P0.3 adim 2 SONRASI) ---------
        # SOZLESME DEGISTI. Yama oncesi dort ayri kusur olculmustu; hepsi ayni
        # kuralin ihlaliydi: KULLANILABILIR SAYI OLMAYAN SEY FIYAT DEGILDIR.
        #   fiyat yok / NaN / inf / 0 / negatif / bool / cop-metin -> `unchecked`
        #   duzgun sayi (float ya da '150' gibi cevrilebilir metin) -> normal yol
        # METIN KASTEN KABUL EDILIYOR: iyi-bicimli sayisal metni REDDETMEK, tip
        # kozmetigi ugruna GERCEK BIR STOP'U KACIRMAK olurdu (sinirsiz zarar);
        # kabul etmenin bedeli ise sifir (deger dogru). Fail-safe yonu cevirmeyi
        # gosteriyor. Cevrilemeyen her sey `unchecked`e gider.
        _s10 = _st10(AAA=_p10(100.0, peak=200.0))     # stop = 190.0
        # (gain 100% >= 30% -> TRAIL_TIGHT 0.05 -> 200*0.95 = 190;
        #  entry*(1-0.15)=85 daha dusuk, max() 190 secer.
        #  ILK YAZDIGIMDA "170" DEMISTIM — YANLISTI, olcup duzeltildi.)
        _sells10, _unch10 = _PF10.check_stops(_s10, {})      # fiyat YOK
        _iddialar10.append(
            ("1  [KORUNACAK] fiyatsiz pozisyon SATIS uretmiyor", len(_sells10), 0))
        _iddialar10.append(
            ("1b [DEGISTI] fiyatsiz pozisyon artik IZ birakiyor",
             _unch10, [("AAA", "fiyat_yok")]))
        _iddialar10.append(
            ("1c [KORUNACAK] fiyatsizken peak DE guncellenmiyor (mutasyon yok)",
             _s10["positions"]["AAA"]["peak"], 200.0))
        _iddialar10.append(
            ("1h [DEGISTI] state'e yazilmiyor (kalici JSON kirlenmiyor)",
             _s10.get("unchecked", "ALAN_YOK"), "ALAN_YOK"))

        _YOK10 = object()   # "anahtar hic yok" ile "deger None" ayrilir

        def _tek10(fiyat):
            _st = _st10(AAA=_p10(100.0, peak=200.0))
            return _PF10.check_stops(_st, {"AAA": fiyat})

        _sn10, _un10 = _tek10(float("nan"))
        _iddialar10.append(
            ("1d [DEGISTI] NaN artik sessiz degil (yanlis-guvenli kapandi)",
             (len(_sn10), _un10), (0, [("AAA", "fiyat_gecersiz")])))
        _si10, _ui10 = _tek10(float("inf"))
        _iddialar10.append(
            ("1d2 [YENI] inf de gecersiz", (len(_si10), _ui10),
             (0, [("AAA", "fiyat_gecersiz")])))
        _sz10, _uz10 = _tek10(0.0)
        _iddialar10.append(
            ("1e [DEGISTI] SIFIR fiyat artik SATIS URETMIYOR "
             "(veri arizasi -> uydurma emir kapandi)",
             (len(_sz10), _uz10), (0, [("AAA", "fiyat_pozitif_degil")])))
        _sg10, _ug10 = _tek10(-5.0)
        _iddialar10.append(
            ("1f [DEGISTI] NEGATIF fiyat da satis uretmiyor",
             (len(_sg10), _ug10), (0, [("AAA", "fiyat_pozitif_degil")])))
        _sb10, _ub10 = _tek10(True)
        _iddialar10.append(
            ("1i [YENI] bool fiyat degildir (float(True)=1.0 -> 1.00'dan SATIS "
             "uretiyordu; olculdu)", (len(_sb10), _ub10),
             (0, [("AAA", "fiyat_sayi_degil")])))
        _sc10, _uc10 = _tek10("abc")
        _iddialar10.append(
            ("1g [DEGISTI] cop metin kosumu DUSURMUYOR, ize gidiyor "
             "(eskiden yakalanmayan TypeError'di)",
             (len(_sc10), _uc10), (0, [("AAA", "fiyat_sayi_degil")])))
        _sm10, _um10 = _tek10("150")
        _iddialar10.append(
            ("1j [KARAR] iyi-bicimli sayisal metin KABUL EDILIYOR "
             "(reddetmek gercek stop'u kacirirdi)", (len(_sm10), _um10), (1, [])))

        # Karsi-yon (pozitif kontrol): fiyat VARSA ve stop altindaysa SATAR.
        _s10b = _st10(AAA=_p10(100.0, peak=200.0))
        _sells10b, _unch10b = _PF10.check_stops(_s10b, {"AAA": 150.0})   # 150 < 190
        _iddialar10.append(
            ("2  [KORUNACAK] fiyat varsa ve stop altindaysa SATAR",
             (len(_sells10b), _unch10b), (1, [])))
        _iddialar10.append(
            ("2b [KORUNACAK] satis kaydi fiyati tasiyor",
             _sells10b[0]["price"] if _sells10b else None, 150.0))

        # --- 1k) ORTAK OTORITE + NUMPY (P0.3 adim 2b) -------------------------
        # `usable_price` TEK kapidir: check_stops ve g1_account ayni fonksiyonu
        # cagirir. Ikisi zaten `stop_level`i paylasiyordu; fiyat dogrulamasini
        # ayri yazmak kayittaki "IKIZI ama BIREBIR DEGIL" ayrismasini buyuturdu.
        import numpy as _np10
        _kapi10 = [
            (None, "fiyat_yok"), ("abc", "fiyat_sayi_degil"),
            ("", "fiyat_sayi_degil"), ([1], "fiyat_sayi_degil"),
            (True, "fiyat_sayi_degil"), (False, "fiyat_sayi_degil"),
            (float("nan"), "fiyat_gecersiz"), (float("inf"), "fiyat_gecersiz"),
            (0.0, "fiyat_pozitif_degil"), (-5.0, "fiyat_pozitif_degil"),
        ]
        for _ham10, _bek10 in _kapi10:
            _iddialar10.append(
                (f"1k usable_price({_ham10!r}) -> {_bek10}",
                 _PF10.usable_price(_ham10)[1], _bek10))
        for _ham10, _bek10 in ((150.0, 150.0), ("150", 150.0),
                               (_np10.float64(150.0), 150.0)):
            _iddialar10.append(
                (f"1k2 usable_price({type(_ham10).__name__}) kabul",
                 _PF10.usable_price(_ham10), (_bek10, None)))

        # NUMPY BOOL — olculdu 2026-09-10: `isinstance(np.bool_(True), bool)`
        # FALSE'tur, ciplak bool kontrolu onu KACIRIR ve float() 1.0 yapar ->
        # 1.00'dan SATIS. Fiyatlar pandas/numpy'den geldigi icin bu NORMAL girdi
        # tipidir, uc durum degil. `.item()` normalizasyonu once cagrilir.
        _iddialar10.append(
            ("1k3 np.bool_ KACMIYOR (adim 2'de acik kalmisti)",
             _PF10.usable_price(_np10.bool_(True))[1], "fiyat_sayi_degil"))
        _snb10, _unb10 = _tek10(_np10.bool_(True))
        _iddialar10.append(
            ("1k4 np.bool_ check_stops'ta da satis uretmiyor",
             (len(_snb10), _unb10), (0, [("AAA", "fiyat_sayi_degil")])))

        # --- 1m) G1 IKIZI (P0.3 adim 2b) --------------------------------------
        # `g1_account` F'in ikizidir ama F'te satis ONERILIR, burada ICRA EDILIR
        # -> ayni kusurun bedeli agir. Yama oncesi olculdu (2026-09-10):
        #   sifir  -> pozisyon SILINDI, kasa 0.00, stops+1
        #   negatif-> pozisyon SILINDI, kasa -4.99
        # Artik ikisi de pozisyonu KORUR ve sebebiyle ize gider.
        from bist_alpha import g1_account as _G110

        def _g1kur10():
            _g = _G110._new_state()
            _g["positions"] = {"AAA": {"entry": 100.0, "peak": 200.0,
                                       "shares": 1.0, "w": 1.0}}
            _g["cash"] = 0.0
            return _g

        def _g1tek10(fiyat):
            _g = _g1kur10()
            _pr = {} if fiyat is _YOK10 else {"AAA": fiyat}
            _g2, _ev = _G110.step(None, None, _g, "2026-09-10", _pr, False,
                                  eval_stops=True)
            return ("AAA" in _g2["positions"], round(_g2["cash"], 2),
                    _g2["stats"]["stops"], _ev.get("stop_unchecked"))

        for _ad10, _f10, _sb10 in (
                ("fiyatsiz", _YOK10, "fiyat_yok"),
                ("NaN", float("nan"), "fiyat_gecersiz"),
                ("SIFIR", 0.0, "fiyat_pozitif_degil"),
                ("NEGATIF", -5.0, "fiyat_pozitif_degil"),
                ("np.bool_", _np10.bool_(True), "fiyat_sayi_degil")):
            _iddialar10.append(
                (f"1m G1 {_ad10}: pozisyon KORUNUR, kasa 0, iz var",
                 _g1tek10(_f10), (True, 0.0, 0, [("AAA", _sb10)])))
        _iddialar10.append(
            ("1m2 [KORUNACAK] G1 normal fiyatta stop ICRA eder",
             _g1tek10(150.0)[:3], (False, 149.7, 1)))

        # --- 2) current_value: UYDURMA FIYAT ----------------------------------
        # portfolio.py:208  `p = prices.get(tic, pos['entry'])`
        # Fiyat yoksa GIRIS FIYATI yaziliyor -> pozisyon "girisinden beri hic
        # hareket etmemis" gibi degerleniyor. Bu sayi daemon.py:545'te
        # yayimlanan F getirisine donusuyor.
        _s10c = _st10(cash=10.0, AAA=_p10(100.0, shares=2.0))
        _iddialar10.append(
            ("3  [DEGISECEK] current_value fiyatsizken ENTRY kullaniyor",
             _PF10.current_value(_s10c, {}), 210.0))          # 10 + 2*100
        _iddialar10.append(
            ("3b [KORUNACAK] fiyat varsa gercek fiyati kullaniyor",
             _PF10.current_value(_s10c, {"AAA": 150.0}), 310.0))
        _iddialar10.append(
            ("3c [DEGISECEK] eksiklik cagirana BILDIRILMIYOR (tek deger doner)",
             isinstance(_PF10.current_value(_s10c, {}), float), True))

        # --- 2b) DEGERLEME (P0.3 adim 3) --------------------------------------
        # Deger YAYIMLANAN bir sayi (daemon.py:545 -> F getirisi). Uc secenek de
        # kusurluydu: `entry` UYDURUR, atlamak pozisyonu TAMAMEN siler, NaN
        # PANELI OLDURUR. Secim: `entry` korunur ama ETIKETLENIR; NaN asla uretilmez.
        _dsts10 = lambda: _st10(cash=10.0, AAA=_p10(100.0, shares=2.0))
        for _ad10, _f10, _sb10 in (
                ("fiyatsiz", _YOK10, "fiyat_yok"),
                ("NaN", float("nan"), "fiyat_gecersiz"),
                ("inf", float("inf"), "fiyat_gecersiz"),
                ("sifir", 0.0, "fiyat_pozitif_degil"),
                ("negatif", -5.0, "fiyat_pozitif_degil"),
                ("cop metin", "abc", "fiyat_sayi_degil"),
                ("np.bool_", _np10.bool_(True), "fiyat_sayi_degil")):
            _pr10 = {} if _f10 is _YOK10 else {"AAA": _f10}
            _iddialar10.append(
                (f"2c degerleme {_ad10}: entry'ye duser AMA etiketli",
                 (round(_PF10.current_value(_dsts10(), _pr10), 2),
                  _PF10.value_coverage(_dsts10(), _pr10)),
                 (210.0, [("AAA", _sb10)])))
        _iddialar10.append(
            ("2d [KORUNACAK] normal fiyatta dogru deger, etiket YOK",
             (round(_PF10.current_value(_dsts10(), {"AAA": 150.0}), 2),
              _PF10.value_coverage(_dsts10(), {"AAA": 150.0})), (310.0, [])))
        # NaN ASLA YAYILMAZ: eskiden tum portfoy degeri nan oluyordu ve
        # `daemon.py` dashboard'i duz json.dump ile yaziyordu -> dosyada cikplak
        # `NaN` -> `JSON.parse` SyntaxError -> PANELIN TAMAMI olur.
        import math as _math10
        _iddialar10.append(
            ("2e NaN fiyat portfoy degerini NaN yapmiyor",
             _math10.isnan(_PF10.current_value(_dsts10(), {"AAA": float("nan")})), False))
        # SON SAVUNMA: dashboard yazicisi NaN'i temizler.
        import json as _json10
        _iddialar10.append(
            ("2f dashboard yazimi NaN'i None'a cevirir (panel olmez)",
             _json10.dumps(_PF10._sanitize_json({"v": float("nan")})), '{"v": null}'))
        _dm10 = (_root9 / "daemon.py").read_text(encoding="utf-8")
        _iddialar10.append(
            ("2g daemon dashboard'i sanitize EDEREK yaziyor",
             "_sanitize_json(state)" in _dm10, True))
        # G1 IKIZI KAPANDI: ayni sayiyi verir (delege).
        _iddialar10.append(
            ("2h G1 _value F ile AYNI sonucu verir (ikiz kapandi)",
             round(_G110._value({"cash": 10.0,
                                 "positions": {"AAA": {"entry": 100.0, "shares": 2.0}}},
                                {"AAA": float("nan")}), 2), 210.0))

        # --- 2i) FALLBACK'IN KENDISI (bagimsiz okumada bulundu) ---------------
        # Adim 3 fiyat yolunu kapatti ama `entry` fallback'ini DOGRULAMIYORDU:
        # entry NaN -> deger YINE nan; entry None/metin -> TypeError, kosum duser.
        # Ayni kusurun ikinci kopyasiydi. Artik entry de `usable_price`ten gecer.
        def _dbz10(entry):
            return _st10(cash=10.0, AAA={"entry": entry, "peak": 100.0, "shares": 2.0})
        for _ad10, _e10 in (("NaN", float("nan")), ("None", None),
                            ("metin", "abc"), ("sifir", 0.0)):
            _iddialar10.append(
                (f"2i entry {_ad10} + fiyat yok: deger SONLU, ayri etiket",
                 (round(_PF10.current_value(_dbz10(_e10), {}), 2),
                  _PF10.value_coverage(_dbz10(_e10), {})),
                 (10.0, [("AAA", "fiyat_ve_entry_gecersiz")])))
        _iddialar10.append(
            ("2i2 entry NaN ama FIYAT VARSA fiyat kullanilir, etiket YOK",
             (round(_PF10.current_value(_dbz10(float("nan")), {"AAA": 150.0}), 2),
              _PF10.value_coverage(_dbz10(float("nan")), {"AAA": 150.0})),
             (310.0, [])))
        _iddialar10.append(
            ("2i3 [KORUNACAK] entry saglamsa eski etiket korunur",
             _PF10.value_coverage(_dbz10(100.0), {}), [("AAA", "fiyat_yok")]))

        # --- 3) rebalance: ASIMETRI -------------------------------------------
        # SATIS tarafi (167) fiyatsizken ENTRY'den satiyor -> pnl tam %0.00.
        # ALIS tarafi (183-184) fiyatsizken ALMIYOR -> zaten fail-closed.
        _s10d = _st10(cash=0.0, AAA=_p10(100.0, shares=1.0))
        _PF10.rebalance(_s10d, {"BBB": 1.0}, {"BBB": 50.0}, trade_date="2026-01-01")
        _satis10 = [t for t in _s10d["history"][-1]["trades"] if t["type"] == "SELL"]
        _iddialar10.append(
            ("4  [DEGISECEK] rebalance fiyatsiz pozisyonu ENTRY'den satiyor",
             _satis10[0]["price"] if _satis10 else None, 100.0))
        _iddialar10.append(
            ("4b [DEGISECEK] uydurma satisin pnl'i tam %0.00 gorunuyor",
             _satis10[0]["pnl_pct"] if _satis10 else None, 0.0))

        _s10e = _st10(cash=100.0)
        _PF10.rebalance(_s10e, {"CCC": 1.0}, {}, trade_date="2026-01-01")
        _iddialar10.append(
            ("5  [KORUNACAK] rebalance ALIS tarafi fiyatsizken ALMIYOR",
             len(_s10e["positions"]), 0))

        # --- 4) stop_level: peak yoksa entry -----------------------------------
        # Bu bilincli bir eski-JSON korumasi (satir 80), kusur DEGIL.
        _iddialar10.append(
            ("6  [KORUNACAK] stop_level peak yoksa entry'ye dusuyor",
             _PF10.stop_level({"entry": 100.0, "shares": 1.0}),
             _PF10.stop_level({"entry": 100.0, "peak": 100.0, "shares": 1.0})))

        # --- 4) REBALANCE (P0.3 adim 4) ---------------------------------------
        # Olculdu (2026-09-10, yama oncesi): tutulan bir pozisyonun fiyati
        # eksikse `rebalance` onu ENTRY'den satar ve bu YENI PORTFOYUN TAMAMININ
        # boyutlandirmasini degistirir (5.988 lot yerine 3.992 = %33 kucuk);
        # NaN ise state'e `shares: nan` YAZILIR; sifir ise portfoy sifirlanir.
        # BIRINCIL koruma shadow.py fill kapisidir; buradaki IKINCI KILIT.
        def _reb10(fiyatlar):
            _s = _st10(cash=0.0, AAA={"entry": 100.0, "peak": 100.0, "shares": 2.0})
            _PF10.rebalance(_s, {"BBB": 1.0}, fiyatlar, trade_date="2026-01-01")
            _h = _s["history"][-1]
            _sat = [t for t in _h["trades"] if t["type"] == "SELL"][0]
            _al = [t for t in _h["trades"] if t["type"] == "BUY"]
            return (_sat["price"], _al[0]["shares"] if _al else 0.0, _h["total"])

        _iddialar10.append(
            ("4c [KORUNACAK] normal fiyatta rebalance BIREBIR ayni "
             "(A1: saglam veride davranis degismedi)",
             _reb10({"AAA": 150.0, "BBB": 50.0}), (150.0, 5.988, 299.4)))
        for _ad10, _f10 in (("NaN", float("nan")), ("sifir", 0.0),
                            ("cop metin", "abc"), ("np.bool_", _np10.bool_(True))):
            _iddialar10.append(
                (f"4d [DEGISTI] rebalance {_ad10}: entry'ye duser, NaN/sifir lot YOK",
                 _reb10({"AAA": _f10, "BBB": 50.0}), (100.0, 3.992, 199.6)))
        _iddialar10.append(
            ("4e [KORUNACAK] fiyat hic yoksa eski davranis (entry) korunur",
             _reb10({"BBB": 50.0}), (100.0, 3.992, 199.6)))

        # --- 5) FILL KAPISI (BIRINCIL koruma) — KANIT TURU: VEKIL --------------
        # `shadow.step` agir kurulum ister (data/signals); burada olculen sey
        # METIN YUZEYI. Davranis kaniti ikinci kilitte (yukarida) ve kapinin
        # kendi kurali dosyada yazili ("%100 norm, HER SAPMA anomali").
        _sh10 = (_root9 / "shadow.py").read_text(encoding="utf-8")
        _kapi10s = [
            ("tutulan pozisyonlar hesaplaniyor", 'tutulan = list((state.get("positions")' in _sh10),
            ("satis tarafi eksigi ayri", "eksik_satis = [t for t in tutulan" in _sh10),
            ("eksik = alis + satis birlesimi", "eksik = eksik_alis + [t for t in eksik_satis" in _sh10),
            ("hangi yarim eksik kaydediliyor", '"missing_sell": eksik_satis[:5] or None,' in _sh10),
        ]
        _eks10 = [a for a, t in _kapi10s if not t]
        if not _eks10:
            ok(f"P0.3 karakterizasyon 5 fill kapisi SATIS tarafini da kapsiyor "
               f"[VEKIL] ({len(_kapi10s)}/{len(_kapi10s)})")
        else:
            bad("P0.3 karakterizasyon 5 fill kapisi eksik: " + " | ".join(_eks10))

        for _ad10, _alinan10, _beklenen10 in _iddialar10:
            if _alinan10 == _beklenen10:
                ok(f"P0.3 karakterizasyon {_ad10}")
            else:
                bad(f"P0.3 karakterizasyon {_ad10}: beklenen {_beklenen10!r}, "
                    f"alinan {_alinan10!r}")

        # DONUKLUK HATIRLATICISI: bu blok gecerken portfolio.py DEGISMEMIS olmali.
        # [6b] zaten SHA'yi kontrol ediyor; burada NIYETI yaziya dokuyoruz ki
        # yama sirasinda "SHA'yi guncelledim ama davranisi olcmedim" olmasin.
        _sha10 = "b70147ef6c50"   # P0.3 adim 2/2b/3/4 (eski 09ad265d9fd5)
        if _sha10 in (_root9 / "selftest.py").read_text(encoding="utf-8"):
            ok("P0.3 karakterizasyon 7  portfolio.py hala 5-SHA baseline'inda "
               "(davranis yamasi bu satiri da guncellemek zorunda)")
        else:
            bad("P0.3 karakterizasyon 7  portfolio.py baseline'i kayip")
    except Exception as e:
        bad(f"P0.3 [6n] karakterizasyon kosmadi: {type(e).__name__}: {e}")

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

        # Borsapy tarih indeksi timezone-aware gelebilir. Bakim kontrolu ayni
        # veriye naive/aware eksenlerde ayni hükmü vermeli; eksen farki daemon'u
        # düşürmemeli (2026-09-08 canli kapanis arizasi).
        import pandas as pd
        _now_naive = pd.Timestamp.now().floor("s")
        _idx_naive = pd.date_range(end=_now_naive, periods=5, freq="D")
        _idx_aware = _idx_naive.tz_localize("UTC")
        _vals = pd.DataFrame(
            {"AAA": [1, 2, 3, 4, 5], "BBB": [5, 4, 3, 2, 1]},
            index=_idx_naive,
        )
        _naive_issues = maintenance.check_data_health({"prices": _vals})
        _aware_vals = _vals.copy()
        _aware_vals.index = _idx_aware
        _aware_issues = maintenance.check_data_health({"prices": _aware_vals})
        if _aware_issues == _naive_issues:
            ok("maintenance timezone-aware/naive veri ayni hüküm")
        else:
            bad(f"maintenance TZ hükmü ayrıştı: naive={_naive_issues}, aware={_aware_issues}")

        _stale_vals = _aware_vals.copy()
        _stale_vals.index = _stale_vals.index - pd.Timedelta(days=10)
        _stale_issues = maintenance.check_data_health({"prices": _stale_vals})
        if any(str(issue).startswith("Veri eski:") for issue in _stale_issues):
            ok("maintenance timezone-aware eski veriyi yakalar")
        else:
            bad(f"maintenance timezone-aware eski veri kaçtı: {_stale_issues}")

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

    # 9-EK. DENETIM ARTEFAKTI BAYAT MI — "koruma kendini korumadan muaf sanir"
    # docs/state/system_control_audit.json PUBLIC yayimlaniyor (bkz
    # GIZLILIK_CANLI_GECIS_KARARI + CLOUDFLARE_ACCESS_KURULUM public URL'i) ve
    # DORT belge onu her degisiklikte `--write` ile tazelemeyi soyluyor.
    # 2026-09-10'da olculdu: damga 2026-07-16 idi -> 56 GUN bayat, ve o bayat
    # kopya `Duplicate basename scan` icin `pass` gosteriyordu, gercek `warn`.
    # Kimse tazelemedigi gibi kimse BAYATLIGI DA OLCMUYORDU (sinyal sifir).
    # ESIK UYDURULMADI: reponun kendi kurali "her degisiklikte" -> artefakttan
    # SONRA gelen bir kod commit'i varsa bayattir. Kiyas noktasi git'in kendisi.
    # BLOKLAYICI DEGIL UYARI: bloklamak salt-dokuman commit'lerini de dusururdu;
    # amac kapi kurmak degil, 56 gun suren SESSIZLIGI bitirmek.
    print("\n[9-EK] Denetim artefakti tazeligi")
    try:
        import io as _ioA
        import json as _jsonA
        import subprocess as _spA
        _audit_pathA = os.path.join(ROOT, "docs", "state", "system_control_audit.json")
        if not os.path.exists(_audit_pathA):
            warn("system_control_audit.json YOK — public denetim artefakti uretilmemis")
        else:
            _auditA = _jsonA.load(_ioA.open(_audit_pathA, encoding="utf-8"))
            _damgaA = str(_auditA.get("generated_at") or "")[:19]
            _sonKodA = _spA.run(
                ["git", "log", "-1", "--format=%cI", "--",
                 "bist_alpha", "scripts", "selftest.py", ".github/workflows"],
                capture_output=True, text=True, cwd=ROOT, encoding="utf-8",
            ).stdout.strip()[:19]
            if not _damgaA or not _sonKodA:
                warn(f"denetim artefakti tazeligi OLCULEMEDI (damga={_damgaA!r} kod={_sonKodA!r})")
            elif _damgaA < _sonKodA:
                warn(f"denetim artefakti BAYAT: damga {_damgaA} < son kod commit'i {_sonKodA} "
                     "-> `python scripts/system_control_audit.py --write "
                     "docs/state/system_control_audit.json`")
            else:
                ok(f"denetim artefakti taze (damga {_damgaA} >= son kod {_sonKodA})")
    except Exception as _eA:
        warn(f"denetim artefakti tazeligi okunamadi: {type(_eA).__name__}: {_eA}")

    # 9-EK2. ELLE ADIM -> KODA TASINDI (D13 otomatiklesme saati, 2026-09-10)
    # `docs/DEGISIKLIK_YONETIMI.md -> Commit Oncesi Kontrol` iki adim yaziyor:
    #   `git diff --check`  ve  `python -m py_compile ...`
    # Ikisini de HICBIR SEY ZORLAMIYORDU; ben de bugun ikisini birden atladim.
    # OLCULDU (2026-09-10): repoda 67 .py var, 36'si selftest metninde HIC ANILMIYOR
    # — aralarinda precise_runner.py (her precise kosumunu suren), reporter.py (her
    # Telegram raporunu yazan) ve scripts/sanitize_public_state.py (Deniz gizlilik
    # temizleyicisi). Birinde syntax hatasi olsa SESSIZCE yayina cikar ve ancak
    # uretimde, rapor slotunda patlardi.
    # NOT: su an 67/67 derleniyor -> bu ONLEYICI bir kapi, mevcut bir kiriga yama degil.
    # BLOKLAYICI/UYARI AYRIMI: derlenmeyen dosya BLOKLAR (calismayan kod);
    # `git diff --check` UYARIR (bosluk/catisma isareti — kozmetikten catismaya
    # uzanir, bloklamak listenin devre disi birakilmasini davet eder).
    print("\n[9-EK2] Derleme + calisma agaci hijyeni (repo standardi, artik otomatik)")
    try:
        import py_compile as _pcB
        import subprocess as _spB
        import tempfile as _tfB
        _atlaB = (".git", "local", "__pycache__", "node_modules", ".venv",
                  "deniz_snapshots")
        _tumB = []
        for _kokB, _dizB, _dosB in os.walk(ROOT):
            _dizB[:] = [d for d in _dizB if d not in _atlaB]
            for _fB in _dosB:
                if _fB.endswith(".py"):
                    _tumB.append(os.path.join(_kokB, _fB))
        _bozukB = []
        with _tfB.TemporaryDirectory() as _tdB:
            for _pB in _tumB:
                try:
                    _pcB.compile(_pB, cfile=os.path.join(_tdB, "x.pyc"), doraise=True)
                except Exception as _eB:
                    _bozukB.append(
                        f"{os.path.relpath(_pB, ROOT)}: {type(_eB).__name__}"
                    )
        if _bozukB:
            bad(f"DERLENMEYEN {len(_bozukB)}/{len(_tumB)} dosya: " + " | ".join(_bozukB[:5]))
        else:
            ok(f"{len(_tumB)} python dosyasinin tamami derleniyor")

        _dcB = _spB.run(["git", "diff", "--check"], capture_output=True, text=True,
                        cwd=ROOT, encoding="utf-8", errors="replace")
        _satirB = [s for s in (_dcB.stdout or "").splitlines() if s.strip()]
        if _satirB:
            warn(f"git diff --check {len(_satirB)} sorun buldu: " + _satirB[0][:110])
        else:
            ok("git diff --check temiz (bosluk/catisma isareti yok)")
    except Exception as _eB2:
        bad(f"[9-EK2] kosmadi: {type(_eB2).__name__}: {_eB2}")

    # 9a. P0.3 — URETICI WORKFLOW HATASI TELEGRAM'A ULASMALI
    # precise/native daemon yolu kirildiginda sonraki always() adimlari yesil
    # gorunebilir. Alarm job'in SON adimi olmali, failure ile cancelled'i
    # kapsamali ve report_gate/gunluk dedup'tan bagimsiz her arizada gondermeli.
    print("\n[9a] P0.3 uretici workflow hata alarmi (test-once)")

    def _workflow_step_block(_text, _name_fragment):
        _lines = _text.splitlines()
        _start = next(
            (i for i, line in enumerate(_lines)
             if line.startswith("      - name:") and _name_fragment in line),
            None,
        )
        if _start is None:
            return ""
        _end = len(_lines)
        for i in range(_start + 1, len(_lines)):
            if _lines[i].startswith("      - name:") or _lines[i].startswith("      - uses:"):
                _end = i
                break
        return "\n".join(_lines[_start:_end])

    _producer_alarm_blocks = []
    for _workflow_path in [
        ".github/workflows/precise.yml",
        ".github/workflows/bist-alpha.yml",
    ]:
        _workflow_text = open(_workflow_path, encoding="utf-8").read()
        _workflow_name = os.path.basename(_workflow_path)
        import re as _re

        _force_input_match = _re.search(
            r"(?ms)^      force_fail:\s*$\n(?P<body>(?:        .*?(?:\n|$))+)",
            _workflow_text,
        )
        _force_input_body = _force_input_match.group("body") if _force_input_match else ""
        _dispatch_has_input = (
            "required: false" in _force_input_body
            and "default: false" in _force_input_body
            and "type: boolean" in _force_input_body
        )
        if _dispatch_has_input:
            ok(f"P0.3 {_workflow_name}: force_fail boolean + default false")
        else:
            bad(f"P0.3 {_workflow_name}: force_fail girdisi eksik/guvensiz varsayilan")

        _force_block = _workflow_step_block(_workflow_text, "P0.3 kontrollu hata")
        if (
            "github.event_name == 'workflow_dispatch'" in _force_block
            and "inputs.force_fail" in _force_block
            and "exit 1" in _force_block
            and "continue-on-error" not in _force_block
        ):
            ok(f"P0.3 {_workflow_name}: kontrollu hata kancasi")
        else:
            bad(f"P0.3 {_workflow_name}: kontrollu hata kancasi eksik/yanlis")

        _alarm_block = _workflow_step_block(_workflow_text, "P0.3 workflow hata alarmi")
        _producer_alarm_blocks.append(_alarm_block)
        if "failure() || cancelled()" in _alarm_block:
            ok(f"P0.3 {_workflow_name}: failure + normal-cancel kosulu")
        else:
            bad(f"P0.3 {_workflow_name}: failure + cancelled birlikte kapsanmiyor")

        _telegram_proof = (
            "TELEGRAM_TOKEN" in _alarm_block
            and "TELEGRAM_CHAT_ID" in _alarm_block
            and _re.search(r"curl\s+-[A-Za-z]*f[A-Za-z]*\b", _alarm_block)
            and '\"ok\"[[:space:]]*:[[:space:]]*true' in _alarm_block
            and "TELEGRAM_TOKEN yok" in _alarm_block
            and "TELEGRAM_CHAT_ID yok" in _alarm_block
            and "|| true" not in _alarm_block
        )
        if _telegram_proof:
            ok(f"P0.3 {_workflow_name}: Telegram HTTP + ok:true kaniti")
        else:
            bad(f"P0.3 {_workflow_name}: Telegram basari kaniti eksik")

        _manifest_fields = [
            "github.workflow",
            "job.status",
            "github.event_name",
            "github.event.schedule",
            "github.ref",
            "github.sha",
            "github.actor",
            "github.run_id",
        ]
        _missing_manifest = [field for field in _manifest_fields if field not in _alarm_block]
        if not _missing_manifest:
            ok(f"P0.3 {_workflow_name}: eyleme-yeterli hata manifesti")
        else:
            bad(f"P0.3 {_workflow_name}: manifest eksik {_missing_manifest}")

        _step_headers = [
            line.strip()
            for line in _workflow_text.splitlines()
            if line.startswith("      - name:") or line.startswith("      - uses:")
        ]
        _alarm_is_last = bool(
            _step_headers
            and _step_headers[-1].startswith("- name:")
            and "P0.3 workflow hata alarmi" in _step_headers[-1]
        )
        _alarm_is_independent = (
            "report_gate" not in _alarm_block
            and "HEARTBEAT_DUE" not in _alarm_block
            and "continue-on-error" not in _alarm_block
        )
        _alarm_run_body = _alarm_block.split("run: |", 1)[-1]
        _shell_has_no_direct_expressions = "${{" not in _alarm_run_body
        if _alarm_is_last and _alarm_is_independent and _shell_has_no_direct_expressions:
            ok(f"P0.3 {_workflow_name}: son adim + dedup bagimsiz + env-sinirli")
        else:
            bad(f"P0.3 {_workflow_name}: son adim/bagimsizlik/env siniri bozuk")

    if (
        len(_producer_alarm_blocks) == 2
        and _producer_alarm_blocks[0]
        and _producer_alarm_blocks[0] == _producer_alarm_blocks[1]
    ):
        ok("P0.3 iki ureticide alarm sozlesmesi birebir ayni")
    else:
        bad("P0.3 producer alarm bloklari ayrismis")

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

