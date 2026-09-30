"""
💼 Carteras multi-moneda con rebalanceo diario (00 UTC), costes por rotación y funding.

Universo: las monedas del top-20 en ENERO de 2023 con perpetuo en Binance (no las ganadoras
de hoy, para no introducir sesgo de supervivencia).
"""

import numpy as np
import pandas as pd

from data import binance_funding, binance_klines
from lab import COST

UNIVERSE = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOGE', 'SOL', 'DOT', 'LTC', 'AVAX', 'LINK']


def load_universe(coins=UNIVERSE, start: str = '2023-01') -> dict:
    """{'close': DataFrame horas × monedas, 'funding': ídem (tasa pagada en esa vela), 'funding_last': ídem}."""
    close, paid, last = {}, {}, {}
    for c in coins:
        k = binance_klines(f'{c}USDT', start)
        f = binance_funding(f'{c}USDT', start)
        close[c] = k['close']
        p = f.copy()
        p.index = p.index - pd.Timedelta(hours=1)
        paid[c] = p
        last[c] = f
    close = pd.DataFrame(close)
    close = close[close.index + pd.Timedelta(hours=1) <= pd.Timestamp.now(tz='UTC')]
    return {
        'close': close,
        'funding': pd.DataFrame(paid).reindex(close.index).fillna(0.0),
        'funding_last': pd.DataFrame(last).reindex(close.index, method='ffill'),
    }


def simulate(u: dict, weights: pd.DataFrame, start: str = '2023-09-01') -> tuple[pd.Series, pd.Series]:
    """
    `weights`: peso objetivo por moneda (fracción del capital, suma ≤ 1), calculado al cierre de
    cada vela; solo se usa el de la vela de las 00 UTC y se aplica desde la vela siguiente.
    Devuelve (retorno neto por vela, rotación diaria).
    """
    close = u['close']
    idx = close.index
    w = weights.reindex(idx).where(pd.Series(idx.hour == 0, index=idx), axis=0).ffill().fillna(0).shift(1).fillna(0)
    r = close.pct_change().fillna(0)
    turnover = w.diff().abs().sum(axis=1).fillna(0)
    ret = (w * r).sum(axis=1) - (w * u['funding']).sum(axis=1) - turnover * COST
    mask = idx >= start
    return ret[mask], turnover[mask]


# ---------- Señales ----------

def ema_trend(close: pd.DataFrame, days: int) -> pd.DataFrame:
    return (close > close.ewm(span=24 * days, adjust=False).mean()).astype(float)


def multi_speed_trend(close: pd.DataFrame, speeds=(10, 20, 50)) -> pd.DataFrame:
    """Media de varias velocidades: 0, 1/3, 2/3 o 1 según cuántas señales estén alcistas."""
    return sum(ema_trend(close, d) for d in speeds) / len(speeds)


def equal_weight(signal: pd.DataFrame) -> pd.DataFrame:
    """Cada moneda pesa 1/N del capital × su señal (0..1)."""
    return signal / signal.shape[1]


def top_momentum(close: pd.DataFrame, lookback_days: int = 14, k: int = 3, trend_days: int = 20) -> pd.DataFrame:
    """Momentum entre monedas: las k con mayor retorno de `lookback_days`, solo si están en tendencia."""
    mom = close.pct_change(24 * lookback_days)
    trend = ema_trend(close, trend_days)
    rank = mom.rank(axis=1, ascending=False)
    return ((rank <= k) & (trend > 0)).astype(float) / k


def btc_regime(weights: pd.DataFrame, close: pd.DataFrame, days: int = 50) -> pd.DataFrame:
    """Las altcoins solo pueden estar compradas si BTC está sobre su EMA."""
    ok = ema_trend(close[['BTC']], days)['BTC']
    out = weights.copy()
    alts = [c for c in out.columns if c != 'BTC']
    out[alts] = out[alts].mul(ok, axis=0)
    return out


def funding_filter(weights: pd.DataFrame, funding_last: pd.DataFrame, z_max: float = 2.0) -> pd.DataFrame:
    """Fuera de una moneda si su funding está > z_max desviaciones sobre su media de 30 días (euforia apalancada)."""
    f = funding_last[weights.columns]
    z = (f - f.rolling(24 * 30).mean()) / f.rolling(24 * 30).std()
    return weights.where(~(z > z_max), 0.0)


def vol_target(weights: pd.DataFrame, close: pd.DataFrame, target: float = 0.60) -> pd.DataFrame:
    """Escala la cartera para que su volatilidad anual estimada (30 días) no pase de `target`."""
    r = close[weights.columns].pct_change()
    port = (weights.shift(1) * r).sum(axis=1)
    vol = port.rolling(24 * 30).std() * np.sqrt(24 * 365)
    scale = (target / vol).clip(upper=1.0).fillna(1.0)
    return weights.mul(scale, axis=0)
