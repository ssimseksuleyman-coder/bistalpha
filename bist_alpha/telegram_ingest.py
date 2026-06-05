"""
TELEGRAM İLE MANUEL VERİ YÜKLEME — inbound dosya alımı.

Telegram bot'una gönderilen dosyaları (CSV/Excel) indirir ve doğru klasöre koyar:
  - *Teknik_Takip*.xlsx        -> deniz_inbox/   (Deniz bülteni)
  - *endeks_katilim*.csv       -> data/          (survivorship üyeliği)
  - Tarihsel*.xlsx / *fiyat*   -> data/          (fiyat verisi güncelleme)
  - diğer                      -> data/uploads/  (genel)

Cron-dostu: her çalışmada getUpdates ile yeni belgeleri çeker (webhook gerekmez).
config (ENV): TELEGRAM_TOKEN (mevcut bildirim token'ı ile aynı), TELEGRAM_CHAT_ID
Son işlenen update offset'i data/.tg_offset ile saklanır (tekrar indirmez).
"""
import os
import requests
from . import config

_OFFSET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", ".tg_offset")
_DATA = os.path.join(os.path.dirname(__file__), "..", "data")
_DENIZ = os.path.join(os.path.dirname(__file__), "..", "deniz_inbox")


def _route(filename):
    """Dosya adına göre hedef klasör + yeni ad."""
    fn = filename.lower()
    if "teknik_takip" in fn or ("teknik" in fn and fn.endswith(".xlsx")):
        return _DENIZ, filename
    if "endeks_katilim" in fn or "katilim" in fn:
        return _DATA, "hisse_endeks_katilim_ds.csv"
    if ("tarihsel" in fn or "fiyat" in fn) and fn.endswith((".xlsx", ".xls")):
        return _DATA, "Tarihsel_Fiyat_Bilgileri.xlsx"
    up = os.path.join(_DATA, "uploads")
    return up, filename


def _read_offset():
    try:
        return int(open(_OFFSET_FILE).read().strip())
    except Exception:
        return 0


def _write_offset(o):
    try:
        os.makedirs(os.path.dirname(_OFFSET_FILE), exist_ok=True)
        open(_OFFSET_FILE, "w").write(str(o))
    except OSError:
        pass


def fetch_uploads():
    """
    Telegram'a gönderilen yeni belgeleri indir + doğru klasöre yerleştir.
    Returns: indirilen dosyaların listesi.
    """
    token = getattr(config, "TELEGRAM_TOKEN", None)
    if not token:
        return []
    base = f"https://api.telegram.org/bot{token}"
    file_base = f"https://api.telegram.org/file/bot{token}"
    offset = _read_offset()
    saved = []
    try:
        r = requests.get(f"{base}/getUpdates",
                         params={"offset": offset + 1, "timeout": 0}, timeout=30)
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"[telegram_ingest] getUpdates hatası: {e}")
        return []

    allowed_chat = str(getattr(config, "TELEGRAM_CHAT_ID", "") or "")
    for upd in updates:
        offset = max(offset, upd["update_id"])
        msg = upd.get("message") or upd.get("channel_post") or {}
        doc = msg.get("document")
        if not doc:
            continue
        # Güvenlik: sadece izinli chat'ten
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if allowed_chat and chat_id != allowed_chat:
            continue
        filename = doc.get("file_name", f"upload_{doc['file_id'][:8]}")
        try:
            fr = requests.get(f"{base}/getFile",
                              params={"file_id": doc["file_id"]}, timeout=30)
            file_path = fr.json()["result"]["file_path"]
            content = requests.get(f"{file_base}/{file_path}", timeout=60).content
            folder, newname = _route(filename)
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, newname)
            with open(dest, "wb") as f:
                f.write(content)
            saved.append(dest)
            print(f"[telegram_ingest] indirildi: {filename} -> {dest}")
            # Onay mesajı
            _notify(base, chat_id, f"✅ Alındı: {newname}")
        except Exception as e:
            print(f"[telegram_ingest] {filename} indirilemedi: {e}")

    _write_offset(offset)
    return saved


def _notify(base, chat_id, text):
    try:
        requests.post(f"{base}/sendMessage",
                      data={"chat_id": chat_id, "text": text}, timeout=15)
    except Exception:
        pass
