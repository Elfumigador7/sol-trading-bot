#!/usr/bin/env python3
"""
🤖 Evaluar el modelo combinado con walk-forward y compararlo con los benchmarks.

Uso (desde research/):  python run_ml.py [--first-test 2023-09-01]

Prueba varias configuraciones (horizonte, ventana de entrenamiento) y umbrales. Todas cuentan
como pruebas para el Deflated Sharpe Ratio. Mismo criterio "PASA" que run_lab.py.
"""

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from data import load_full
from features_h import FEATURES_VERSION, build_features
from lab import BARS_PER_YEAR, backtest, buy_and_hold, deflated_sharpe, metrics
from ml import Setup, barrier_outcomes, sides_from_probs, simulate, walk_forward_probs
from strategies import simple_rule_entries

RESULTS_DIR = Path(__file__).parent / "results"
SETUPS = [Setup(12, 1.0, 365), Setup(24, 1.0, 365), Setup(12, 1.0, None), Setup(24, 1.0, None)]
THRESHOLDS = [0.52, 0.55, 0.58, 0.60]
RECENT_MONTHS = 6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--first-test', default='2023-09-01')
    args = parser.parse_args()
    first = pd.Timestamp(args.first_test, tz='UTC')

    print("📥 Cargando datos y features...")
    df = load_full()
    feats = build_features(df)
    print(f"   {len(df)} velas, {feats.shape[1]} features (versión {FEATURES_VERSION})")
    RESULTS_DIR.mkdir(exist_ok=True)

    oos = df.index >= first
    rows, trials, runs = [], [], {}
    for setup in SETUPS:
        cache = RESULTS_DIR / f"probs_{setup.name()}_{FEATURES_VERSION}_{df.index[-1]:%Y%m%d}.csv.gz"
        outcomes = barrier_outcomes(df, setup.horizon, setup.mult)
        if cache.exists():
            probs = pd.read_csv(cache, index_col=0, parse_dates=True)
        else:
            print(f"\n🔬 Walk-forward {setup.name()}...")
            labels = {s: np.where(np.isnan(o['net']), np.nan, (o['net'] > 0).astype(float))
                      for s, o in outcomes.items()}
            probs = walk_forward_probs(feats, labels, setup, first, log=lambda *a: None)
            probs.to_csv(cache)

        p = probs[oos]
        auc = {}
        for side, col in ((1, 'p_long'), (-1, 'p_short')):
            y = outcomes[side]['net'][oos]
            ok = ~np.isnan(y) & p[col].notna().to_numpy()
            auc[side] = roc_auc_score(y[ok] > 0, p[col].to_numpy()[ok])
        print(f"   {setup.name()}: AUC largo {auc[1]:.3f} | AUC corto {auc[-1]:.3f} (0.5 = azar)")

        for thr in THRESHOLDS:
            sides = sides_from_probs(probs, thr).where(oos, 0)
            ret, trades = simulate(df, sides, outcomes)
            ret = ret[oos]
            trials.append(ret.mean() / ret.std() if ret.std() > 0 else 0.0)
            key = f"{setup.name()}_thr{thr}"
            runs[key] = (ret, trades)
            rows.append({'config': key, 'auc_largo': auc[1], 'auc_corto': auc[-1], **metrics(ret, trades)})

    # Benchmarks en el mismo periodo
    d = df[oos]
    bh = buy_and_hold(d)
    simple = backtest(d, simple_rule_entries(d), 24)
    recent_start = d.index[-1] - pd.DateOffset(months=RECENT_MONTHS)
    bench = {'buy_and_hold': (bh, None), 'regla_simple': (simple.returns, simple.trades)}
    best_sr = max(metrics(r)['sharpe'] for r, _ in bench.values())
    best_sr_recent = max(metrics(r[r.index >= recent_start])['sharpe'] for r, _ in bench.values())

    table = pd.DataFrame(rows).set_index('config')
    for key, (ret, trades) in runs.items():
        psr, dsr = deflated_sharpe(ret, trials)
        recent = metrics(ret[ret.index >= recent_start])
        table.loc[key, 'psr'], table.loc[key, 'dsr'] = psr, dsr
        table.loc[key, 'ret_6m'], table.loc[key, 'sharpe_6m'] = recent['retorno_total'], recent['sharpe']
        table.loc[key, 'veredicto'] = ('✅ PASA' if (table.loc[key, 'retorno_total'] > 0 and table.loc[key, 'sharpe'] > best_sr
                                                     and dsr >= 0.95 and recent['retorno_total'] > 0
                                                     and recent['sharpe'] > best_sr_recent) else '❌ no')

    pd.set_option('display.width', 200)
    print(f"\n📊 FUERA DE MUESTRA {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d} "
          f"({len(trials)} configuraciones probadas)\n")
    for name, (r, t) in bench.items():
        m = metrics(r, t)
        rr = metrics(r[r.index >= recent_start])
        print(f"   [benchmark] {name:<13} retorno {m['retorno_total']:+8.1%} | Sharpe {m['sharpe']:5.2f} | "
              f"max DD {m['max_drawdown']:+.1%} | últimos 6 m {rr['retorno_total']:+.1%} (Sharpe {rr['sharpe']:.2f})")
    show = table.copy()
    for c in ('retorno_total', 'max_drawdown', 'aciertos', 'ret_6m'):
        show[c] = show[c].map(lambda v: f"{v:+.1%}" if pd.notna(v) else '—')
    show['media_por_op'] = table['media_por_op'].map(lambda v: f"{v:+.3%}" if pd.notna(v) else '—')
    for c in ('sharpe', 'sharpe_6m', 'psr', 'dsr', 'auc_largo', 'auc_corto'):
        show[c] = table[c].map(lambda v: f"{v:.2f}")
    print()
    print(show[['auc_largo', 'auc_corto', 'retorno_total', 'sharpe', 'max_drawdown', 'operaciones', 'aciertos',
                'media_por_op', 'psr', 'dsr', 'ret_6m', 'sharpe_6m', 'veredicto']].to_string())

    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    table.to_csv(RESULTS_DIR / f"ml_resumen_{stamp}.csv")
    best = table['sharpe'].idxmax()
    runs[best][1].to_csv(RESULTS_DIR / f"ml_trades_{best}_{stamp}.csv", index=False)
    t = runs[best][1]
    t['año'] = t['entry_time'].dt.year
    print(f"\n🔎 Mejor configuración: {best}")
    print(t.groupby('side')['net_return'].agg(ops='count', media='mean', total='sum').round(4).to_string())
    print(t.groupby('año')['net_return'].agg(ops='count', media='mean', total='sum').round(4).to_string())
    print(f"\n💾 Resultados en {RESULTS_DIR}/ml_*_{stamp}.csv")


if __name__ == '__main__':
    main()
