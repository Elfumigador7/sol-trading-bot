"""Métricas de rendimiento real: operaciones de entrada→salida, aciertos y veredicto."""
from datetime import date

import pytest

from performance import COST, summarize, trades, verdict


def row(day, equity, weights, prices, funding=None, account='a'):
    return {'account': account, 'day': date(2026, 10, day), 'seq': 0, 'equity': equity,
            'weights': weights, 'prices': prices, 'funding': funding or {}}


def test_trade_from_entry_to_exit_with_costs_and_funding():
    hist = [row(1, 1000, {'SOL': 1.0}, {'SOL': 100}),
            row(2, 1100, {'SOL': 1.0}, {'SOL': 110}, {'SOL': 0.001}),
            row(3, 1200, {'SOL': 0.0}, {'SOL': 120}, {'SOL': 0.001})]
    closed, still = trades(hist, {'SOL': 130})
    assert still == [] and len(closed) == 1
    assert closed[0]['ret'] == pytest.approx(0.20 - 0.002 - 2 * COST)


def test_open_trade_is_valued_at_live_price():
    closed, still = trades([row(1, 1000, {'SOL': 1.0}, {'SOL': 100})], {'SOL': 90})
    assert closed == [] and still[0]['ret'] == pytest.approx(-0.10 - 2 * COST)


def test_win_rate_and_benchmark():
    rows = [row(1, 1000, {'SOL': 1.0}, {'SOL': 100}), row(2, 1100, {}, {'SOL': 110}),
            row(3, 1100, {'SOL': 1.0}, {'SOL': 110}), row(4, 1000, {}, {'SOL': 100})]
    rows += [row(d, 1000 * p / 100, {'SOL': 1.0}, {'SOL': p}, account='buy_and_hold')
             for d, p in [(1, 100), (2, 110), (3, 110), (4, 100)]]
    m = summarize(rows, {'SOL': 100})
    assert m['a']['aciertos'] == 0.5 and len(m['a']['cerradas']) == 2
    assert m['a']['factor'] > 1  # +10 % frente a -9 %
    assert m['a']['vs_bench'] == pytest.approx(0.0)


@pytest.mark.parametrize("n, t, start", [(5, 3.0, '⏳'), (60, 2.5, '✅'), (60, 1.2, '🟡'), (60, 0.0, '⚪'), (60, -2, '🔴')])
def test_verdict(n, t, start):
    assert verdict(n, t).startswith(start)
