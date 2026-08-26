import pytest

from quant.backtest.costs import CostModel


def test_korea_sell_kospi_includes_tax():
    model = CostModel("korea")
    buy = model.apply(10_000_000, is_sell=False, asset_type="equity", exchange="KOSPI")
    sell = model.apply(10_000_000, is_sell=True, asset_type="equity", exchange="KOSPI")
    assert buy.tax_or_fee == 0
    assert sell.tax_or_fee > 0
    assert sell.total_cost > buy.total_cost


def test_korea_etf_sell_has_no_tax():
    model = CostModel("korea")
    sell = model.apply(10_000_000, is_sell=True, asset_type="etf", exchange="KOSPI")
    assert sell.tax_or_fee == 0


def test_korea_kosdaq_vs_kospi_same_tax_rate_currently():
    model = CostModel("korea")
    kospi_sell = model.apply(1_000_000, True, "equity", "KOSPI")
    kosdaq_sell = model.apply(1_000_000, True, "equity", "KOSDAQ")
    assert kospi_sell.tax_or_fee == pytest.approx(kosdaq_sell.tax_or_fee)


def test_us_buy_has_no_sec_fee():
    model = CostModel("us")
    buy = model.apply(5000, is_sell=False)
    assert buy.tax_or_fee == 0


def test_us_sell_has_sec_fee():
    model = CostModel("us")
    sell = model.apply(5000, is_sell=True)
    assert sell.tax_or_fee > 0


def test_fill_total_cost_bps_positive():
    model = CostModel("korea")
    fill = model.apply(1_000_000, True, "equity", "KOSPI")
    assert fill.total_cost_bps > 0


def test_estimate_round_trip_cost_bps_reasonable():
    kr = CostModel("korea").estimate_round_trip_cost_bps("equity", "KOSPI")
    us = CostModel("us").estimate_round_trip_cost_bps("equity")
    assert 0 < kr < 100  # sanity: round trip should be well under 1%
    assert 0 < us < 20


def test_us_per_share_cost_uses_share_count():
    model = CostModel("us")
    fill = model.apply_us_per_share(shares=100, price=50, is_sell=True)
    assert fill.notional == pytest.approx(5000)
    assert fill.tax_or_fee > 0
