"""
🧱 Features horarias del modelo combinado. Las usa el entrenamiento Y el bot en vivo.

Regla: el valor de la fila t solo usa información disponible al CIERRE de la vela t.
Todo va normalizado (retornos en unidades de volatilidad, ratios, z-scores) para que
2023 y 2026 sean comparables aunque SOL cotice a precios muy distintos.

Bloques:
  precio        retornos multi-horizonte, medias, rango, velas
  estructura    swing highs/lows (HH/HL vs LH/LL), rupturas de estructura, distancias en ATR
  volatilidad   régimen y compresión
  flujo         volumen relativo, volumen comprador agresivo, nº de trades
  derivados     funding, open interest, ratios largo/corto (posicionamiento)
  mercado       BTC y ETH (arrastre), fuerza relativa, correlación
  calendario    hora y día de la semana (cíclicos)
  sentimiento   Fear & Greed, visitas a Wikipedia, tono y volumen de noticias (GDELT)
"""

import numpy as np
import pandas as pd

FEATURES_VERSION = "h1.0"
WEEK = 24 * 7
MONTH = 24 * 30


def _z(s: pd.Series, window: int) -> pd.Series:
    return (s - s.rolling(window).mean()) / s.rolling(window).std()


def _swings(high: pd.Series, low: pd.Series, k: int):
    """Último y penúltimo swing high/low CONFIRMADOS (un pivote en p se confirma en p + k)."""
    is_ph = high == high.rolling(2 * k + 1, center=True).max()
    is_pl = low == low.rolling(2 * k + 1, center=True).min()
    ph = high.shift(k).where(is_ph.shift(k, fill_value=False))
    pl = low.shift(k).where(is_pl.shift(k, fill_value=False))

    def last_prev(p):
        pts = p.dropna()
        return p.ffill(), pts.shift(1).reindex(p.index).ffill()
    return (*last_prev(ph), *last_prev(pl))


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    close, high, low = df['close'], df['high'], df['low']
    r1 = close.pct_change()
    vol = r1.rolling(WEEK).std()  # volatilidad horaria típica de la última semana

    # --- precio ---
    for k in (1, 3, 6, 12, 24, 72, 168):
        f[f'ret_{k}h'] = close.pct_change(k) / (vol * np.sqrt(k))
    for span in (24, 168):
        f[f'dist_ema_{span}'] = (close / close.ewm(span=span, adjust=False).mean() - 1) / vol
    f['ema_24_168'] = (close.ewm(span=24, adjust=False).mean()
                       / close.ewm(span=168, adjust=False).mean() - 1) / vol
    for n in (24, 168):
        hi, lo = high.rolling(n).max(), low.rolling(n).min()
        f[f'range_pos_{n}'] = (close - lo) / (hi - lo)
    rng = (high - low).replace(0, np.nan)
    f['candle_body'] = (close - df['open']) / rng
    f['upper_wick'] = (high - np.maximum(close, df['open'])) / rng
    f['lower_wick'] = (np.minimum(close, df['open']) - low) / rng

    # --- estructura de mercado ---
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(24).mean()
    for k in (6, 24):
        last_ph, prev_ph, last_pl, prev_pl = _swings(high, low, k)
        f[f'struct_{k}'] = np.sign(last_ph - prev_ph) + np.sign(last_pl - prev_pl)  # +2 = HH+HL
        f[f'dist_swing_high_{k}'] = (close - last_ph) / atr
        f[f'dist_swing_low_{k}'] = (close - last_pl) / atr
        f[f'bos_up_{k}'] = (close > last_ph).astype(float)     # ruptura de estructura alcista
        f[f'bos_down_{k}'] = (close < last_pl).astype(float)

    # --- volatilidad ---
    f['vol_24_168'] = r1.rolling(24).std() / vol
    f['vol_168_720'] = vol / r1.rolling(MONTH).std()
    width = close.rolling(24).std() / close.rolling(24).mean()
    f['squeeze_rank'] = width.rolling(MONTH).rank(pct=True)
    f['atr_pct'] = atr / close

    # --- flujo ---
    f['volume_rel'] = np.log(df['volume'] / df['volume'].rolling(WEEK).mean())
    f['trades_rel'] = np.log(df['count'] / df['count'].rolling(WEEK).mean())
    for k in (1, 6, 24):
        buy = df['taker_buy_volume'].rolling(k).sum() / df['volume'].rolling(k).sum()
        f[f'buy_ratio_z_{k}h'] = _z(buy, WEEK)

    # --- derivados / posicionamiento ---
    f['funding'] = df['funding_last'] * 1e4
    f['funding_z'] = _z(df['funding_last'], MONTH)
    if 'oi' in df:
        oi = df['oi'].ffill()
        for k in (1, 6, 24):
            f[f'oi_chg_{k}h'] = oi.pct_change(k)
        f['oi_z'] = _z(oi, WEEK)
        f['oi_price_div'] = np.sign(close.pct_change(24)) * oi.pct_change(24)  # sube precio con OI cayendo = cortos cerrando
        for c in ('top_ls_accounts', 'top_ls_positions', 'global_ls_accounts'):
            s = df[c].ffill()
            f[c] = s
            f[f'{c}_z'] = _z(s, WEEK)
            f[f'{c}_chg_24h'] = s.pct_change(24)

    # --- mercado (BTC / ETH) ---
    for tag in ('btc', 'eth'):
        if f'{tag}_close' not in df:
            continue
        c = df[f'{tag}_close']
        cr = c.pct_change()
        cvol = cr.rolling(WEEK).std()
        for k in (1, 6, 24):
            f[f'{tag}_ret_{k}h'] = c.pct_change(k) / (cvol * np.sqrt(k))
        f[f'{tag}_corr_168'] = r1.rolling(WEEK).corr(cr)
        f[f'sol_vs_{tag}_24h'] = f['ret_24h'] - f[f'{tag}_ret_24h']

    # --- calendario ---
    hour = df.index.hour
    dow = df.index.dayofweek
    f['hour_sin'], f['hour_cos'] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    f['dow_sin'], f['dow_cos'] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)

    # --- sentimiento y noticias (diarios, ya desplazados para no mirar al futuro) ---
    if 'fear_greed' in df:
        f['fear_greed'] = df['fear_greed']
        f['fear_greed_chg_7d'] = df['fear_greed'] - df['fear_greed'].shift(WEEK)
    if 'wiki_views' in df:
        f['wiki_attention'] = np.log(df['wiki_views'] / df['wiki_views'].rolling(MONTH).mean())
    if 'news_volume' in df:
        f['news_attention'] = np.log((df['news_volume'] + 1) / (df['news_volume'].rolling(MONTH).mean() + 1))
        f['news_tone'] = df['news_tone']
        f['news_tone_z'] = _z(df['news_tone'], MONTH)

    return f.replace([np.inf, -np.inf], np.nan)
