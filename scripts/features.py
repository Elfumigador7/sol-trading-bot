"""
Features técnicas compartidas entre el entrenamiento y el motor de trading.
Ambos DEBEN usar esta función para que el modelo reciba lo mismo que vio al entrenar.

Entrada: DataFrame de trades en orden con columnas
    'time' (datetime UTC), 'price', 'size', 'side' ('B' compra agresiva / 'A' venta agresiva)

Todas las features son relativas (no dependen del nivel de precio), para que el
modelo aprenda patrones y no "a qué precio estaba SOL cuando entrené".
Inspiradas en "Rise of the Machines? Intraday High-Frequency Trading Patterns"
(Petukhina, Reule, Härdle): momentum, volatility clustering, flujo de órdenes y
efectos de hora del día.
"""

import numpy as np
import pandas as pd

# Features que usa siempre el modelo
BASE_FEATURES = [
    'rsi_14',        # momentum
    'dist_sma_20',   # precio / SMA20 - 1
    'dist_sma_50',   # precio / SMA50 - 1
    'sma_20_50',     # SMA20 / SMA50 - 1 (tendencia)
    'ret_50',        # retorno de los últimos 50 trades
    'atr_14_pct',    # volatility clustering: |Δprecio| medio / precio
    'vol_ratio',     # volumen medio 20 / volumen medio 100 (actividad relativa)
    'buy_ratio_50',  # % del volumen iniciado por compradores (flujo de órdenes)
]

# Efecto hora del día (paper): solo tiene sentido con datos de muchos días
TIME_FEATURES = ['hour_sin', 'hour_cos']
MIN_DAYS_FOR_TIME_FEATURES = 7

# Trades mínimos para que todas las features estén definidas
MIN_HISTORY = 100


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    price = df['price']
    size = df['size']

    # RSI
    delta = price.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi_14'] = 100 - (100 / (1 + gain / (loss + 1e-10)))

    # Tendencia relativa
    sma_20 = price.rolling(window=20).mean()
    sma_50 = price.rolling(window=50).mean()
    df['dist_sma_20'] = price / sma_20 - 1
    df['dist_sma_50'] = price / sma_50 - 1
    df['sma_20_50'] = sma_20 / sma_50 - 1
    df['ret_50'] = price / price.shift(50) - 1

    # Volatilidad
    df['atr_14_pct'] = delta.abs().rolling(window=14).mean() / price

    # Volumen y flujo de órdenes
    df['vol_ratio'] = size.rolling(window=20).mean() / size.rolling(window=100).mean()
    buy_size = size.where(df['side'] == 'B', 0)
    df['buy_ratio_50'] = buy_size.rolling(window=50).sum() / size.rolling(window=50).sum()

    # Hora del día en forma cíclica (23h está cerca de 0h)
    hour = df['time'].dt.hour + df['time'].dt.minute / 60
    df['hour_sin'] = np.sin(2 * np.pi * hour / 24)
    df['hour_cos'] = np.cos(2 * np.pi * hour / 24)

    return df
