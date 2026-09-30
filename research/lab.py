"""
🧪 Laboratorio de backtesting: operaciones cortas (≤ 48 h) con costes reales.

Reglas del juego (para no engañarnos):
- Una señal al cierre de la vela t se ejecuta al cierre de t (≈ apertura de t+1). Las
  estrategias solo pueden usar datos hasta t.
- Cada operación dura `hold` velas (máx. 48 h). Una posición a la vez.
- Costes: comisión taker + slippage por lado, y funding de perpetuos mientras se mantiene.
- Walk-forward: los parámetros se eligen con los últimos `train_days` y se prueban en los
  `test_days` siguientes, que el optimizador nunca vio. Solo cuenta el resultado de test.
- Deflated Sharpe Ratio (Bailey & López de Prado, 2014): corrige la suerte de haber
  probado muchas combinaciones.
"""

from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd
from scipy import stats

FEE = 0.00045        # taker Hyperliquid / Binance por lado
MAKER_FEE = 0.00015  # maker Hyperliquid (nivel base)
SLIPPAGE = 0.0002    # spread + deslizamiento por lado (solo órdenes a mercado)
COST = FEE + SLIPPAGE
MAX_HOLD_H = 48
BARS_PER_YEAR = 24 * 365


@dataclass
class Execution:
    """
    Cómo se ejecutan las órdenes.

    taker: a mercado al cierre de la vela de la señal. Siempre se ejecuta; paga FEE + SLIPPAGE.

    maker: orden límite al precio de cierre de la señal (± entry_offset a nuestro favor).
      - Se ejecuta solo si alguna de las `entry_wait` velas siguientes CRUZA el precio
        (low < límite para comprar, high > límite para vender). Tocarlo no basta: habría
        cola delante. Si no se ejecuta, la operación se pierde.
      - Esto modela la selección adversa: solo te llenan cuando el precio va contra ti,
        y te pierdes justo las operaciones que salen disparadas a tu favor.
      - Salida: orden límite al cierre de la vela de salida; si en `exit_wait` velas no se
        ejecuta, se cierra a mercado (taker) para respetar el límite de tiempo.
    """
    mode: str = 'taker'
    entry_offset: float = 0.0
    entry_wait: int = 2
    exit_wait: int = 1

    def label(self) -> str:
        if self.mode == 'taker':
            return f"taker ({COST:.3%}/lado)"
        return (f"maker ({MAKER_FEE:.3%}/lado, límite {self.entry_offset:+.2%}, "
                f"espera {self.entry_wait}h, salida a mercado si no se llena en {self.exit_wait}h)")


TAKER = Execution('taker')
MAKER = Execution('maker')


@dataclass
class Strategy:
    name: str
    reference: str
    idea: str
    grid: dict
    entries: callable          # entries(df, train, **params) -> Series {-1, 0, 1}
    needs_fit: bool = False    # True si usa `train` para aprender algo (p. ej. estacionalidad)
    requires: list = field(default_factory=list)  # columnas necesarias

    def param_sets(self):
        keys = list(self.grid)
        return [dict(zip(keys, values)) for values in product(*self.grid.values())]


@dataclass
class Result:
    returns: pd.Series   # retorno neto por vela
    trades: pd.DataFrame


def backtest(df: pd.DataFrame, entries: pd.Series, hold, execution: Execution = TAKER) -> Result:
    """`hold`: int o Series (velas por operación en cada entrada)."""
    close = df['close'].to_numpy()
    high = df['high'].to_numpy()
    low = df['low'].to_numpy()
    funding = df['funding'].to_numpy()
    sig = entries.reindex(df.index).fillna(0).to_numpy()
    holds = (hold.reindex(df.index).fillna(1).to_numpy().astype(int)
             if isinstance(hold, pd.Series) else np.full(len(df), int(hold)))
    n = len(df)
    maker = execution.mode == 'maker'

    bar_ret = np.zeros(n)
    r = np.zeros(n)
    r[1:] = close[1:] / close[:-1] - 1
    trades = []
    missed = 0

    i = 0
    while i < n - 1:
        side = sig[i]
        if side == 0:
            i += 1
            continue

        # --- Entrada ---
        if maker:
            limit = close[i] * (1 - side * execution.entry_offset)
            k = next((k for k in range(i + 1, min(i + execution.entry_wait, n - 1) + 1)
                      if (low[k] < limit if side > 0 else high[k] > limit)), None)
            if k is None:
                missed += 1
                i += 1
                continue
            entry_price, entry_bar = limit, k
            bar_ret[k] += side * (close[k] / limit - 1) - side * funding[k] - MAKER_FEE
            entry_fee = MAKER_FEE
            h = min(holds[i], MAX_HOLD_H - execution.exit_wait)
        else:
            entry_price, entry_bar = close[i], i
            bar_ret[i + 1] -= COST
            entry_fee = COST
            h = min(holds[i], MAX_HOLD_H)

        # --- Mantener hasta la vela de salida j ---
        j = min(entry_bar + h, n - 1)
        seg = slice(entry_bar + 1, j + 1)
        bar_ret[seg] += side * r[seg] - side * funding[seg]
        fund_paid = side * funding[entry_bar + 1:j + 1].sum() + (side * funding[entry_bar] if maker else 0)

        # --- Salida ---
        exit_price, exit_bar, exit_fee = close[j], j, COST
        if maker:
            target = close[j]
            filled = next((m for m in range(j + 1, min(j + execution.exit_wait, n - 1) + 1)
                           if (high[m] > target if side > 0 else low[m] < target)), None)
            if filled is not None:
                exit_bar, exit_fee = filled, MAKER_FEE
                bar_ret[filled] -= MAKER_FEE  # sale a `target`: sin retorno extra en esa vela
            else:
                # No se llenó: seguimos expuestos esas velas y cerramos a mercado
                last = min(j + execution.exit_wait, n - 1)
                seg2 = slice(j + 1, last + 1)
                bar_ret[seg2] += side * r[seg2] - side * funding[seg2]
                fund_paid += side * funding[seg2].sum()
                exit_price, exit_bar = close[last], last
                bar_ret[last] -= COST
        else:
            bar_ret[j] -= COST

        net = side * (exit_price / entry_price - 1) - entry_fee - exit_fee - fund_paid
        trades.append((df.index[i], df.index[exit_bar], int(side), entry_price, exit_price, net))
        i = exit_bar

    trades = pd.DataFrame(trades, columns=['entry_time', 'exit_time', 'side', 'entry', 'exit', 'net_return'])
    trades.attrs['missed'] = missed
    return Result(pd.Series(bar_ret, index=df.index), trades)


def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    """Benchmark: comprado todo el periodo en el perpetuo (paga funding)."""
    ret = df['close'].pct_change().fillna(0) - df['funding']
    ret.iloc[0] -= COST
    return ret


def metrics(returns: pd.Series, trades: pd.DataFrame | None = None) -> dict:
    equity = (1 + returns).cumprod()
    std = returns.std()
    out = {
        'retorno_total': equity.iloc[-1] - 1,
        'sharpe': returns.mean() / std * np.sqrt(BARS_PER_YEAR) if std > 0 else 0.0,
        'max_drawdown': (equity / equity.cummax() - 1).min(),
    }
    if trades is not None:
        out.update({
            'operaciones': len(trades),
            'aciertos': (trades['net_return'] > 0).mean() if len(trades) else np.nan,
            'media_por_op': trades['net_return'].mean() if len(trades) else np.nan,
        })
    return out


def deflated_sharpe(returns: pd.Series, trial_sharpes: list) -> tuple[float, float]:
    """
    (PSR, DSR): probabilidad de que el Sharpe real sea > 0 (PSR) y > el mejor Sharpe que
    cabría esperar por pura suerte tras N pruebas (DSR). Sharpe por vela, sin anualizar.
    """
    r = returns.to_numpy()
    T = len(r)
    if T < 10 or r.std() == 0:
        return np.nan, np.nan
    sr = r.mean() / r.std()
    skew = stats.skew(r)
    kurt = stats.kurtosis(r, fisher=False)
    denom = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))

    def psr(sr0):
        return float(stats.norm.cdf((sr - sr0) * np.sqrt(T - 1) / denom))

    trials = np.asarray([s for s in trial_sharpes if np.isfinite(s)])
    N = max(len(trials), 2)
    emc = 0.5772156649
    sr_max_luck = np.sqrt(np.var(trials)) * ((1 - emc) * stats.norm.ppf(1 - 1 / N)
                                              + emc * stats.norm.ppf(1 - 1 / (N * np.e)))
    return psr(0.0), psr(sr_max_luck)


def walk_forward(df: pd.DataFrame, strategy: Strategy, train_days: int = 90, test_days: int = 30,
                 min_train_trades: int = 10, execution: Execution = TAKER) -> dict:
    """Optimiza en train, aplica en test, avanza `test_days`. Devuelve el resultado fuera de muestra."""
    params_list = strategy.param_sets()
    start, end = df.index[0], df.index[-1]
    train_len, test_len = pd.Timedelta(days=train_days), pd.Timedelta(days=test_days)

    # Estrategias sin ajuste: calcular las señales una sola vez por combinación
    cache = {}
    if not strategy.needs_fit:
        for k, p in enumerate(params_list):
            cache[k] = strategy.entries(df, None, **p)

    oos_entries = pd.Series(0.0, index=df.index)
    oos_hold = pd.Series(1, index=df.index)
    windows = []

    # Para el DSR: Sharpe de cada configuración probada en todo el periodo (una prueba = una combinación)
    trial_sharpes = []
    for k, p in enumerate(params_list):
        if k in cache:
            ret = backtest(df, cache[k], p['hold'], execution).returns
            trial_sharpes.append(ret.mean() / ret.std() if ret.std() > 0 else 0.0)
    window_sharpes = {k: [] for k in range(len(params_list))}

    t0 = start + train_len
    while t0 + pd.Timedelta(days=7) <= end:
        t1 = min(t0 + test_len, end)
        train = df[(df.index >= t0 - train_len) & (df.index < t0)]
        train_mask = (df.index >= t0 - train_len) & (df.index < t0)

        best, best_sr = None, -np.inf
        for k, p in enumerate(params_list):
            sig = cache[k] if k in cache else strategy.entries(df, train, **p)
            res = backtest(train, sig[train_mask], p['hold'], execution)
            if len(res.trades) < min_train_trades:
                continue
            sr = res.returns.mean() / res.returns.std() if res.returns.std() > 0 else 0.0
            window_sharpes[k].append(sr)
            if sr > best_sr:
                best, best_sr, best_k = p, sr, k

        test_mask = (df.index >= t0) & (df.index < t1)
        if best is not None and best_sr > 0:  # si nada funcionó en train, no operar
            sig = cache[best_k] if best_k in cache else strategy.entries(df, train, **best)
            oos_entries[test_mask] = sig[test_mask]
            oos_hold[test_mask] = best['hold']
        windows.append({'desde': t0, 'hasta': t1, 'params': best,
                        'sharpe_train_anual': best_sr * np.sqrt(BARS_PER_YEAR) if best else np.nan})
        t0 = t1

    if strategy.needs_fit:  # sin Sharpe de periodo completo: media de sus ventanas de train
        trial_sharpes = [np.mean(v) for v in window_sharpes.values() if v]

    first_test = start + train_len
    oos_df = df[df.index >= first_test]
    res = backtest(oos_df, oos_entries[df.index >= first_test], oos_hold[df.index >= first_test], execution)

    windows = pd.DataFrame(windows)
    windows['retorno_test'] = [res.returns[(res.returns.index >= w.desde) & (res.returns.index < w.hasta)].add(1).prod() - 1
                               for w in windows.itertuples()]

    return {
        'strategy': strategy,
        'result': res,
        'trial_sharpes': trial_sharpes,
        'metrics': {**metrics(res.returns, res.trades),
                    'combinaciones': len(params_list),
                    'ventanas_positivas': (windows['retorno_test'] > 0).mean()},
        'windows': windows,
        'period': (first_test, end),
    }
