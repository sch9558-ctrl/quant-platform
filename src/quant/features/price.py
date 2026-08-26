"""Price-return features (spec section 5, "Price Features").

Every function here is a pure, causal transform of a single price series:
value at row t is computed only from rows <= t. This is what makes them safe
to use directly as backtest signals without look-ahead -- see
tests/features/test_no_lookahead.py which asserts this property mechanically
for every feature in this package.
"""
from __future__ import annotations

import pandas as pd

DEFAULT_RETURN_WINDOWS = (1, 5, 20, 60, 120, 252)


def simple_returns(close: pd.Series, windows: tuple[int, ...] = DEFAULT_RETURN_WINDOWS) -> pd.DataFrame:
    out = {}
    for w in windows:
        out[f"ret_{w}d"] = close.pct_change(w)
    return pd.DataFrame(out, index=close.index)


def log_returns(close: pd.Series, windows: tuple[int, ...] = DEFAULT_RETURN_WINDOWS) -> pd.DataFrame:
    import numpy as np
    log_close = pd.Series(np.log(close), index=close.index)
    out = {}
    for w in windows:
        out[f"logret_{w}d"] = log_close - log_close.shift(w)
    return pd.DataFrame(out, index=close.index)


def daily_return(close: pd.Series) -> pd.Series:
    return close.pct_change().rename("daily_return")
