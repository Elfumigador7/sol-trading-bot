import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def market():
    """Mercado sintético de 1 h con todas las columnas que usan las features (sin internet)."""
    rng = np.random.default_rng(0)
    n = 2500
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    df = pd.DataFrame({
        "open": np.r_[close[0], close[:-1]], "high": high, "low": low, "close": close,
        "volume": rng.uniform(1e5, 1e6, n), "count": rng.integers(1000, 5000, n).astype(float),
        "funding": np.where(idx.hour % 8 == 7, 1e-4, 0.0), "funding_last": 1e-4 + rng.normal(0, 2e-5, n),
        "btc_close": 60000 * np.exp(np.cumsum(rng.normal(0, 0.005, n))), "btc_volume": rng.uniform(1e3, 1e4, n),
        "eth_close": 3000 * np.exp(np.cumsum(rng.normal(0, 0.007, n))), "eth_volume": rng.uniform(1e4, 1e5, n),
        "oi": 1e7 * np.exp(np.cumsum(rng.normal(0, 0.002, n))),
        "top_ls_accounts": 1 + rng.uniform(0, 1, n), "top_ls_positions": 1 + rng.uniform(0, 1, n),
        "global_ls_accounts": 1 + rng.uniform(0, 1, n),
        "fear_greed": rng.integers(10, 90, n).astype(float), "wiki_views": rng.integers(300, 900, n).astype(float),
    }, index=idx)
    df["taker_buy_volume"] = df["volume"] * rng.uniform(0.3, 0.7, n)
    return df
