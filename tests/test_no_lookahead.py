"""La garantía más importante: ninguna feature usa información posterior a su vela."""
import numpy as np
import pandas as pd
import pytest

from features_h import build_features


@pytest.mark.parametrize("t", [900, 1500, 2400])
def test_hourly_features_do_not_look_ahead(market, t):
    full = build_features(market)
    truncated = build_features(market.iloc[: t + 1])
    a, b = full.iloc[t], truncated.iloc[t]
    both_nan = a.isna() & b.isna()
    assert (np.isclose(a, b, rtol=1e-9, atol=1e-12) | both_nan).all(), a[~(np.isclose(a, b) | both_nan)]


def test_tick_features_do_not_look_ahead():
    from features import BASE_FEATURES, TIME_FEATURES, add_features
    FEATURE_COLS = BASE_FEATURES + TIME_FEATURES
    rng = np.random.default_rng(1)
    n = 400
    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=n, freq="s", tz="UTC"),
        "price": 100 + np.cumsum(rng.normal(0, 0.05, n)),
        "size": rng.uniform(0.1, 5, n),
        "side": rng.choice(["A", "B"], n),
    })
    full = add_features(df)[FEATURE_COLS]
    part = add_features(df.iloc[:300])[FEATURE_COLS]
    pd.testing.assert_series_equal(full.iloc[299], part.iloc[299])
