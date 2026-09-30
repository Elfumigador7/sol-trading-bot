"""
🤖 Modelo combinado: todas las features → probabilidad de que un largo / un corto salga bien.

Etiquetas de triple barrera (López de Prado, "Advances in Financial Machine Learning"):
  para cada hora t se simula entrar al cierre con
    take-profit  = +mult · σ_h · √H   (orden límite → comisión maker)
    stop-loss    = −mult · σ_h · √H   (a mercado → taker + slippage)
    tiempo       = H horas (≤ 48)      (a mercado)
  Si en una vela se tocan TP y SL, se asume SL (conservador).
  y_long = 1 si el largo termina con beneficio neto de costes y funding; igual y_short.

Validación walk-forward mensual: se entrena solo con filas cuyo resultado ya se conocía
(purga de H horas antes del test), con más peso a los datos recientes, y se predice el mes
siguiente. Las operaciones se simulan con exactamente las mismas barreras y costes.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from lab import COST, MAKER_FEE, MAX_HOLD_H

WEEK = 24 * 7


@dataclass
class Setup:
    horizon: int = 24          # horas máximas por operación
    mult: float = 1.0          # anchura de TP/SL en unidades de σ·√H
    lookback_days: int | None = 365   # None = todo el historial
    half_life_days: float = 180       # peso de una fila = 0.5 ** (antigüedad / half_life)

    def name(self):
        lb = 'todo' if self.lookback_days is None else f'{self.lookback_days}d'
        return f"H{self.horizon}_m{self.mult}_lb{lb}"


def barrier_outcomes(df: pd.DataFrame, horizon: int, mult: float) -> dict:
    """Resultado neto, vela de salida, precio y comisión de salida de abrir un largo / corto en cada hora."""
    assert horizon <= MAX_HOLD_H
    close, high, low = df['close'].to_numpy(), df['high'].to_numpy(), df['low'].to_numpy()
    funding = df['funding'].to_numpy()
    vol = df['close'].pct_change().rolling(WEEK).std().to_numpy()
    width = vol * np.sqrt(horizon) * mult
    n = len(df)
    cum_fund = np.concatenate([[0], np.cumsum(funding)])

    out = {}
    for side in (1, -1):
        net = np.full(n, np.nan)
        exit_idx = np.full(n, -1)
        exit_px = np.full(n, np.nan)
        exit_fee = np.full(n, np.nan)
        for t in range(n - 1):
            w = width[t]
            if not np.isfinite(w) or w <= 0:
                continue
            entry = close[t]
            tp = entry * (1 + side * w)
            sl = entry * (1 - side * w)
            last = t + horizon
            hit = None
            for j in range(t + 1, min(last, n - 1) + 1):
                if (low[j] <= sl) if side > 0 else (high[j] >= sl):
                    hit = (j, sl, COST)          # stop a mercado
                    break
                if (high[j] >= tp) if side > 0 else (low[j] <= tp):
                    hit = (j, tp, MAKER_FEE)     # take-profit con orden límite
                    break
            if hit is None:
                if last > n - 1:
                    continue                     # aún no se sabe cómo acaba: sin etiqueta
                hit = (last, close[last], COST)  # salida por tiempo
            e, px, fee = hit
            fund = cum_fund[e + 1] - cum_fund[t + 1]
            net[t] = side * (px / entry - 1) - COST - fee - side * fund
            exit_idx[t], exit_px[t], exit_fee[t] = e, px, fee
        out[side] = {'net': net, 'exit': exit_idx, 'exit_px': exit_px, 'fee': exit_fee}
    return out


def simulate(df: pd.DataFrame, sides: pd.Series, outcomes: dict) -> tuple[pd.Series, pd.DataFrame]:
    """Una posición a la vez. Devuelve retornos por vela (marcados a mercado) y operaciones."""
    close = df['close'].to_numpy()
    funding = df['funding'].to_numpy()
    s = sides.reindex(df.index).fillna(0).to_numpy()
    n = len(df)
    bar = np.zeros(n)
    trades = []
    t = 0
    while t < n - 1:
        side = int(s[t])
        if side == 0 or outcomes[side]['exit'][t] < 0:
            t += 1
            continue
        o = outcomes[side]
        e, px = o['exit'][t], o['exit_px'][t]
        for j in range(t + 1, e + 1):
            cur = px if j == e else close[j]
            bar[j] += side * (cur / close[j - 1] - 1) - side * funding[j]
        bar[t + 1] -= COST
        bar[e] -= o['fee'][t]
        trades.append((df.index[t], df.index[e], side, close[t], px, o['net'][t]))
        t = e
    trades = pd.DataFrame(trades, columns=['entry_time', 'exit_time', 'side', 'entry', 'exit', 'net_return'])
    return pd.Series(bar, index=df.index), trades


def make_model():
    return HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=250, max_leaf_nodes=15, min_samples_leaf=300,
        l2_regularization=1.0, random_state=42)


def walk_forward_probs(feats: pd.DataFrame, labels: dict, setup: Setup, first_test: pd.Timestamp,
                       test_days: int = 30, log=print) -> pd.DataFrame:
    """Probabilidades fuera de muestra de largo y corto para cada hora desde first_test."""
    probs = pd.DataFrame(np.nan, index=feats.index, columns=['p_long', 'p_short'])
    X_all = feats.to_numpy(dtype=np.float32)
    idx = feats.index
    purge = pd.Timedelta(hours=setup.horizon)
    t0 = first_test
    while t0 < idx[-1]:
        t1 = t0 + pd.Timedelta(days=test_days)
        train_mask = idx < t0 - purge
        if setup.lookback_days:
            train_mask &= idx >= t0 - pd.Timedelta(days=setup.lookback_days)
        test_mask = (idx >= t0) & (idx < t1)
        age_days = ((t0 - idx[train_mask]).total_seconds() / 86400).to_numpy()
        weights = 0.5 ** (age_days / setup.half_life_days)
        for side, col in ((1, 'p_long'), (-1, 'p_short')):
            y = labels[side][train_mask]
            ok = ~np.isnan(y)
            model = make_model().fit(X_all[train_mask][ok], y[ok].astype(int), sample_weight=weights[ok])
            probs.loc[test_mask, col] = model.predict_proba(X_all[test_mask])[:, 1]
        log(f"   {setup.name()} | test {t0:%Y-%m} | train {train_mask.sum()} filas")
        t0 = t1
    return probs


def sides_from_probs(probs: pd.DataFrame, threshold: float) -> pd.Series:
    long_ok = (probs['p_long'] >= threshold) & (probs['p_long'] >= probs['p_short'])
    short_ok = (probs['p_short'] >= threshold) & (probs['p_short'] > probs['p_long'])
    return pd.Series(np.where(long_ok, 1, np.where(short_ok, -1, 0)), index=probs.index)
