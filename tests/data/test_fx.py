import pandas as pd

from quant.data.fx import _last_close


def test_last_close_accepts_simple_close_series():
    frame = pd.DataFrame(
        {"Close": [1300.0, 1312.5]},
        index=pd.to_datetime(["2026-10-01", "2026-10-02"]),
    )
    assert _last_close(frame) == 1312.5


def test_last_close_rejects_empty_or_nonpositive_values():
    assert _last_close(pd.DataFrame()) is None
    frame = pd.DataFrame({"Close": [0.0]})
    assert _last_close(frame) is None
