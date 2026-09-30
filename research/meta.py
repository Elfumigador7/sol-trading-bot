"""
🎯 Meta-labeling sobre la rotación (López de Prado, "Advances in Financial Machine Learning", cap. 3).

La regla (rotacion_top3) decide QUÉ comprar. El modelo solo decide si FIARSE de cada elección:
para cada día y cada moneda elegida por la rotación, predice si su retorno del día siguiente será
positivo. Si la probabilidad no llega al umbral, esa parte de la cartera se queda en liquidez.

Datos diarios = cierre de la vela de 1 h de las 00:00 UTC (el momento en que decide el bot).
Todo se valida en walk-forward mensual y se compara con la rotación sin filtro, con los mismos costes.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from portfolio import btc_regime, simulate, top_momentum

FIRST_TEST = pd.Timestamp('2021-07-01', tz='UTC')   # antes no hay historial suficiente para entrenar
FEATURES = ['ret_1d', 'ret_7d', 'ret_14d', 'ret_28d', 'dist_ema20', 'dist_ema50', 'vol_ratio',
            'mom_rank', 'btc_ret_7d', 'btc_dist_ema50', 'funding_z', 'dow_sin', 'dow_cos']
NEWS_FEATURES = ['sent_3d', 'alerts_3d', 'macro_sent_3d', 'fomc_3d']


def rotation_weights(close: pd.DataFrame) -> pd.DataFrame:
    return btc_regime(top_momentum(close, 14, 3, 20), close, 50)


def daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Filas de la vela de las 00:00 UTC, indexadas por su día."""
    d = frame[frame.index.hour == 0].copy()
    d.index = d.index.floor('D')
    return d


def build_dataset(close: pd.DataFrame, funding_last: pd.DataFrame, news: pd.DataFrame | None = None) -> pd.DataFrame:
    """Una fila por (día, moneda) elegida por la rotación, con features y etiqueta (retorno del día siguiente > 0)."""
    D = daily(close)
    F = daily(funding_last).reindex(D.index)
    picks = daily(rotation_weights(close)).reindex(D.index).fillna(0)

    r1 = D.pct_change()
    vol30 = r1.rolling(30).std()
    feats = {
        'ret_1d': r1 / vol30,
        'ret_7d': D.pct_change(7) / (vol30 * np.sqrt(7)),
        'ret_14d': D.pct_change(14) / (vol30 * np.sqrt(14)),
        'ret_28d': D.pct_change(28) / (vol30 * np.sqrt(28)),
        'dist_ema20': (D / D.ewm(span=20, adjust=False).mean() - 1) / vol30,
        'dist_ema50': (D / D.ewm(span=50, adjust=False).mean() - 1) / vol30,
        'vol_ratio': r1.rolling(7).std() / vol30,
        'mom_rank': D.pct_change(14).rank(axis=1, pct=True),
        'funding_z': (F - F.rolling(30).mean()) / F.rolling(30).std(),
    }
    btc = D['BTC']
    btc_vol = btc.pct_change().rolling(30).std()
    btc_ret7 = btc.pct_change(7) / (btc_vol * np.sqrt(7))
    btc_dist = (btc / btc.ewm(span=50, adjust=False).mean() - 1) / btc_vol
    next_ret = D.shift(-1) / D - 1

    rows = []
    for coin in D.columns:
        sel = picks[coin] > 0
        part = pd.DataFrame({k: v[coin] for k, v in feats.items()})[sel]
        part['btc_ret_7d'] = btc_ret7[sel]
        part['btc_dist_ema50'] = btc_dist[sel]
        part['coin'] = coin
        part['weight'] = picks[coin][sel]
        part['next_ret'] = next_ret[coin][sel]
        rows.append(part)
    ds = pd.concat(rows).sort_index()
    ds['dow_sin'] = np.sin(2 * np.pi * ds.index.dayofweek / 7)
    ds['dow_cos'] = np.cos(2 * np.pi * ds.index.dayofweek / 7)
    if news is not None:  # sentimiento medio y alertas de los 3 días previos, por moneda
        ds = ds.join(news, on=[ds.index.rename('day'), 'coin'], how='left')
        ds[NEWS_FEATURES] = ds[NEWS_FEATURES].fillna(0.0)
    ds['y'] = (ds['next_ret'] > 0).astype(float).where(ds['next_ret'].notna())
    return ds


def make_model():
    return HistGradientBoostingClassifier(learning_rate=0.05, max_iter=150, max_leaf_nodes=8,
                                          min_samples_leaf=60, l2_regularization=1.0, random_state=42)


def walk_forward(ds: pd.DataFrame, features: list, first_test=FIRST_TEST) -> pd.Series:
    """Probabilidad fuera de muestra para cada fila, reentrenando cada mes con todo el pasado."""
    probs = pd.Series(np.nan, index=range(len(ds)))
    ds = ds.reset_index(names='day')
    months = pd.date_range(first_test, ds['day'].max() + pd.Timedelta(days=1), freq='MS', tz='UTC')
    for m0, m1 in zip(months, list(months[1:]) + [ds['day'].max() + pd.Timedelta(days=1)]):
        train = ds[(ds['day'] < m0 - pd.Timedelta(days=1)) & ds['y'].notna()]
        test = ds[(ds['day'] >= m0) & (ds['day'] < m1)]
        if len(train) < 200 or test.empty:
            continue
        model = make_model().fit(train[features], train['y'])
        probs.loc[test.index] = model.predict_proba(test[features])[:, 1]
    return probs.to_numpy()


def filtered_weights(close: pd.DataFrame, ds: pd.DataFrame, probs: np.ndarray, threshold: float) -> pd.DataFrame:
    """Pesos de la rotación, quitando las elecciones cuya probabilidad no llega al umbral."""
    w = rotation_weights(close).copy()
    drop = ds.assign(p=probs)
    drop = drop[drop['p'].notna() & (drop['p'] < threshold)]
    idx0 = w.index[w.index.hour == 0]
    day_to_bar = pd.Series(idx0, index=idx0.floor('D'))
    for day, row in drop.iterrows():
        if day in day_to_bar.index:
            w.loc[day_to_bar[day], row['coin']] = 0.0
    return w


def evaluate(u: dict, weights: pd.DataFrame, start) -> pd.Series:
    r, _ = simulate(u, weights.fillna(0), start=str(pd.Timestamp(start).date()))
    return r
