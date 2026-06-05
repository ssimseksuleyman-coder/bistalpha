"""
EKSİK #6 — Otomatik bakım (self-maintenance).

Görevler:
  - Veri bütünlüğü kontrolü (eksik gün, NaN patlaması, donmuş fiyat)
  - Snapshot rotasyonu (eski Deniz/rapor snapshot'larını temizle)
  - Sağlık kontrolü (son veri tarihi güncel mi?)
  - Log rotasyonu
daemon tarafından günlük çağrılır; sorun varsa bildirim üretir.
"""
import os
import glob
import json
from datetime import datetime, timedelta
import pandas as pd
from . import config


def check_data_health(data, max_staleness_days=4):
    """Veri güncel ve tutarlı mı? Sorun listesi döner (boşsa sağlıklı)."""
    issues = []
    prices = data['prices']

    # 1) Son veri tarihi güncel mi?
    last_date = prices.index[-1]
    age = (datetime.now() - last_date.to_pydatetime()).days
    if age > max_staleness_days:
        issues.append(f"Veri eski: son tarih {last_date.date()} ({age} gün önce)")

    # 2) Son günde NaN patlaması var mı?
    last_row = prices.iloc[-1]
    nan_pct = last_row.isna().mean() * 100
    if nan_pct > 50:
        issues.append(f"Son günde %{nan_pct:.0f} hisse NaN — veri eksik olabilir")

    # 3) Donmuş fiyat (son 5 gün hiç değişmemiş hisseler)
    if len(prices) >= 5:
        recent = prices.iloc[-5:]
        frozen = (recent.nunique() == 1).sum()
        if frozen > len(prices.columns) * 0.3:
            issues.append(f"{frozen} hisse son 5 gün donmuş (tatil/durdurma?)")

    return issues


def rotate_snapshots(snapshot_dir, keep_days=90):
    """keep_days'ten eski snapshot'ları siler."""
    if not os.path.isdir(snapshot_dir):
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for f in glob.glob(os.path.join(snapshot_dir, "*.json")):
        if datetime.fromtimestamp(os.path.getmtime(f)) < cutoff:
            os.remove(f)
            removed += 1
    return removed


def rotate_logs(log_dir="logs", keep_days=30):
    """Eski logları temizler."""
    return rotate_snapshots(log_dir, keep_days)


def clean_temp(root="."):
    """
    Eski/geçici dosyaları temizle: __pycache__, *.pyc, *.tmp, bozuk state yedekleri.
    Disk şişmesini önler.
    """
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # __pycache__ klasörleri
        if "__pycache__" in dirnames:
            import shutil
            try:
                shutil.rmtree(os.path.join(dirpath, "__pycache__"))
                removed += 1
            except OSError:
                pass
            dirnames.remove("__pycache__")
        for fn in filenames:
            if fn.endswith((".pyc", ".tmp", ".bozuk")) or ".bozuk_" in fn:
                try:
                    os.remove(os.path.join(dirpath, fn))
                    removed += 1
                except OSError:
                    pass
    return removed


def run_maintenance(data, snapshot_dir="deniz_snapshots", log_dir="logs"):
    """
    Tam bakım döngüsü. daemon günlük çağırır.
    Returns: dict (sağlık raporu).
    """
    issues = check_data_health(data)
    n_snap = rotate_snapshots(snapshot_dir)
    n_log = rotate_logs(log_dir)
    n_temp = clean_temp()
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_issues": issues,
        "healthy": len(issues) == 0,
        "snapshots_removed": n_snap,
        "logs_removed": n_log,
        "temp_removed": n_temp,
    }
    status = "✅ sağlıklı" if report["healthy"] else f"⚠️ {len(issues)} sorun"
    print(f"[maintenance] {status} | snapshot:{n_snap} log:{n_log} temp:{n_temp}")
    return report
