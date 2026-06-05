"""
ÖZ-İYİLEŞTİRME (self-healing) — sistem hatalarını kendi kendine toparlama.

İlke: "sessizce mantık değiştirme" DEĞİL. Gerçek self-healing =
  - Geçici hataları yeniden dene (retry)
  - Birincil veri kaynağı çökerse yedeğe düş (Yahoo → gömülü Excel)
  - Bozuk state'i tespit et + onar/sıfırla
  - İstisnayı yakala, logla, bildir, ÇÖKME (daemon ayakta kalsın)
"""
import time
import os
import json
import traceback
from datetime import datetime


def with_retry(fn, retries=3, delay=5, label="işlem"):
    """Geçici hatalarda yeniden dener (network, veri çekme vb.)."""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[selfheal] {label} denemesi {i+1}/{retries} başarısız: {e}")
            if i < retries - 1:
                time.sleep(delay)
    raise last


def safe_feed():
    """
    Birincil veri kaynağını dene; çökerse gömülü Excel'e (FileFeed) düş.
    Yahoo/borsapy/API geçici çökerse sistem durmaz (rate-limit/ban/ToS koruması).
    """
    from . import datafeed, config
    source = getattr(config, "DATA_SOURCE", "file")
    if source == "file":
        return datafeed.FileFeed().get_latest()
    try:
        feed = datafeed.get_feed()
        data = with_retry(feed.get_latest, retries=3, delay=10,
                          label=f"{source} veri çekme")
        if data['prices'].shape[1] < 50 or data['prices'].empty:
            raise ValueError("Veri yetersiz/boş")
        return data
    except Exception as e:
        print(f"[selfheal] {source} çöktü ({e}) → gömülü Excel yedeğine düşülüyor")
        return datafeed.FileFeed().get_latest()


def validate_and_repair_state(account, state_dir="portfolios"):
    """
    Portföy JSON'unu doğrula. Bozuksa yedekle + sıfırla (veri kaybı önlenir).
    """
    path = os.path.join(state_dir, f"portfolio_{account}.json")
    if not os.path.exists(path):
        return True  # yok = temiz başlangıç
    try:
        with open(path) as f:
            state = json.load(f)
        # Zorunlu alanlar
        assert "account" in state and "cash" in state and "positions" in state
        assert isinstance(state["positions"], dict)
        for tic, pos in state["positions"].items():
            assert all(k in pos for k in ("entry", "peak", "shares"))
        return True
    except Exception as e:
        print(f"[selfheal] {account} portföyü bozuk ({e}) → yedeklenip sıfırlanıyor")
        bak = path + f".bozuk_{datetime.now():%Y%m%d_%H%M%S}.bak"
        try:
            os.rename(path, bak)
        except OSError:
            pass
        return False


def guarded(fn, notify_fn=None, label="döngü"):
    """
    Bir görevi koru: hata olursa yakala, logla, bildir, ÇÖKME.
    daemon görevlerini buna sarar — tek hata tüm servisi düşürmez.
    """
    try:
        return fn()
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[selfheal] {label} HATA (yakalandı, servis ayakta):\n{tb}")
        if notify_fn:
            try:
                notify_fn(f"⚠️ BIST Alpha — {label} hatası",
                          f"{e}\n\n{tb[:1500]}")
            except Exception:
                pass
        return None
