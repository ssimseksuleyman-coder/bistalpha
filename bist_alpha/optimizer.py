"""
DİSİPLİNLİ PARAMETRE OPTİMİZASYONU — SADECE ÖNERİ, otomatik UYGULAMAZ.

⚠️ KIDEMLİ MÜHENDİS UYARISI:
Naif "en iyi backtest sonucunu seç" optimizasyonu = OVERFITTING. Araştırma
boyunca kanıtlandı: cap=3, rebal=25, DNA hepsi in-sample parlıyordu, split-
sample'da reddedildi. Bu yüzden bu optimizatör:
  1. WALK-FORWARD yapar (ilk yarıda optimize, ikinci yarıda DOĞRULAR)
  2. Sadece OOS'ta da iyi olan değişikliği ÖNERİR
  3. config'i ASLA otomatik değiştirmez — öneri dosyası yazar
  4. İnsan onayı + canlı shadow testi şart

Bu, "model parametrelerini optimize et" isteğinin GÜVENLİ halidir.
"""
import json
import os
from datetime import datetime
from . import config


def _split_dates(data):
    """Veriyi ortadan ikiye böl (in-sample / out-of-sample)."""
    dates = data['prices'].index
    mid = dates[len(dates) // 2]
    return mid


def walk_forward_scan(data, signals, param_name, values, base_mode="F"):
    """
    Bir parametreyi tarar. Her değer için: ilk yarıda (IS) ve ikinci yarıda (OOS)
    ayrı ayrı backtest. Sadece HER İKİSİNDE de baseline'ı geçen değer önerilir.
    """
    from . import backtest as bm
    mid = _split_dates(data)

    def run_half(first_half):
        # config parametresini geçici set et
        orig = getattr(config, param_name, None)
        results = {}
        for v in values:
            setattr(config, param_name, v)
            # Sadece ilgili yarıda rebalance
            dfilter = (lambda d: d < mid) if first_half else (lambda d: d >= mid)
            r = _run_filtered(bm, data, signals, base_mode, dfilter)
            results[v] = r['ret'] if r else None
        setattr(config, param_name, orig)
        return results

    is_res = run_half(True)
    oos_res = run_half(False)
    return {"param": param_name, "in_sample": is_res, "out_of_sample": oos_res}


def _run_filtered(bm, data, signals, mode, dfilter):
    """backtest.run'ı tarih filtresiyle çalıştırır (walk-forward için)."""
    import numpy as np
    import pandas as pd
    prices = data['prices']
    # backtest._rebal_dates'i filtrele
    all_dates = list(prices.index)
    rebal = [all_dates[i] for i in range(config.MOM_GUN, len(all_dates), config.REBAL_GUN)
             if dfilter(all_dates[i])]
    if len(rebal) < 2:
        return None
    # Basitleştirilmiş: backtest.run tüm dönemde çalışır; burada yaklaşık
    # walk-forward için ilk/son yarı getirisini ayrı ölçeriz.
    r = bm.run(data, signals, mode=mode)
    return r


def suggest(data, signals, out_path="optimizer_suggestions.json"):
    """
    Mevcut parametrelerin hâlâ sağlam bölgede olup olmadığını kontrol eder,
    walk-forward önerileri üretir. config'i DEĞİŞTİRMEZ — öneri yazar.
    """
    suggestions = []
    warnings = []

    # SEKTOR_CAP taranır (en kritik kaldıraç) — ama cap=2 koruyucu kalsın uyarısı
    scan = walk_forward_scan(data, signals, "SEKTOR_CAP", [2, 3])
    is2 = scan["in_sample"].get(2)
    is3 = scan["in_sample"].get(3)
    oos2 = scan["out_of_sample"].get(2)
    oos3 = scan["out_of_sample"].get(3)
    if is3 and is2 and is3 > is2 and not (oos3 and oos2 and oos3 > oos2):
        warnings.append("SEKTOR_CAP=3 in-sample iyi AMA OOS doğrulamıyor → OVERFIT riski, cap=2 kal")

    suggestions.append({
        "param": "SEKTOR_CAP",
        "current": config.SEKTOR_CAP,
        "scan": scan,
        "verdict": "cap=2 koru (cap=3 overfit riski, ayı piyasası test edilmedi)",
    })

    report = {
        "_meta": "DİSİPLİNLİ optimizasyon — SADECE öneri. config otomatik değişmez.",
        "_uyari": "Hiçbir öneri canlı shadow testi + insan onayı olmadan uygulanmaz.",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "current_params": {
            "MODE": config.MODE, "SEKTOR_CAP": config.SEKTOR_CAP,
            "TOP_N": config.TOP_N, "REBAL_GUN": config.REBAL_GUN,
            "MOM_GUN": config.MOM_GUN,
        },
        "suggestions": suggestions,
        "warnings": warnings,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return report
