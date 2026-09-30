"""
📡 Datos en vivo con el MISMO formato que data.load_full(), para el bot horario.

Usa las APIs públicas de Binance (las mismas series que el histórico) para las últimas
~1000 horas, que bastan para calcular todas las features de features_h.py.
"""

import time

import pandas as pd
import requests

from data import _daily_shifted, fear_greed, wiki_views

FAPI = "https://fapi.binance.com"
HOURS = 1000


def _get(path: str, **params):
    for attempt in range(3):
        try:
            r = requests.get(FAPI + path, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def _klines(symbol: str) -> pd.DataFrame:
    rows = _get("/fapi/v1/klines", symbol=symbol, interval="1h", limit=HOURS)
    df = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                                     'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'])
    df.index = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df = df[df.index + pd.Timedelta(hours=1) <= pd.Timestamp.now(tz='UTC')]  # solo velas cerradas
    return df[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume', 'count']].astype(float)


def _funding(symbol: str) -> pd.Series:
    rows = _get("/fapi/v1/fundingRate", symbol=symbol, limit=1000)
    s = pd.Series([float(r['fundingRate']) for r in rows],
                  index=pd.to_datetime([r['fundingTime'] for r in rows], unit='ms', utc=True).floor('h'))
    return s[~s.index.duplicated(keep='last')].sort_index()


def _metrics(symbol: str) -> pd.DataFrame:
    """Fotos horarias (en punto) de OI y ratios; como en el histórico, la foto de H va a la vela que cierra en H."""
    series = {
        'oi': ("/futures/data/openInterestHist", 'sumOpenInterest'),
        'top_ls_accounts': ("/futures/data/topLongShortAccountRatio", 'longShortRatio'),
        'top_ls_positions': ("/futures/data/topLongShortPositionRatio", 'longShortRatio'),
        'global_ls_accounts': ("/futures/data/globalLongShortAccountRatio", 'longShortRatio'),
    }
    out = {}
    for name, (path, field) in series.items():
        rows = _get(path, symbol=symbol, period="1h", limit=500)
        s = pd.Series([float(r[field]) for r in rows],
                      index=pd.to_datetime([int(r['timestamp']) for r in rows], unit='ms', utc=True))
        s.index = s.index - pd.Timedelta(hours=1)
        out[name] = s[~s.index.duplicated(keep='last')]
    return pd.DataFrame(out)


def load_live(symbol: str = "SOLUSDT") -> pd.DataFrame:
    df = _klines(symbol)
    funding = _funding(symbol)
    paid = funding.copy()
    paid.index = paid.index - pd.Timedelta(hours=1)
    df['funding'] = paid.reindex(df.index).fillna(0.0)
    df['funding_last'] = funding.reindex(df.index, method='ffill')

    for sym, tag in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
        k = _klines(sym)
        df[f'{tag}_close'] = k['close'].reindex(df.index)
        df[f'{tag}_volume'] = k['volume'].reindex(df.index)

    df = df.join(_metrics(symbol), how='left')
    start = (df.index[0] - pd.Timedelta(days=40)).strftime('%Y-%m')
    daily = pd.concat([fear_greed(), wiki_views(start=start)], axis=1)
    daily = daily.reindex(daily.index.union(df.index)).ffill().reindex(df.index)
    return df.join(daily)
