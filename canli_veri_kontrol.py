#!/usr/bin/env python3
import os
import sys
from datetime import datetime

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["DATA_SOURCE"] = os.environ.get("DATA_SOURCE", "yahoo")

from bist_alpha import datafeed


def main():
    feed = datafeed.get_feed()
    print(f"DATA_SOURCE={os.environ.get('DATA_SOURCE')} -> {type(feed).__name__}")
    data = feed.get_latest()
    prices = data["prices"]
    bist = data.get("bist")
    if prices.empty:
        print("HATA: Canli fiyat verisi bos geldi.")
        return 1
    universe = feed.dynamic_universe(data)
    last_date = prices.index[-1]
    print(f"Hisse verisi: {prices.shape[1]} hisse x {prices.shape[0]} gun")
    print(f"Son veri tarihi: {last_date}")
    print(f"XU100 satir sayisi: {len(bist) if bist is not None else 0}")
    print(f"Dinamik evren: {len(universe)} hisse")
    stale_days = (datetime.now().date() - last_date.date()).days if hasattr(last_date, "date") else None
    if stale_days is not None:
        print(f"Veri gecikmesi: {stale_days} gun")
        if stale_days > 7:
            print("UYARI: Veri 7 gunden eski gorunuyor; Yahoo kaynak/market tatili kontrol edilmeli.")
    print("OK: Canli veri alimi calisiyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
