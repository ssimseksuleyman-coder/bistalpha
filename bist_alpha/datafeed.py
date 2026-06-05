"""
EKSİK #1 — Dinamik veri akışı (manuel değil, otomatik).

Adapter deseni: sistem veri kaynağından bağımsız çalışır.
- FileFeed     : yerel Excel/CSV (şu an çalışan varsayılan)
- APIFeed      : canlı BIST API (kullanıcı endpoint + key takar)
- ScraperFeed  : web kazıma (kullanıcı kendi scraper'ını takar)

Üniversite (hisse listesi) HER ÇAĞRIDA piyasa değerine göre dinamik seçilir —
sabit liste YOK. Yeni halka arzlar otomatik girer, küçülenler düşer.
"""
import pandas as pd
import os
import tempfile
from abc import ABC, abstractmethod
from . import config


class DataFeed(ABC):
    """Tüm veri kaynakları bu arayüzü uygular."""

    @abstractmethod
    def get_latest(self):
        """En güncel pivot tabloları döner (data.load_data formatında dict)."""
        ...

    def dynamic_universe(self, data, date=None, size=None):
        """
        Piyasa değerine göre DİNAMİK evren. Sabit liste değil.
        Her çağrıda en büyük N hisse otomatik seçilir.
        Nokta-zamanlı endeks üyeliği VARSA (survivorship düzeltmesi) önce kısıtlar.
        """
        size = size or config.UNIVERSE_SIZE
        mcaps = data['mcaps']
        if date is None:
            date = mcaps.index[-1]          # en güncel gün
        mc = mcaps.loc[date].dropna()
        # Survivorship: nokta-zamanlı üyelik varsa onunla sınırla
        try:
            from . import universe_history
            members = universe_history.index_members(date)
            if members:
                mc = mc[mc.index.isin(members)]
        except Exception:
            pass
        return set(mc.nlargest(size).index.tolist())


class FileFeed(DataFeed):
    """Yerel dosyadan okur (şu an çalışan varsayılan kaynak)."""

    def __init__(self, path=None):
        self.path = path or config.DATA_PATH

    def get_latest(self):
        from . import data as data_mod
        data = data_mod.load_data(path=self.path)
        data['_source'] = 'file'
        return data


class APIFeed(DataFeed):
    """
    Canlı BIST API adaptörü — KULLANICI DOLDURUR.
    Endpoint + API key config'e eklenir; aşağıdaki fetch() gerçek API'ye bağlanır.
    """

    def __init__(self, base_url=None, api_key=None):
        self.base_url = base_url or getattr(config, "BIST_API_URL", None)
        self.api_key = api_key or getattr(config, "BIST_API_KEY", None)

    def get_latest(self):
        if not self.base_url:
            raise NotImplementedError(
                "APIFeed: config.BIST_API_URL ve BIST_API_KEY tanımla. "
                "fetch() içinde kendi API'nin response'unu pivot formatına çevir."
            )
        # ---- KULLANICI BURAYI DOLDURUR ----
        # import requests
        # r = requests.get(f"{self.base_url}/prices",
        #                   headers={"Authorization": f"Bearer {self.api_key}"})
        # raw = r.json()
        # -> raw'ı data.load_data formatına (prices/mins/maxs/aofs/volumes/mcaps/bist) çevir
        raise NotImplementedError("APIFeed.fetch() kullanıcı tarafından doldurulacak")


class YahooFeed(DataFeed):
    """
    ÜCRETSİZ canlı BIST verisi — Yahoo Finance (yfinance). API KEY GEREKMEZ.
    BIST hisseleri .IS suffix ile (GARAN.IS). 7/24 cloud (GitHub Actions) için ideal.

    NOT: yfinance OHLCV verir; sistemin Min/Max/AOF eşlemesi:
      Min=Low, Max=High, AOF≈(H+L+C)/3 (tipik fiyat — VWAP yoksa yakınsama).
    Akıllı para sinyalleri bu yakınsamayla çalışır (birebir AOF değil).
    """

    def __init__(self, period="2y"):
        self.period = period

    def _configure_cache(self, yf):
        cache_dir = os.environ.get("YFINANCE_CACHE_DIR")
        if not cache_dir:
            cache_dir = os.path.join(tempfile.gettempdir(), "bistalpha_yfinance_cache")
        os.makedirs(cache_dir, exist_ok=True)
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(cache_dir)

    def get_latest(self):
        import yfinance as yf
        import pandas as pd
        import numpy as np
        from .universe import all_bist_tickers, universe_meta, yahoo_symbols

        self._configure_cache(yf)
        tickers = all_bist_tickers()
        symbols = yahoo_symbols(tickers)

        prices, mins, maxs, aofs, volumes = {}, {}, {}, {}, {}
        batch_size = int(os.environ.get("YAHOO_BATCH_SIZE", "80"))
        for start in range(0, len(symbols), batch_size):
            batch_symbols = symbols[start:start + batch_size]
            batch_tickers = tickers[start:start + batch_size]
            raw = yf.download(batch_symbols, period=self.period, interval="1d",
                              group_by="ticker", auto_adjust=False,
                              progress=False, threads=True)
            for sym, tic in zip(batch_symbols, batch_tickers):
                try:
                    sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                    if sub.empty or sub['Close'].dropna().empty:
                        continue
                    prices[tic] = sub['Close']
                    mins[tic] = sub['Low']
                    maxs[tic] = sub['High']
                    aofs[tic] = (sub['High'] + sub['Low'] + sub['Close']) / 3  # AOF yakınsama
                    volumes[tic] = sub['Volume']
                except (KeyError, TypeError):
                    continue

        prices = pd.DataFrame(prices).sort_index()
        if prices.empty:
            raise ValueError("YahooFeed bos veri dondurdu; semboller/rate-limit/cache sorunu olabilir")
        # XU100 endeksi (Yahoo: XU100.IS)
        try:
            bist_raw = yf.download("XU100.IS", period=self.period, interval="1d",
                                   auto_adjust=False, progress=False)
            bist = bist_raw['Close'].dropna()
            if hasattr(bist, 'columns'):
                bist = bist.iloc[:, 0]
        except Exception:
            bist = pd.Series(dtype=float)

        # Market cap: yfinance toplu vermez; PD_mn_TL yoksa fiyat*hacim proxy ile
        # evren seçimi yapılır (mcaps = son fiyat * ort hacim yaklaşımı)
        mcaps = pd.DataFrame(prices)  # placeholder; dynamic_universe fiyat*hacim kullanır

        return {
            'prices': prices,
            'mins': pd.DataFrame(mins).sort_index(),
            'maxs': pd.DataFrame(maxs).sort_index(),
            'aofs': pd.DataFrame(aofs).sort_index(),
            'volumes': pd.DataFrame(volumes).sort_index(),
            'mcaps': mcaps,
            'bist': bist,
            '_source': 'yahoo',
            '_source_pool_count': len(tickers),
            '_source_pool_method': universe_meta().get("method"),
            '_source_pool_fallback': universe_meta().get("fallback"),
        }

    def dynamic_universe(self, data, date=None, size=None):
        """Yahoo'da mcap yok — likidite (fiyat*hacim) proxy'siyle evren seç."""
        size = size or config.UNIVERSE_SIZE
        prices = data['prices']
        volumes = data['volumes']
        if prices.empty or volumes.empty:
            raise ValueError("YahooFeed evren secimi icin fiyat/hacim verisi yok")
        if date is None:
            date = prices.index[-1]
        idx = prices.index.searchsorted(date)
        # Son 20 gün ortalama TL devir = likidite proxy
        window = slice(max(0, idx - 20), idx + 1)
        turnover = (prices.iloc[window] * volumes.iloc[window]).mean()
        return set(turnover.nlargest(size).index.tolist())


class BorsaPyFeed(DataFeed):
    """
    TradingView destekli CANLI/15dk-gecikmeli BIST verisi — borsapy kütüphanesi.
    DATA_SOURCE="borsapy". yfinance'e göre BIST kapsamı daha iyi (yerli kaynak).

    NOT: Cron (kısa ömürlü çalışma) için borsapy.download() SNAPSHOT kullanılır.
    borsapy.TradingViewStream (WebSocket) kalıcı süreç içindir (VPS/systemd daemon),
    GitHub Actions'ın 2 dakikalık cron'u için uygun DEĞİL — snapshot doğru seçim.

    DÜRÜST UYARILAR:
      - Resmi olmayan kütüphane: TradingView arayüzü değişirse kırılabilir (kırılgan)
      - TradingView ToS'u programatik erişimi kısıtlayabilir (hukuki/ToS riski)
      - GitHub paylaşımlı IP'de yine rate-limit/ban riski (safe_feed yedeğe düşer)
      - Bazı özellikler TradingView auth ister (config.TV_USERNAME/TV_PASSWORD)
      - Gecikmeli veri varsayılan; canlı için TradingView aboneliği gerekebilir
    """

    def __init__(self, period="2y"):
        self.period = period

    def get_latest(self):
        import borsapy
        import pandas as pd
        from .universe import all_bist_tickers, universe_meta
        tickers = all_bist_tickers()

        # Opsiyonel TradingView auth (config/ENV'den)
        tv_user = getattr(config, "TV_USERNAME", None)
        tv_pass = getattr(config, "TV_PASSWORD", None)
        if tv_user and tv_pass:
            try:
                borsapy.set_tradingview_auth(tv_user, tv_pass)
            except Exception:
                pass

        # Toplu snapshot indir (cron-dostu, WebSocket değil)
        raw = borsapy.download(tickers, period=self.period, interval="1d")

        prices, mins, maxs, aofs, volumes = {}, {}, {}, {}, {}
        for tic in tickers:
            try:
                # borsapy.download çoklu hisse için MultiIndex kolon döndürür
                if isinstance(raw.columns, pd.MultiIndex):
                    sub = raw[tic]
                else:
                    sub = raw  # tek hisse
                cols = {c.lower(): c for c in sub.columns}
                close = sub[cols.get('close', 'Close')]
                if close.dropna().empty:
                    continue
                prices[tic] = close
                mins[tic] = sub[cols.get('low', 'Low')]
                maxs[tic] = sub[cols.get('high', 'High')]
                aofs[tic] = (sub[cols.get('high', 'High')] + sub[cols.get('low', 'Low')] + close) / 3
                volumes[tic] = sub[cols.get('volume', 'Volume')]
            except (KeyError, TypeError):
                continue

        prices = pd.DataFrame(prices).sort_index()
        # XU100 endeksi
        try:
            idx_raw = borsapy.index("XU100", period=self.period, interval="1d") \
                if hasattr(borsapy, "index") else None
            bist = idx_raw['close'] if idx_raw is not None and 'close' in idx_raw else pd.Series(dtype=float)
        except Exception:
            bist = pd.Series(dtype=float)

        return {
            'prices': prices,
            'mins': pd.DataFrame(mins).sort_index(),
            'maxs': pd.DataFrame(maxs).sort_index(),
            'aofs': pd.DataFrame(aofs).sort_index(),
            'volumes': pd.DataFrame(volumes).sort_index(),
            'mcaps': pd.DataFrame(prices),  # mcap yok → universe sıralama proxy (birim-bağımsız)
            'bist': bist,
            '_source': 'borsapy',
            '_source_pool_count': len(tickers),
            '_source_pool_method': universe_meta().get("method"),
            '_source_pool_fallback': universe_meta().get("fallback"),
        }

    def dynamic_universe(self, data, date=None, size=None):
        """mcap yok → likidite (fiyat×hacim) sıralaması (sıralama birim-bağımsız)."""
        size = size or config.UNIVERSE_SIZE
        prices = data['prices']
        volumes = data['volumes']
        if prices.empty or volumes.empty:
            raise ValueError("YahooFeed evren secimi icin fiyat/hacim verisi yok")
        if date is None:
            date = prices.index[-1]
        idx = prices.index.searchsorted(date)
        window = slice(max(0, idx - 20), idx + 1)
        turnover = (prices.iloc[window] * volumes.iloc[window]).mean()
        return set(turnover.nlargest(size).index.tolist())


def get_feed():
    """config.DATA_SOURCE'a göre uygun feed'i döner."""
    source = getattr(config, "DATA_SOURCE", "file")
    if source == "api":
        return APIFeed()
    if source == "yahoo":
        return YahooFeed()
    if source == "borsapy":
        return BorsaPyFeed()
    return FileFeed()

