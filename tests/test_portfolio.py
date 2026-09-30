"""Reglas de cartera usadas en vivo por trend_engine.py."""
import numpy as np
import pandas as pd

from portfolio import btc_regime, ema_trend, equal_weight, simulate, top_momentum

IDX = pd.date_range("2026-01-01", periods=24 * 80, freq="h", tz="UTC")


def closes():
    t = np.arange(len(IDX))
    return pd.DataFrame({
        "BTC": 100 + 0.05 * t,          # sube
        "SOL": 100 + 0.20 * t,          # sube más
        "ETH": 100 + 0.10 * t,
        "DOGE": 300 - 0.10 * t,         # baja
    }, index=IDX)


def test_trend_is_long_only_above_ema():
    w = ema_trend(closes(), 20).iloc[-1]
    assert w["SOL"] == 1 and w["DOGE"] == 0


def test_top_momentum_picks_strongest_trending_coins():
    w = top_momentum(closes(), lookback_days=14, k=2, trend_days=20).iloc[-1]
    assert set(w[w > 0].index) == {"SOL", "ETH"}
    assert np.isclose(w.sum(), 1.0)


def test_btc_regime_blocks_alts_when_btc_is_down():
    c = closes()
    c["BTC"] = 200 - 0.05 * np.arange(len(IDX))  # BTC bajista
    w = btc_regime(equal_weight(ema_trend(c, 20)), c, 50).iloc[-1]
    assert w.drop("BTC").sum() == 0


def test_simulate_charges_costs_on_turnover():
    c = pd.DataFrame({"SOL": np.full(len(IDX), 100.0)}, index=IDX)
    u = {"close": c, "funding": c * 0.0}
    w = pd.DataFrame({"SOL": 1.0}, index=IDX)
    ret, turnover = simulate(u, w, start=str(IDX[0].date()))
    assert np.isclose(turnover.sum(), 1.0)      # una sola entrada
    assert ret.sum() < 0                        # con precio plano, solo quedan los costes
