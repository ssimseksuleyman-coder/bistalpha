"""
Walk-forward validasyon — overfitting tespiti.

Her fold: TRAIN gunluk in-sample, TEST gunluk out-of-sample.
Train Sharpe >> Test Sharpe -> overfitting sinyali.

Kullanim:
    from bist_alpha.validate import walk_forward
    results = walk_forward(data, mode="F")
"""
import numpy as np
import pandas as pd
from . import config
from . import signals as sig_mod
from . import backtest as bt_mod


def walk_forward(data, mode="F", train_days=252, test_days=63, slippage=0.0, verbose=True):
    """
    Expanding-window walk-forward test.

    Her fold icin:
      - Train: [0 .. train_end] uzerinde backtest
      - Test:  [train_end .. train_end+test_days] uzerinde backtest
      - Ayni sinyaller (tam veri uzerinden hesaplanir — gercekci)
      - Degradasyon = (train_sharpe - test_sharpe) / train_sharpe

    Returns: list of fold dicts + summary dict
    """
    prices = data['prices']
    n = len(prices)

    if n < train_days + test_days:
        return {"error": f"Yetersiz veri: {n} gun < {train_days + test_days} gerekli"}

    # Sinyaller tam veri uzerinden — gercek kullanim bunu yapar
    signals = sig_mod.compute_signals(data)

    folds = []
    fold_idx = 0
    train_end = train_days

    while train_end + test_days <= n:
        # Alt-veri kesimi
        train_data = _slice_data(data, 0, train_end)
        test_data  = _slice_data(data, train_end - config.MOM_GUN, train_end + test_days)

        train_sig = sig_mod.compute_signals(train_data)
        test_sig  = sig_mod.compute_signals(test_data)

        r_train = bt_mod.run(train_data, train_sig, mode=mode, slippage=slippage)
        r_test  = bt_mod.run(test_data,  test_sig,  mode=mode, slippage=slippage)

        if r_train is None or r_test is None:
            train_end += test_days
            continue

        degrade_sharpe = ((r_train['sharpe'] - r_test['sharpe']) / r_train['sharpe'] * 100
                          if r_train['sharpe'] != 0 else None)
        degrade_ret    = ((r_train['ret'] - r_test['ret']) / abs(r_train['ret']) * 100
                          if r_train['ret'] != 0 else None)

        fold = {
            "fold": fold_idx + 1,
            "train_start": str(prices.index[0].date()),
            "train_end":   str(prices.index[train_end - 1].date()),
            "test_start":  str(prices.index[train_end].date()),
            "test_end":    str(prices.index[min(train_end + test_days - 1, n - 1)].date()),
            "train_days":  train_end,
            "test_days":   test_days,
            # Train metrikleri
            "train_ret":    r_train['ret'],
            "train_dd":     r_train['dd'],
            "train_sharpe": r_train['sharpe'],
            "train_calmar": r_train['calmar'],
            # Test metrikleri
            "test_ret":    r_test['ret'],
            "test_dd":     r_test['dd'],
            "test_sharpe": r_test['sharpe'],
            "test_calmar": r_test['calmar'],
            # Degradasyon
            "degrade_sharpe_pct": round(degrade_sharpe, 1) if degrade_sharpe is not None else None,
            "degrade_ret_pct":    round(degrade_ret,    1) if degrade_ret    is not None else None,
        }
        folds.append(fold)

        if verbose:
            dg = f"{degrade_sharpe:.0f}%" if degrade_sharpe is not None else "N/A"
            print(f"  Fold {fold_idx+1}: train Sharpe={r_train['sharpe']:.2f} "
                  f"| test Sharpe={r_test['sharpe']:.2f} | degrade={dg}")

        fold_idx += 1
        train_end += test_days

    if not folds:
        return {"error": "Hic fold olusturulamadi", "folds": []}

    # Ozet
    avg_train_sharpe = np.mean([f['train_sharpe'] for f in folds])
    avg_test_sharpe  = np.mean([f['test_sharpe']  for f in folds])
    avg_degrade      = np.mean([f['degrade_sharpe_pct'] for f in folds
                                if f['degrade_sharpe_pct'] is not None])
    avg_train_ret = np.mean([f['train_ret'] for f in folds])
    avg_test_ret  = np.mean([f['test_ret']  for f in folds])

    verdict = _verdict(avg_degrade, avg_train_sharpe, avg_test_sharpe)

    summary = {
        "n_folds":           len(folds),
        "train_days":        train_days,
        "test_days":         test_days,
        "avg_train_sharpe":  round(float(avg_train_sharpe), 2),
        "avg_test_sharpe":   round(float(avg_test_sharpe),  2),
        "avg_train_ret":     round(float(avg_train_ret),    2),
        "avg_test_ret":      round(float(avg_test_ret),     2),
        "avg_degrade_pct":   round(float(avg_degrade),      1),
        "verdict":           verdict,
        "interpretation":    _interpret(verdict),
    }

    return {"summary": summary, "folds": folds}


def _verdict(degrade_pct, train_sharpe, test_sharpe):
    """Overfitting derecesi."""
    if test_sharpe <= 0:
        return "OVERFITTING_AGIR"
    if degrade_pct > 70:
        return "OVERFITTING_YUKSEK"
    if degrade_pct > 40:
        return "OVERFITTING_ORTA"
    if degrade_pct > 15:
        return "OVERFITTING_DUSUK"
    return "SAGLIKLI"


def _interpret(verdict):
    msgs = {
        "SAGLIKLI":          "Strateji out-of-sample'da guclu. Canli uygulamaya yakin.",
        "OVERFITTING_DUSUK": "Hafif degradasyon — beklenen. Canli performans %15 daha dusuk olabilir.",
        "OVERFITTING_ORTA":  "Dikkat: belirgin degradasyon. Canli performans %40 daha dusuk olabilir.",
        "OVERFITTING_YUKSEK":"UYARI: Ciddi overfitting. Canli sistem bu getiriyi uretmeyebilir.",
        "OVERFITTING_AGIR":  "KRITIK: Strateji out-of-sample'da negatif Sharpe. Kullanma!",
    }
    return msgs.get(verdict, "")


def _slice_data(data, start, end):
    """Veri dict'ini [start:end] index araligina keser."""
    sliced = {}
    for k, v in data.items():
        if isinstance(v, (pd.DataFrame, pd.Series)):
            sliced[k] = v.iloc[start:end]
        else:
            sliced[k] = v
    return sliced
