#!/usr/bin/env python3
"""
💰 RENDIMIENTO REAL de las cuentas paper: ¿gana dinero y se puede fiar uno de ello?

Lee trend_accounts (lo que el bot ha hecho de verdad, con costes y funding) y calcula:
  - Capital ahora: la última fila valorada con el precio actual de Hyperliquid.
  - Operaciones: cada tramo en que una cuenta tiene una moneda (peso 0 → >0 → 0). Resultado de la
    operación = variación del precio - funding pagado - comisión de entrada y salida.
  - Aciertos y factor de beneficio (ganado / perdido) de las operaciones cerradas.
  - Rentabilidad diaria: Sharpe, y t-estadístico frente a 0 y frente a buy & hold.
  - Veredicto: con t ≥ 2 hay ~95 % de confianza de que la ganancia no es suerte.

`python scripts/performance.py` imprime el detalle por cuenta (`./bot.sh rendimiento`);
report.py usa `summarize()` para la tabla del informe.
"""

import asyncio
import json
import math
import sys
from datetime import datetime, timezone

import requests

COST = 0.00045 + 0.0002     # igual que trend_engine.py: taker + slippage por lado
START_CAPITAL = 1000.0
MIN_DAYS = 30               # por debajo no se calculan Sharpe ni veredicto
BENCHMARK = 'buy_and_hold'


def live_prices() -> dict:
    try:
        mids = requests.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}, timeout=15).json()
        return {k: float(v) for k, v in mids.items() if not k.startswith('@')}
    except Exception:
        return {}


def _json(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def live_equity(last, prices: dict) -> float:
    """Capital de la última fila valorado a precios actuales (sin el funding aún no cobrado)."""
    w, px0 = _json(last['weights']), _json(last['prices'])
    pnl = sum(wt * (prices[c] / px0[c] - 1) for c, wt in w.items() if wt > 1e-9 and c in prices and c in px0)
    return float(last['equity']) * (1 + pnl)


def trades(hist: list, prices: dict) -> tuple[list, list]:
    """(cerradas, abiertas). Cada operación: {coin, entrada, salida, px_in, px_out, ret}."""
    open_, closed = {}, []
    prev_w = {}
    for row in hist:
        w, px, funding = _json(row['weights']), _json(row['prices']), _json(row['funding'])
        for c, t in open_.items():           # funding cobrado desde la fila anterior mientras se tenía
            t['funding'] += funding.get(c, 0.0)
        for c in set(w) | set(prev_w):
            was, now = prev_w.get(c, 0) > 1e-9, w.get(c, 0) > 1e-9
            if not was and now:
                open_[c] = {'coin': c, 'entrada': row['day'], 'px_in': px[c], 'funding': 0.0}
            elif was and not now and c in open_:
                t = open_.pop(c)
                t.update(salida=row['day'], px_out=px[c])
                t['ret'] = t['px_out'] / t['px_in'] - 1 - t['funding'] - 2 * COST
                closed.append(t)
        prev_w = w
    still = []
    for c, t in open_.items():
        if c in prices:
            t.update(salida=None, px_out=prices[c])
            t['ret'] = prices[c] / t['px_in'] - 1 - t['funding'] - 2 * COST  # como si cerrase ahora
            still.append(t)
    return closed, still


def daily_returns(hist: list) -> dict:
    """{día: retorno} usando el capital de la última fila de cada día (el primero contra 1.000 USD)."""
    last = {}
    for row in hist:
        last[row['day']] = float(row['equity'])
    out, prev = {}, START_CAPITAL
    for day in sorted(last):
        out[day] = last[day] / prev - 1
        prev = last[day]
    return out


def t_stat(xs: list) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return m / sd * math.sqrt(len(xs)) if sd > 0 else None


def verdict(n_days: int, t: float | None) -> str:
    if n_days < MIN_DAYS or t is None:
        return f"⏳ pocos datos ({n_days}/{MIN_DAYS} días)"
    if t >= 2:
        return "✅ rentable (95 %)"
    if t >= 1:
        return "🟡 gana, sin confirmar"
    if t > -1:
        return "⚪ ni gana ni pierde"
    return "🔴 pierde"


def days_to_confirm(sharpe: float) -> int:
    """Días que hacen falta para que un Sharpe anual dado llegue a t = 2 (lo que dice el backtest)."""
    return math.ceil(4 * 365 / sharpe ** 2)


def summarize(rows: list, prices: dict | None = None) -> dict:
    """{cuenta: métricas}. `rows`: filas de trend_accounts ordenadas por día y seq."""
    prices = live_prices() if prices is None else prices
    accounts = {}
    for r in rows:
        accounts.setdefault(r['account'], []).append(r)
    bench = daily_returns(accounts.get(BENCHMARK, []))
    bench_eq = live_equity(accounts[BENCHMARK][-1], prices) if BENCHMARK in accounts else None
    out = {}
    for name, hist in accounts.items():
        daily = daily_returns(hist)
        rets = list(daily.values())
        closed, still = trades(hist, prices)
        wins = [t['ret'] for t in closed if t['ret'] > 0]
        losses = [t['ret'] for t in closed if t['ret'] <= 0]
        eq = live_equity(hist[-1], prices)
        excess = [daily[d] - bench[d] for d in daily if d in bench]
        n = len(rets)
        sd = math.sqrt(sum((x - sum(rets) / n) ** 2 for x in rets) / (n - 1)) if n > 1 else 0
        out[name] = {
            'capital': eq,
            'retorno': eq / START_CAPITAL - 1,
            'vs_bench': (eq - bench_eq) / START_CAPITAL if bench_eq and name != BENCHMARK else None,
            'dias': n,
            'dias_verdes': sum(x > 0 for x in rets),
            'cerradas': closed,
            'abiertas': still,
            'aciertos': len(wins) / len(closed) if closed else None,
            'factor': sum(wins) / -sum(losses) if losses and sum(losses) < 0 else (math.inf if wins else None),
            'sharpe': sum(rets) / n / sd * math.sqrt(365) if n >= MIN_DAYS and sd > 0 else None,
            't': t_stat(rets),
            't_vs_bench': t_stat(excess) if name != BENCHMARK else None,
        }
        out[name]['veredicto'] = verdict(n, out[name]['t'])
    return out


def fmt_pct(x, signed=True):
    return '—' if x is None else (f"{x:+.1%}" if signed else f"{x:.0%}")


def table_lines(summary: dict) -> list:
    """Tabla markdown para el informe."""
    lines = ["| Cuenta | Capital ahora | Retorno | vs buy & hold | Días en verde | Operaciones (cerradas + abiertas) "
             "| Aciertos | Ganado/perdido | Sharpe | ¿Rentable? |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in sorted(summary.items(), key=lambda kv: -kv[1]['capital']):
        sharpe = '—' if m['sharpe'] is None else f"{m['sharpe']:.2f}"
        factor = '—' if m['factor'] is None else ('∞' if m['factor'] == math.inf else f"{m['factor']:.2f}")
        lines.append(
            f"| {name} | {m['capital']:,.2f} | {fmt_pct(m['retorno'])} | {fmt_pct(m['vs_bench'])} "
            f"| {m['dias_verdes']}/{m['dias']} | {len(m['cerradas'])} + {len(m['abiertas'])} "
            f"| {fmt_pct(m['aciertos'], False)} | {factor} | {sharpe} "
            f"| {m['veredicto']} |")
    return lines


async def main():
    import asyncpg
    import report
    conn = await asyncpg.connect(**report.DB_CONFIG)
    rows = await conn.fetch("SELECT account, day, seq, run_time, equity, weights, prices, funding "
                            "FROM trend_accounts ORDER BY account, day, seq")
    await conn.close()
    prices = live_prices()
    summary = summarize(rows, prices)
    md = [f"# 💰 Rendimiento real — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
          "Capital valorado al precio actual de Hyperliquid, con comisiones y funding ya pagados.", ""]
    md += table_lines(summary)
    md += ["", "## Operaciones por cuenta", ""]
    for name, m in sorted(summary.items()):
        closed = ', '.join(f"{t['coin']} {t['entrada']:%m-%d}→{t['salida']:%m-%d} {t['ret']:+.1%}" for t in m['cerradas'])
        still = ', '.join(f"{t['coin']} {t['ret']:+.1%}" for t in sorted(m['abiertas'], key=lambda t: -t['ret']))
        md.append(f"- **{name}** · cerradas: {closed or 'ninguna'} · abiertas: {still or 'ninguna'}")
    md.append("")
    md += ["## Cómo leerlo", "",
           "- Operación = el tiempo que una cuenta tiene una moneda, de la entrada a la salida. Las de tendencia "
           "duran semanas y ganan pocas veces pero mucho: aciertos del 30-40 % con ganado/perdido > 1,5 es normal.",
           "- Rentable de verdad = lo que importa es el capital, no los aciertos. El veredicto usa la rentabilidad "
           f"diaria (t-estadístico) y necesita al menos {MIN_DAYS} días.",
           "- vs buy & hold: si no bate a tener SOL sin más, la estrategia sirve sobre todo para reducir caídas.",
           ]
    need = [f"{acc} {days_to_confirm(sr)} días" for acc, (sr, _, _) in report.BACKTEST.items() if sr and acc != BENCHMARK]
    md.append("- Paciencia: incluso si rinde igual que en el backtest, confirmar que es rentable con 95 % de "
              "confianza lleva: " + ', '.join(need) + ". Antes de eso, lo útil es ver que no se sale de lo "
              "esperado (caídas, operaciones parecidas a las del backtest).")
    text = '\n'.join(md) + '\n'
    print(report.to_terminal(text) if '--terminal' in sys.argv else text)


if __name__ == '__main__':
    asyncio.run(main())
