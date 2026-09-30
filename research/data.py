"""
📥 Datos históricos para el laboratorio (velas de 1 h + funding de perpetuos).

Fuentes:
- Binance USDⓈ-M futures (data.binance.vision): años de SOLUSDT, con volumen comprador.
- Hyperliquid (API info): ~7 meses de velas de 1 h y funding horario del mercado donde opera el bot.

Todo se cachea en research/data/ (los meses completos solo se descargan una vez).
"""

import io
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
BINANCE = "https://data.binance.vision/data/futures/um"
HL_INFO = "https://api.hyperliquid.xyz/info"

KLINE_COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
              'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']


def _to_utc(ms: pd.Series) -> pd.Series:
    ms = pd.to_numeric(ms)
    unit = 'us' if ms.iloc[0] > 1e14 else 'ms'  # Binance usa microsegundos en algunos archivos nuevos
    return pd.to_datetime(ms, unit=unit, utc=True)


def _cached(path: Path, fetch, permanent: bool) -> pd.DataFrame | None:
    """Leer de caché o descargar. Los archivos no permanentes (mes en curso) se refrescan cada 6 h."""
    if path.exists() and (permanent or time.time() - path.stat().st_mtime < 6 * 3600):
        return pd.read_csv(path)
    df = fetch()
    if df is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return df


def _zip_csv(url: str, columns: list) -> pd.DataFrame | None:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read(z.namelist()[0]).decode()
    has_header = not raw[:1].isdigit()
    return pd.read_csv(io.StringIO(raw), header=0 if has_header else None, names=columns)


def _months(start: str):
    """Meses completos desde start (YYYY-MM) hasta el mes pasado."""
    cur = datetime.strptime(start, "%Y-%m").replace(tzinfo=timezone.utc)
    this_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur < this_month:
        yield cur.strftime("%Y-%m")
        cur = (cur + timedelta(days=32)).replace(day=1)


def binance_klines(symbol: str = "SOLUSDT", start: str = "2023-01") -> pd.DataFrame:
    parts = []
    for m in _months(start):
        url = f"{BINANCE}/monthly/klines/{symbol}/1h/{symbol}-1h-{m}.zip"
        df = _cached(DATA_DIR / "binance" / f"{symbol}-1h-{m}.csv.gz",
                     lambda: _zip_csv(url, KLINE_COLS), permanent=True)
        if df is not None:
            parts.append(df)

    # Mes en curso: archivos diarios hasta ayer
    today = datetime.now(timezone.utc).date()
    for d in pd.date_range(today.replace(day=1), today - timedelta(days=1)):
        day = d.strftime("%Y-%m-%d")
        url = f"{BINANCE}/daily/klines/{symbol}/1h/{symbol}-1h-{day}.zip"
        df = _cached(DATA_DIR / "binance" / f"{symbol}-1h-{day}.csv.gz",
                     lambda: _zip_csv(url, KLINE_COLS), permanent=True)
        if df is not None:
            parts.append(df)

    df = pd.concat(parts, ignore_index=True)
    df['time'] = _to_utc(df['open_time'])
    df = df.drop_duplicates('time').set_index('time').sort_index()
    cols = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume', 'count']
    return df[cols].astype(float)


def binance_funding(symbol: str = "SOLUSDT", start: str = "2023-01") -> pd.Series:
    parts = []
    for m in _months(start):
        url = f"{BINANCE}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip"
        df = _cached(DATA_DIR / "binance" / f"{symbol}-funding-{m}.csv.gz",
                     lambda: _zip_csv(url, ['calc_time', 'funding_interval_hours', 'last_funding_rate']),
                     permanent=True)
        if df is not None:
            parts.append(pd.DataFrame({'time': df['calc_time'], 'rate': df['last_funding_rate']}))

    # Mes en curso desde la API pública
    def fetch_current():
        start_ms = int(datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).timestamp() * 1000)
        rows = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                            params={'symbol': symbol, 'startTime': start_ms, 'limit': 1000}, timeout=30).json()
        return pd.DataFrame({'time': [r['fundingTime'] for r in rows], 'rate': [r['fundingRate'] for r in rows]})
    parts.append(_cached(DATA_DIR / "binance" / f"{symbol}-funding-current.csv.gz", fetch_current, permanent=False))

    df = pd.concat(parts, ignore_index=True)
    df['time'] = _to_utc(df['time']).dt.floor('h')
    return df.drop_duplicates('time').set_index('time')['rate'].astype(float).sort_index()


def hyperliquid_klines(coin: str = "SOL") -> pd.DataFrame:
    """Últimas 5000 velas de 1 h (~7 meses)."""
    def fetch():
        end = int(time.time() * 1000)
        rows = requests.post(HL_INFO, json={"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "1h", "startTime": end - 5000 * 3600_000, "endTime": end}}, timeout=30).json()
        return pd.DataFrame({'time': [r['t'] for r in rows], 'open': [r['o'] for r in rows],
                             'high': [r['h'] for r in rows], 'low': [r['l'] for r in rows],
                             'close': [r['c'] for r in rows], 'volume': [r['v'] for r in rows],
                             'count': [r['n'] for r in rows]})
    df = _cached(DATA_DIR / "hyperliquid" / f"{coin}-1h.csv.gz", fetch, permanent=False)
    df['time'] = _to_utc(df['time'])
    return df.set_index('time').sort_index().astype(float)


def hyperliquid_funding(coin: str = "SOL", days: int = 220) -> pd.Series:
    def fetch():
        start = int((time.time() - days * 86400) * 1000)
        out = []
        while True:
            rows = requests.post(HL_INFO, json={"type": "fundingHistory", "coin": coin, "startTime": start},
                                 timeout=30).json()
            if not rows:
                break
            out += rows
            start = rows[-1]['time'] + 1
            if len(rows) < 500:
                break
        return pd.DataFrame({'time': [r['time'] for r in out], 'rate': [r['fundingRate'] for r in out]})
    df = _cached(DATA_DIR / "hyperliquid" / f"{coin}-funding.csv.gz", fetch, permanent=False)
    df['time'] = _to_utc(df['time']).dt.floor('h')
    return df.drop_duplicates('time').set_index('time')['rate'].astype(float).sort_index()


def load_dataset(source: str = "binance", start: str = "2023-01") -> pd.DataFrame:
    """
    Velas de 1 h con dos columnas de funding:
      funding      → tasa cobrada al cerrar esa vela (0 si no hay pago); la paga quien esté largo si es > 0
      funding_last → última tasa conocida (feature, sin mirar al futuro)
    """
    if source == "binance":
        df, funding = binance_klines(start=start), binance_funding(start=start)
    elif source == "hyperliquid":
        df, funding = hyperliquid_klines(), hyperliquid_funding()
    else:
        raise ValueError("source debe ser 'binance' o 'hyperliquid'")

    # Un pago a la hora T lo paga la posición abierta durante la vela que termina en T
    paid = funding.copy()
    paid.index = paid.index - pd.Timedelta(hours=1)
    df['funding'] = paid.reindex(df.index).fillna(0.0)
    df['funding_last'] = funding.reindex(df.index, method='ffill')
    df = df[df.index + pd.Timedelta(hours=1) <= pd.Timestamp.now(tz='UTC')]  # sin la vela en curso
    return df.dropna(subset=['close'])


# =============================================================================
# Datos adicionales: otros activos, posicionamiento, sentimiento y noticias
# =============================================================================

from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'sol-research-bot/1.0 (personal research)'}
METRIC_COLS = ['create_time', 'symbol', 'sum_open_interest', 'sum_open_interest_value',
               'count_toptrader_long_short_ratio', 'sum_toptrader_long_short_ratio',
               'count_long_short_ratio', 'sum_taker_long_short_vol_ratio']


def binance_metrics(symbol: str = "SOLUSDT", start: str = "2023-01") -> pd.DataFrame:
    """
    Posicionamiento de futuros (cada 5 min en origen): open interest y ratios largo/corto.
    Se toma la foto exacta de cada hora en punto H y se asigna a la vela que CIERRA en H
    (vela con open_time H-1h), igual que hará el bot en vivo con la API de 1 h.
    """
    days = pd.date_range(f"{start}-01", datetime.now(timezone.utc).date() - timedelta(days=1), freq='D')

    def one(d):
        day = d.strftime("%Y-%m-%d")
        url = f"{BINANCE}/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip"
        return _cached(DATA_DIR / "binance_metrics" / f"{symbol}-{day}.csv.gz",
                       lambda: _zip_csv(url, METRIC_COLS), permanent=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        parts = [p for p in pool.map(one, days) if p is not None]
    df = pd.concat(parts, ignore_index=True)
    df['time'] = pd.to_datetime(df['create_time'], utc=True)
    df = df[df['time'].dt.minute == 0].drop_duplicates('time').set_index('time').sort_index()
    df.index = df.index - pd.Timedelta(hours=1)
    cols = {'sum_open_interest': 'oi', 'count_toptrader_long_short_ratio': 'top_ls_accounts',
            'sum_toptrader_long_short_ratio': 'top_ls_positions', 'count_long_short_ratio': 'global_ls_accounts'}
    return df[list(cols)].rename(columns=cols).astype(float)


def _daily_shifted(series: pd.Series) -> pd.Series:
    """Un dato del día D solo se conoce al terminar D: se usa desde D+1 00:00 UTC."""
    s = series.copy()
    s.index = pd.to_datetime(s.index, utc=True).normalize() + pd.Timedelta(days=1)
    return s[~s.index.duplicated(keep='last')].sort_index()


def fear_greed() -> pd.Series:
    def fetch():
        rows = requests.get("https://api.alternative.me/fng/?limit=0", timeout=30).json()['data']
        return pd.DataFrame({'time': [int(r['timestamp']) for r in rows], 'value': [r['value'] for r in rows]})
    df = _cached(DATA_DIR / "sentiment" / "fear_greed.csv.gz", fetch, permanent=False)
    return _daily_shifted(pd.Series(df['value'].astype(float).to_numpy(),
                                    index=pd.to_datetime(df['time'], unit='s', utc=True))).rename('fear_greed')


def wiki_views(article: str = "Solana_(blockchain_platform)", start: str = "2023-01") -> pd.Series:
    def fetch():
        end = datetime.now(timezone.utc).strftime("%Y%m%d")
        url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
               f"all-access/user/{article}/daily/{start.replace('-', '')}01/{end}")
        items = requests.get(url, headers=UA, timeout=30).json()['items']
        return pd.DataFrame({'time': [i['timestamp'][:8] for i in items], 'views': [i['views'] for i in items]})
    df = _cached(DATA_DIR / "sentiment" / f"wiki_{article}.csv.gz", fetch, permanent=False)
    return _daily_shifted(pd.Series(df['views'].astype(float).to_numpy(),
                                    index=pd.to_datetime(df['time'].astype(str), format="%Y%m%d"))).rename('wiki_views')


def gdelt_news(query: str = "solana", start: str = "2023-01") -> pd.DataFrame:
    """Noticias en inglés que mencionan `query`: tono medio y volumen diarios (GDELT)."""
    def fetch():
        out = []
        for mode, name in (('timelinetone', 'tone'), ('timelinevolraw', 'volume')):
            chunk_start = pd.Timestamp(f"{start}-01")
            while chunk_start < pd.Timestamp.now():
                chunk_end = min(chunk_start + pd.DateOffset(months=6), pd.Timestamp.now().normalize())
                url = ("https://api.gdeltproject.org/api/v2/doc/doc"
                       f"?query={query}%20sourcelang:english&mode={mode}&format=json"
                       f"&startdatetime={chunk_start:%Y%m%d%H%M%S}&enddatetime={chunk_end:%Y%m%d%H%M%S}")
                for attempt in range(8):
                    time.sleep(8)  # GDELT limita a 1 petición / 5 s
                    r = requests.get(url, timeout=60)
                    if r.ok and r.text.startswith('{'):
                        break
                    time.sleep(20 * (attempt + 1))
                else:
                    raise RuntimeError("GDELT no responde (límite de peticiones)")
                timeline = r.json().get('timeline') or [{'data': []}]
                data = timeline[0]['data']
                out += [{'date': d['date'][:8], 'metric': name, 'value': d['value']} for d in data]
                chunk_start = chunk_end
        return pd.DataFrame(out)
    df = _cached(DATA_DIR / "sentiment" / f"gdelt_{query}.csv.gz", fetch, permanent=False)
    wide = df.pivot_table(index='date', columns='metric', values='value', aggfunc='last')
    wide.index = pd.to_datetime(wide.index.astype(str), format="%Y%m%d")
    out = pd.DataFrame({c: _daily_shifted(wide[c]) for c in wide.columns})
    return out.rename(columns={'tone': 'news_tone', 'volume': 'news_volume'})


def load_full(start: str = "2023-01") -> pd.DataFrame:
    """
    Dataset completo de 1 h para el modelo combinado (Binance):
    SOL (OHLCV + taker + funding) + BTC/ETH + posicionamiento + sentimiento + noticias.
    """
    df = load_dataset("binance", start)
    for sym, tag in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
        k = binance_klines(sym, start)
        df[f'{tag}_close'] = k['close'].reindex(df.index)
        df[f'{tag}_volume'] = k['volume'].reindex(df.index)
    df = df.join(binance_metrics("SOLUSDT", start), how='left')
    daily = [fear_greed(), wiki_views(start=start)]
    # GDELT es lento (1 petición / 5 s): se descarga aparte con gdelt_news() y aquí solo se usa si ya está
    if (DATA_DIR / "sentiment" / "gdelt_solana.csv.gz").exists():
        daily.append(gdelt_news(start=start))
    else:
        print("ℹ️  Sin noticias GDELT en caché (descárgalas con: python -c 'import data; data.gdelt_news()')")
    daily = pd.concat(daily, axis=1)
    daily = daily.reindex(daily.index.union(df.index)).ffill().reindex(df.index)
    return df.join(daily)
