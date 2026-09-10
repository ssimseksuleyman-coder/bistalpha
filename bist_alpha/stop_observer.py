"""P0.6 / madde 7 — BAGIMSIZ STOP GOZLEMI.

NEDEN AYRI BIR MODUL (2026-09-08 canli vakasi):
  Veri kapisi Yahoo'yu reddedince `safe_feed` dustu, daemon exit 1 verdi ve O GUN
  STOPLAR HIC DEGERLENDIRILMEDI. Rapor uretimi ile stop guvenligi AYNI yola bagli
  oldugu icin veri deligi stop korumasini da dusurdu.

  Ayrim su olcume dayanir (2026-09-10):
    Yahoo GECMIS kapisindan REDDEDILDI (09-07 deligi, %17.5 kapsam)
    Yahoo 4 pozisyonun GUNCEL fiyatini DOGRU verdi (borsapy ile %0.00-0.11 fark)
  => Kapinin reddi SUREKLILIK hakkindadir, ANLIK FIYAT gecerliligi hakkinda degil.
  Stop yalnizca guncel fiyat + kayitli entry/peak ister; gecmise ihtiyaci YOKTUR.
  Bu yuzden bu modul `selfheal.safe_feed`'i KULLANMAZ — kapiyi BILEREK atlar.
  (Biri ileride "neden gate'i atliyor" deyip baglarsa senaryo-3 sessizce olur.)

BES BAGLAYICI KARAR (P0.6/madde-7 kaydi, 2026-09-10):
  1. Her kosuda calisir — yalniz-arizada calisan bir yedek, tam ihtiyac duyuldugu
     gun bozuk cikar (#0b dersi: hic kosmamis yedek, yedek degildir).
  2. YALNIZ TESPIT: emir vermez, portfolio state'ini DEGISTIRMEZ. Icra, P0.5
     (atomik state) kapandiktan sonra ayri karardir.
  3. Stop seviyesi TEK OTORITE: `portfolio.stop_level`. Ucuncu bir uygulama
     dogmamali (mevcut iki uygulama yalniz SHA dondurmasiyla hizada tutuluyor).
     Cagri MODUL ATTRIBUTE uzerinden yapilir ki otorite test edilebilsin.
  4. Ayri artefakt: `stop_eval.json`'a YAZMAZ. O dosyanin BAYATLIGI #0l'in
     kor-nokta sinyalidir (`_write_stop_eval` yalniz kapanista yazar).
  5. `portfolio.py`'ye YAZILMAZ — o dosya 5-SHA donuk (09ad265d9fd5); icine
     fonksiyon eklemek [6b]'yi kirar ve A1'i ihlal ettirir.

FAIL-SAFE YONU (P0.3): pozisyon basina `priced` / `missing`.
  Fiyati olmayan pozisyon SESSIZCE ATLANMAZ ve giris fiyatiyla DOLDURULMAZ.
  `breached` uc durumludur: True / False / None. `None` = OLCULEMEDI.
  "Bilinmiyor" ile "guvenli" ayni sey degildir.

ALARM KOSULU: yalniz `breached`. `missing` veri-kalitesi durumudur ve
  kendiliginden cozulmez; her kosuda Telegram'a gitse alarm korlugu uretir.
  `missing` ize ve operasyon kapisina gider.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import portfolio

REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVER_OUT = REPO_ROOT / "docs" / "state" / "stop_observer.json"
SCHEMA_VERSION = 1


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_path(account, state_dir=None):
    base = Path(state_dir) if state_dir is not None else REPO_ROOT / "portfolios"
    return base / f"portfolio_{account}.json"


def _display_path(path):
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_state(account, state_dir=None):
    """State'i sifirlamadan oku; yokluk, bozukluk ve gecerli bos state ayridir."""
    path = _state_path(account, state_dir)
    meta = {"account": account, "path": _display_path(path)}
    if not path.is_file():
        return None, {**meta, "status": "missing"}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, {
            **meta,
            "status": "unreadable",
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        }
    if not isinstance(state, dict) or not isinstance(state.get("positions"), dict):
        return None, {**meta, "status": "invalid", "error": "positions dict degil"}
    return state, {
        **meta,
        "status": "loaded",
        "position_count": len(state.get("positions", {})),
    }


def load_states(accounts, state_dir=None):
    """Tum hesaplari mutasyon yapmadan yukler ve her hesabin durumunu raporlar."""
    states, statuses = {}, {}
    for account in accounts:
        state, status = load_state(account, state_dir=state_dir)
        statuses[account] = status
        if state is not None:
            states[account] = state
    return states, statuses


def evaluate_stops(state, prices_today, price_dates=None):
    """Pozisyon basina stop gozlemi. SAF: state'i DEGISTIRMEZ, emir uretmez.

    Doner: [{ticker, status, price, price_date, stop_level, breached, entry, peak}, ...]
      status  = "priced"  -> fiyat bulundu, breached True/False
              = "missing" -> fiyat yok,     breached None (OLCULEMEDI)
      breached: None asla False'a indirgenmez — bilinmiyor != guvenli.

    `price_date` fiyatin ALINDIGI BAR GUNUDUR, gozlemin kosma gunu DEGIL.
    Ikisi ayni olmayabilir (islem durdurma, tatil, kaynak gecikmesi) ve fark
    gorunmezse panel bayat fiyat uzerinden kendinden emin YESIL gosterir.
    Bayatlik burada OLCULUR, HUKME cevrilmez (esik uydurulmaz).

    `peak` GUNCELLENMEZ: peak tazelemek bir state mutasyonudur ve ana yolun isidir.
    Gozlemci son yetkili state'e gore olcer.
    """
    rows = []
    dates = price_dates or {}
    positions = (state or {}).get("positions") or {}
    for ticker in sorted(positions):
        pos = positions[ticker]
        if not isinstance(pos, dict):
            rows.append({
                "ticker": ticker, "status": "invalid", "price": None,
                "price_date": None,
                "stop_level": None, "breached": None, "entry": None, "peak": None,
                "reason": "invalid_position",
            })
            continue

        # OTORITE: modul attribute uzerinden -> tek kaynak, test edilebilir.
        level_error = None
        try:
            level = portfolio.stop_level(pos)
            level = float(level) if level is not None and math.isfinite(float(level)) else None
        except Exception as exc:
            level = None
            level_error = f"{type(exc).__name__}: {str(exc)[:120]}"

        raw = (prices_today or {}).get(ticker)
        try:
            price = float(raw) if raw is not None and math.isfinite(float(raw)) else None
        except (TypeError, ValueError, OverflowError):
            price = None

        if price is None or level is None:
            reason = (
                "stop_level_error" if level_error
                else "stop_level_missing" if level is None
                else "price_missing" if raw is None
                else "price_invalid"
            )
            rows.append({
                "ticker": ticker, "status": "missing", "price": None,
                "price_date": None,
                "stop_level": level, "breached": None,
                "entry": pos.get("entry"), "peak": pos.get("peak"),
                "reason": reason,
            })
            continue

        rows.append({
            "ticker": ticker, "status": "priced", "price": price,
            "price_date": dates.get(ticker),
            "stop_level": level, "breached": bool(price < level),
            "entry": pos.get("entry"), "peak": pos.get("peak"),
            "reason": "priced",
        })
    return rows


def any_breach(account_rows):
    """Alarm YALNIZ burada True doner. `missing` alarm URETMEZ (karar 3)."""
    for rows in (account_rows or {}).values():
        for row in rows or []:
            if row.get("breached") is True:
                return True
    return False


def gate_verdict(position_count, unpriced_count, unavailable_count, loaded_count):
    """Operasyon kapisi hukmu — TUKETICISI OLAN cikti (P0.6 kapi karari).

    RED    : gozlem YAPILAMADI. Hicbir hesap yuklenemedi, ya da pozisyon var
             fakat HICBIRI fiyatlanamadi. Bu bir arizadir; adim da exit 1 verir
             ve P0.3 alarmi dogru sekilde ateslenir.
    YELLOW : gozlem YAPILDI ama EKSIK. Bazi pozisyon fiyatsiz ya da bazi hesap
             okunamadi. Ariza DEGIL -> exit 0, Telegram YOK; kapi yukselir.
    GREEN  : tum hesaplar yuklendi, tum pozisyonlar fiyatlandi.

    "Bilinmiyor" ile "guvenli" ayni sey degildir: eksik gozlem YESIL veremez.
    """
    if loaded_count == 0:
        return {"verdict": "RED", "reason": "no_account_state",
                "detail": "hicbir hesap state'i yuklenemedi"}
    if position_count and unpriced_count >= position_count:
        return {"verdict": "RED", "reason": "no_priced_position",
                "detail": "pozisyon var, hicbiri fiyatlanamadi"}
    if unpriced_count or unavailable_count:
        return {"verdict": "YELLOW", "reason": "partial_coverage",
                "detail": f"unpriced={unpriced_count} unavailable_account={unavailable_count}"}
    return {"verdict": "GREEN", "reason": "full_coverage",
            "detail": f"positions={position_count}"}


def build_payload(account_rows, price_sources, run_label=None, account_status=None,
                  cross_check=None):
    """Artefakt govdesi. `stop_eval.json`'dan AYRI dosyaya yazilir (karar 4).

    `cross_check` iki bagimsiz kaynagin ayni sembol icin verdigi fiyat ve bar
    gunudur. ARTEFAKTA yazilir, yalniz loga DEGIL: Actions logu 90 gunde silinir,
    bu dosya git'te kalir. Bir stop tartismali hale gelirse "o gun iki kaynak ne
    diyordu" sorusunun cevabi kalici olmali. Uyusmazlik ESIGI YOK (karar bilincli).
    """
    statuses = account_status or {
        acc: {"account": acc, "status": "loaded"}
        for acc in (account_rows or {})
    }
    unavailable = sum(1 for item in statuses.values() if item.get("status") != "loaded")
    toplam = sum(len(r or []) for r in (account_rows or {}).values())
    eksik = sum(
        1 for rows in (account_rows or {}).values()
        for row in rows or [] if row.get("status") != "priced"
    )
    # FIYATIN BAR GUNU — gozlemin kosma gunundan AYRI. Yalniz fiyatlanan
    # satirlardan toplanir; hukme cevrilmez, gorunur kilinir (bkz evaluate_stops).
    bar_gunleri = sorted({
        row.get("price_date")
        for rows in (account_rows or {}).values()
        for row in rows or []
        if row.get("status") == "priced" and row.get("price_date")
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_timestamp(),
        "tz": 0.0,
        "run_label": run_label or os.environ.get("STOP_OBS_LABEL") or None,
        "writer": "bist_alpha.stop_observer",
        "price_sources": price_sources,
        "cross_source_check": cross_check or {},
        "position_count": toplam,
        "unpriced_count": eksik,
        "price_asof": {
            "oldest": bar_gunleri[0] if bar_gunleri else None,
            "newest": bar_gunleri[-1] if bar_gunleri else None,
            "distinct": len(bar_gunleri),
        },
        "account_status": statuses,
        "unavailable_account_count": unavailable,
        "gate": gate_verdict(toplam, eksik, unavailable,
                             sum(1 for i in statuses.values() if i.get("status") == "loaded")),
        "breach": any_breach(account_rows),
        "accounts": {acc: rows for acc, rows in (account_rows or {}).items()},
        "note": (
            "P0.6/madde-7 bagimsiz stop gozlemi. YALNIZ TESPIT — emir/state "
            "mutasyonu YOK. stop_eval.json'dan AYRIDIR: o artefaktin bayatligi "
            "#0l'in kor-nokta sinyalidir, bu dosya her kosuda yazilir."
        ),
    }


def write_payload(payload, path=None):
    """Atomik yazim: tmp -> replace. Kismi dosya birakmaz."""
    out = Path(path or OBSERVER_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(out)
    return out
