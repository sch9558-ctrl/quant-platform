import pandas as pd

from quant.macro.cross_asset import fetch_cross_asset_snapshot
from quant.pipeline.institutional_overlay import evaluate_candidate


def _download(*args, **kwargs):
    idx=pd.to_datetime(["2026-10-01","2026-10-02"])
    data={
        ("KRW=X","Close"):[1400.0,1414.0],
        ("^SOX","Close"):[5000.0,4850.0],
        ("^VIX","Close"):[24.0,27.0],
        ("^TNX","Close"):[40.0,41.6],
    }
    return pd.DataFrame(data,index=idx)


def test_cross_asset_snapshot_computes_required_market_inputs():
    snap=fetch_cross_asset_snapshot("2026-10-02",downloader=_download)
    assert snap.korea_complete and snap.us_complete
    assert round(snap.usdkrw_1d_pct,6)==1.0
    assert round(snap.sox_1d_pct,6)==-3.0
    assert snap.vix==27.0
    assert round(snap.us10y_change_bp,6)==16.0


def test_overlay_fails_closed_when_macro_snapshot_is_missing():
    c={"market":"us","price":100,"volatility":.2,"composite_score":.9,"trade_plan":{"target_1":115}}
    out=evaluate_candidate(
        c,filings=[],as_of="2026-10-04",
        open_price=100,previous_close=100,
        macro_data_available=False,market_data_available=True,
        adv_notional=1e9,order_notional=1e6,
    )
    assert not out.approved
    assert "MACRO_DATA_UNAVAILABLE" in out.reasons


def test_overlay_blocks_vix_and_gap_down_risks():
    c={"market":"us","price":100,"volatility":.2,"composite_score":.9,"trade_plan":{"target_1":115}}
    out=evaluate_candidate(
        c,filings=[],as_of="2026-10-04",
        open_price=95,previous_close=100,
        vix=30,us10y_change_bp=5,
        macro_data_available=True,market_data_available=True,
        adv_notional=1e9,order_notional=1e6,
    )
    assert not out.approved
    assert "VIX_ABOVE_25" in out.reasons
    assert "GAP_DOWN_HOLD" in out.reasons
