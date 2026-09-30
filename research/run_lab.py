#!/usr/bin/env python3
"""
🧪 Ejecutar el laboratorio: todas las estrategias en walk-forward vs benchmarks.

Uso (desde research/):
    python run_lab.py                          # Binance 2023 → hoy
    python run_lab.py --source hyperliquid     # validar en el mercado del bot (~7 meses)
    python run_lab.py --start 2024-06 --train-days 60 --test-days 14
    python run_lab.py --execution maker        # órdenes límite (comisión maker, puede no llenarse)
    python run_lab.py --execution maker --entry-offset 0.001   # límite 0,1 % mejor que el cierre

Veredicto por estrategia: "PASA" solo si fuera de muestra y con costes
  1) gana dinero, 2) bate en Sharpe a buy & hold y a la regla simple,
  3) DSR ≥ 0.95 (no se explica por haber probado muchas combinaciones) y
  4) también gana en los últimos 6 meses (sigue funcionando ahora).
"""

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from data import load_dataset
from lab import MAKER, TAKER, Execution, backtest, buy_and_hold, deflated_sharpe, metrics, walk_forward
from strategies import STRATEGIES, simple_rule_entries

RESULTS_DIR = Path(__file__).parent / "results"
RECENT_MONTHS = 6


def fmt(m: dict) -> dict:
    pct = lambda v: f"{v:+.1%}" if pd.notna(v) else "—"
    return {
        'retorno': pct(m['retorno_total']),
        'sharpe': f"{m['sharpe']:.2f}",
        'max_dd': pct(m['max_drawdown']),
        'ops': m.get('operaciones', '—'),
        'aciertos': f"{m['aciertos']:.0%}" if pd.notna(m.get('aciertos', float('nan'))) else '—',
        'media/op': f"{m['media_por_op']:+.3%}" if pd.notna(m.get('media_por_op', float('nan'))) else '—',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='binance', choices=['binance', 'hyperliquid'])
    parser.add_argument('--start', default='2023-01')
    parser.add_argument('--train-days', type=int, default=90)
    parser.add_argument('--test-days', type=int, default=30)
    parser.add_argument('--execution', default='taker', choices=['taker', 'maker'])
    parser.add_argument('--entry-offset', type=float, default=0.0,
                        help='maker: distancia del límite al cierre a nuestro favor (0.001 = 0,1 %%)')
    parser.add_argument('--entry-wait', type=int, default=2, help='maker: velas que espera la orden de entrada')
    args = parser.parse_args()
    execution = (TAKER if args.execution == 'taker'
                 else Execution('maker', args.entry_offset, args.entry_wait, MAKER.exit_wait))

    print(f"📥 Cargando datos ({args.source} desde {args.start})...")
    df = load_dataset(args.source, args.start)
    print(f"   {len(df)} velas de 1 h: {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}\n")

    runs = []
    for s in STRATEGIES:
        if any(c not in df.columns for c in s.requires):
            print(f"⏭️  {s.name}: faltan columnas {s.requires} en {args.source}")
            continue
        print(f"🔬 {s.name} ({len(s.param_sets())} combinaciones)...")
        runs.append(walk_forward(df, s, args.train_days, args.test_days, execution=execution))

    # DSR con TODAS las configuraciones probadas en el estudio (más pruebas = más exigente)
    all_trials = [sr for run in runs for sr in run['trial_sharpes']]
    for run in runs:
        run['metrics']['psr'], run['metrics']['dsr'] = deflated_sharpe(run['result'].returns, all_trials)
    print(f"\n🎲 Configuraciones probadas en total: {len(all_trials)}")

    first, end = runs[0]['period']
    oos = df[df.index >= first]
    recent_start = end - pd.DateOffset(months=RECENT_MONTHS)

    bh = buy_and_hold(oos)
    simple = backtest(oos, simple_rule_entries(oos), 24)
    bench = {
        'buy_and_hold': metrics(bh),
        'regla_simple': metrics(simple.returns, simple.trades),
    }
    bench_recent = {
        'buy_and_hold': metrics(bh[bh.index >= recent_start]),
        'regla_simple': metrics(simple.returns[simple.returns.index >= recent_start],
                                simple.trades[simple.trades['entry_time'] >= recent_start]),
    }
    best_bench_sr = max(b['sharpe'] for b in bench.values())
    best_bench_recent_sr = max(b['sharpe'] for b in bench_recent.values())

    rows, rows_recent = [], []
    for name, m in bench.items():
        rows.append({'estrategia': f"[benchmark] {name}", **fmt(m), 'llenado': '—', 'psr': '—', 'dsr': '—',
                     'ventanas+': '—', 'veredicto': ''})
    for run in runs:
        m = run['metrics']
        ret = run['result'].returns
        tr = run['result'].trades
        recent = metrics(ret[ret.index >= recent_start], tr[tr['entry_time'] >= recent_start])
        passes = (m['retorno_total'] > 0 and m['sharpe'] > best_bench_sr and m['dsr'] >= 0.95
                  and recent['retorno_total'] > 0 and recent['sharpe'] > best_bench_recent_sr)
        missed = tr.attrs.get('missed', 0)
        fill = f"{len(tr) / (len(tr) + missed):.0%}" if len(tr) + missed else '—'
        rows.append({'estrategia': run['strategy'].name, **fmt(m), 'llenado': fill, 'psr': f"{m['psr']:.2f}",
                     'dsr': f"{m['dsr']:.2f}", 'ventanas+': f"{m['ventanas_positivas']:.0%}",
                     'veredicto': '✅ PASA' if passes else '❌ no'})
        rows_recent.append({'estrategia': run['strategy'].name, **fmt(recent)})
    for name, m in bench_recent.items():
        rows_recent.insert(0, {'estrategia': f"[benchmark] {name}", **fmt(m)})

    table = pd.DataFrame(rows).set_index('estrategia')
    table_recent = pd.DataFrame(rows_recent).set_index('estrategia')

    print(f"\n📊 FUERA DE MUESTRA {first:%Y-%m-%d} → {end:%Y-%m-%d} "
          f"(walk-forward {args.train_days}d/{args.test_days}d)\n   Ejecución: {execution.label()} + funding\n")
    print(table.to_string())
    print(f"\n📅 ÚLTIMOS {RECENT_MONTHS} MESES ({recent_start:%Y-%m-%d} → {end:%Y-%m-%d})\n")
    print(table_recent.to_string())

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = f"{args.source}_{args.execution}_{datetime.now():%Y%m%d_%H%M}"
    table.to_csv(RESULTS_DIR / f"resumen_{stamp}.csv")
    table_recent.to_csv(RESULTS_DIR / f"resumen_recientes_{stamp}.csv")
    for run in runs:
        run['result'].trades.to_csv(RESULTS_DIR / f"trades_{run['strategy'].name}_{stamp}.csv", index=False)
        run['windows'].to_csv(RESULTS_DIR / f"ventanas_{run['strategy'].name}_{stamp}.csv", index=False)
    print(f"\n💾 Resultados en {RESULTS_DIR}/ (*_{stamp}.csv)")


if __name__ == '__main__':
    main()
