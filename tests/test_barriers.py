"""Etiquetas de triple barrera: take-profit con orden límite, stop a mercado, sin futuro = sin etiqueta."""
import numpy as np

from lab import COST, MAKER_FEE
from ml import barrier_outcomes


def test_take_profit_hit_uses_maker_fee(market):
    df = market.copy()
    o = barrier_outcomes(df, horizon=12, mult=1.0)
    long = o[1]
    t = np.flatnonzero(~np.isnan(long["net"]))[0]
    e, px, fee = long["exit"][t], long["exit_px"][t], long["fee"][t]
    assert t < e <= t + 12
    assert fee in (COST, MAKER_FEE)
    funding = df["funding"].to_numpy()[t + 1:e + 1].sum()
    assert np.isclose(long["net"][t], px / df["close"].iloc[t] - 1 - COST - fee - funding)


def test_no_label_without_enough_future(market):
    o = barrier_outcomes(market, horizon=24, mult=50.0)  # barreras inalcanzables → salida por tiempo
    assert np.isnan(o[1]["net"][-5:]).all()
