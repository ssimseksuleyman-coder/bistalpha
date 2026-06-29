"""
EKSİK #3 — Otomatik zamanlı raporlama (09:45, 14:30, 18:30).

İki kullanım:
  1. Dahili döngü: python daemon.py (sürekli çalışır, saatleri bekler)
  2. Sistem cron'u (önerilen — daha sağlam):
       45 9  * * 1-5  cd /yol && python daemon.py --once acilis
       30 14 * * 1-5  cd /yol && python daemon.py --once gunici
       30 18 * * 1-5  cd /yol && python daemon.py --once kapanis
"""
import time
from datetime import datetime

# Varsayılan raporlama saatleri (HH, MM, etiket)
SCHEDULE = [
    (9, 45, "acilis"),    # açılış sonrası ilk sinyal
    (14, 30, "gunici"),   # gün içi güncelleme
    (18, 40, "kapanis"),  # kapanis raporu + ertesi gun hazirlik
]


def is_weekday():
    return datetime.now().weekday() < 5  # 0-4 = Pzt-Cuma


def run_loop(task_fn, poll_seconds=30):
    """
    Sürekli döngü — planlanan saatlerde task_fn(label) çağırır.
    task_fn: def task(label) -> None
    Aynı dakikada iki kez tetiklenmeyi önler.
    """
    print(f"[scheduler] Başladı. Saatler: {[f'{h:02d}:{m:02d}' for h,m,_ in SCHEDULE]}")
    last_fired = None
    while True:
        now = datetime.now()
        if is_weekday():
            for h, m, label in SCHEDULE:
                key = (now.date(), label)
                if now.hour == h and now.minute == m and last_fired != key:
                    print(f"[scheduler] {now:%H:%M} -> görev '{label}'")
                    try:
                        task_fn(label)
                    except Exception as e:
                        print(f"[scheduler] Görev hatası ({label}): {e}")
                    last_fired = key
        time.sleep(poll_seconds)
