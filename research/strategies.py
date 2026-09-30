"""
📚 Estrategias a probar (hipótesis sacadas de papers). Todas las operaciones duran ≤ 48 h.

Cada función devuelve las entradas: +1 largo, -1 corto, 0 nada, calculadas solo con datos
hasta el cierre de cada vela. El `grid` son los parámetros que el walk-forward puede elegir.

Para añadir un paper nuevo: escribe su función, añade un Strategy a STRATEGIES y ejecuta
run_lab.py. Si no bate a los benchmarks fuera de muestra, queda documentado como descartado.
"""

import numpy as np
import pandas as pd

from lab import Strategy

WEEK = 24 * 7
MONTH = 24 * 30


def _zscore_return(df: pd.DataFrame, k: int) -> pd.Series:
    """Retorno de las últimas k horas dividido por la volatilidad esperada en k horas."""
    r1 = df['close'].pct_change()
    vol = r1.rolling(WEEK).std() * np.sqrt(k)
    return df['close'].pct_change(k) / vol


# 1. Momentum intradía ---------------------------------------------------------
def momentum_entries(df, train, k, thr, hold):
    z = _zscore_return(df, k)
    return np.sign(z).where(z.abs() > thr, 0).fillna(0)


# 2. Reversión intradía --------------------------------------------------------
def reversal_entries(df, train, k, thr, hold):
    return -momentum_entries(df, train, k, thr, hold)


# 3. Estacionalidad por hora del día (aprendida en train) ---------------------
def seasonality_entries(df, train, hold, t_min):
    fwd = train['close'].shift(-hold) / train['close'] - 1
    by_hour = fwd.groupby(train.index.hour).agg(['mean', 'std', 'count'])
    t_stat = by_hour['mean'] / (by_hour['std'] / np.sqrt(by_hour['count']))
    side_by_hour = np.sign(by_hour['mean']).where(t_stat.abs() > t_min, 0)
    return pd.Series(df.index.hour.map(side_by_hour).to_numpy(), index=df.index).fillna(0)


# 4. Funding extremo → reversión ----------------------------------------------
def funding_entries(df, train, thr, hold):
    f = df['funding_last']
    z = (f - f.rolling(MONTH).mean()) / f.rolling(MONTH).std()
    # Funding muy alto = demasiados largos apalancados → apostar a la bajada (y al revés)
    return (-np.sign(z)).where(z.abs() > thr, 0).fillna(0)


# 5. Ruptura tras compresión de volatilidad -----------------------------------
def breakout_entries(df, train, n, squeeze_pct, hold):
    close = df['close']
    width = close.rolling(24).std() / close.rolling(24).mean()
    squeezed = (width.rolling(MONTH).rank(pct=True) < squeeze_pct).shift(1, fill_value=False)
    up = close > df['high'].rolling(n).max().shift(1)
    down = close < df['low'].rolling(n).min().shift(1)
    side = pd.Series(0.0, index=df.index)
    side[up & squeezed] = 1
    side[down & squeezed] = -1
    return side


# 6. Flujo de órdenes (volumen comprador agresivo) ----------------------------
def order_flow_entries(df, train, k, thr, hold):
    buy_ratio = df['taker_buy_volume'].rolling(k).sum() / df['volume'].rolling(k).sum()
    z = (buy_ratio - buy_ratio.rolling(WEEK).mean()) / buy_ratio.rolling(WEEK).std()
    return np.sign(z).where(z.abs() > thr, 0).fillna(0)


# Benchmark: regla simple, sin optimizar ----------------------------------------
def simple_rule_entries(df, train=None, hold=24):
    """Cada día a las 00 UTC: largo si SOL subió en las últimas 24 h, corto si bajó."""
    side = np.sign(df['close'].pct_change(24)).fillna(0)
    return side.where(df.index.hour == 0, 0)


STRATEGIES = [
    Strategy(
        name='momentum_intradia',
        reference='Gao, Han, Li & Zhou (2018) "Market Intraday Momentum", JFE; '
                  'Wen, Bouri, Xu & Zhao (2022) sobre momentum/reversión intradía en cripto',
        idea='Un movimiento fuerte en las últimas k horas continúa en las siguientes',
        grid={'k': [3, 6, 12, 24], 'thr': [0.5, 1.0, 1.5, 2.0], 'hold': [3, 6, 12, 24]},
        entries=momentum_entries,
    ),
    Strategy(
        name='reversion_intradia',
        reference='Wen, Bouri, Xu & Zhao (2022); literatura de reversión a corto plazo',
        idea='Un movimiento fuerte en las últimas k horas se corrige en las siguientes',
        grid={'k': [3, 6, 12, 24], 'thr': [0.5, 1.0, 1.5, 2.0], 'hold': [3, 6, 12, 24]},
        entries=reversal_entries,
    ),
    Strategy(
        name='estacionalidad_horaria',
        reference='Petukhina, Reule & Härdle (2021) "Rise of the machines? Intraday '
                  'high-frequency trading patterns of cryptocurrencies", EJF',
        idea='Algunas horas del día tienen retornos sistemáticamente positivos o negativos',
        grid={'hold': [1, 2, 4, 8], 't_min': [1.5, 2.0, 2.5, 3.0]},
        entries=seasonality_entries,
        needs_fit=True,
    ),
    Strategy(
        name='funding_extremo',
        reference='He, Manela, Ross & von Wachter (2022) "Fundamentals of Perpetual Futures"',
        idea='Un funding anormalmente alto/bajo indica exceso de apalancamiento que se deshace',
        grid={'thr': [1.0, 1.5, 2.0, 2.5], 'hold': [8, 24, 48]},
        entries=funding_entries,
    ),
    Strategy(
        name='ruptura_volatilidad',
        reference='Clásico técnico (Bollinger squeeze / Donchian) + volatility clustering',
        idea='Tras un periodo de volatilidad comprimida, la ruptura de rango continúa',
        grid={'n': [12, 24, 48], 'squeeze_pct': [0.1, 0.2, 0.3], 'hold': [6, 12, 24, 48]},
        entries=breakout_entries,
    ),
    Strategy(
        name='flujo_ordenes',
        reference='Literatura de order flow imbalance (p. ej. Cont, Kukanov & Stoikov, 2014)',
        idea='Si los compradores agresivos dominan de forma anormal, el precio sigue subiendo',
        grid={'k': [1, 3, 6, 12], 'thr': [1.0, 1.5, 2.0, 2.5], 'hold': [3, 6, 12, 24]},
        entries=order_flow_entries,
        requires=['taker_buy_volume'],
    ),
]
