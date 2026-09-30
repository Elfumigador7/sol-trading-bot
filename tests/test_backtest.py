"""Costes, órdenes límite y corrección por suerte del motor de backtest."""
import numpy as np
import pandas as pd

from lab import COST, MAKER, MAKER_FEE, backtest, deflated_sharpe

IDX = pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC")


def frame(close, low=None, high=None, funding=0.0):
    close = np.asarray(close, float)
    return pd.DataFrame({"close": close, "low": close - 1 if low is None else low,
                         "high": close + 1 if high is None else high, "funding": funding}, index=IDX)


def entry_at_zero(side=1):
    e = pd.Series(0, index=IDX)
    e.iloc[0] = side
    return e


def test_taker_round_trip_on_flat_price_costs_two_fees():
    res = backtest(frame([100] * 10), entry_at_zero(), hold=3)
    assert len(res.trades) == 1
    assert np.isclose(res.trades.net_return.iloc[0], -2 * COST)


def test_short_profits_when_price_falls():
    res = backtest(frame(np.linspace(100, 91, 10)), entry_at_zero(-1), hold=3)
    assert res.trades.net_return.iloc[0] > 0


def test_long_pays_positive_funding():
    no_fund = backtest(frame([100] * 10), entry_at_zero(), hold=3).trades.net_return.iloc[0]
    with_fund = backtest(frame([100] * 10, funding=1e-4), entry_at_zero(), hold=3).trades.net_return.iloc[0]
    assert np.isclose(no_fund - with_fund, 3e-4)


def test_maker_order_is_missed_when_price_never_trades_through():
    c = np.arange(100, 110, 1.0)
    res = backtest(frame(c, low=c, high=c + 0.5), entry_at_zero(), 3, MAKER)
    assert len(res.trades) == 0 and res.trades.attrs["missed"] == 1


def test_maker_fill_and_limit_exit():
    c = np.array([100, 99.5, 101, 102, 103, 104, 104, 104, 104, 104.0])
    t = backtest(frame(c), entry_at_zero(), 3, MAKER).trades.iloc[0]
    assert t.entry == 100 and t.exit == 103
    assert np.isclose(t.net_return, 103 / 100 - 1 - 2 * MAKER_FEE)


def test_maker_exit_falls_back_to_market_order():
    c = np.array([100, 99.5, 101, 102, 103, 102, 101, 100, 100, 100.0])
    t = backtest(frame(c, high=np.minimum(c + 1, 103)), entry_at_zero(), 3, MAKER).trades.iloc[0]
    assert np.isclose(t.net_return, 102 / 100 - 1 - MAKER_FEE - COST)


def test_more_trials_make_deflated_sharpe_stricter():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0005, 0.01, 2000))
    few = deflated_sharpe(returns, list(rng.normal(0, 0.01, 5)))[1]
    many = deflated_sharpe(returns, list(rng.normal(0, 0.01, 500)))[1]
    assert many < few
