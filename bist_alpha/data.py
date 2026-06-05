"""
Veri yükleme modülü.
Excel'i okur, doğru kolon eşlemesiyle pivot tablolar üretir.
"""
import pandas as pd
import numpy as np
from . import config

COLUMNS = ['Ticker', 'Tarih', 'Kapanis', 'Min', 'Max', 'AOF', 'Hacim',
           'Sermaye', 'USDTRY', 'BIST100', 'PD_mn_TL', 'PD_mn_USD',
           'HalkaA_TL', 'HalkaA_USD']


def load_data(path=None, sheet=None):
    """
    Excel'i yükler ve pivot tabloları döner.

    Returns: dict with keys:
        prices, mins, maxs, aofs, volumes, mcaps (gün x hisse DataFrame)
        bist (gün -> BIST100 Series)
    """
    path = path or config.DATA_PATH
    sheet = sheet or config.SHEET_NAME

    df = pd.read_excel(path, sheet_name=sheet, header=0, engine="openpyxl")
    df = df.iloc[2:].copy()                # ilk 2 satır başlık/boşluk
    df.columns = COLUMNS
    df['Tarih'] = pd.to_datetime(df['Tarih'], errors='coerce')
    for c in ['Kapanis', 'Min', 'Max', 'AOF', 'Hacim', 'PD_mn_TL', 'USDTRY', 'BIST100']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['Ticker'] = df['Ticker'].ffill()
    df = df.dropna(subset=['Tarih', 'Kapanis', 'Ticker'])

    def pv(col):
        return df.pivot_table(index='Tarih', columns='Ticker', values=col,
                              aggfunc='last').sort_index()

    return {
        'prices': pv('Kapanis'),
        'mins': pv('Min'),
        'maxs': pv('Max'),
        'aofs': pv('AOF'),
        'volumes': pv('Hacim'),
        'mcaps': pv('PD_mn_TL'),
        'bist': df.groupby('Tarih')['BIST100'].first().sort_index().dropna(),
    }
