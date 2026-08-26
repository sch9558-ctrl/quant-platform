# Architecture

## Design goal

This is **not** an auto-trading bot. It is a research pipeline whose job is to
answer, every day, "which strategies and which names are currently the most
promising candidates, and how much should I trust that judgment" — and to
prefer answers that are *reproducible and likely to survive out-of-sample*
over answers that simply maximize a backtested return number.

## Pipeline (also see `src/quant/pipeline/research_pipeline.py`)

```
Market Data (data/)
  -> Universe Engine (universe/)
  -> Feature Engine (features/)
  -> Market Regime Detection (regime/)
  -> Market Screening (scanner/)
  -> Strategy Library (strategy/)
  -> Backtesting (backtest/)
  -> Performance Analytics (analytics/)
  -> Train/Validation/OOS + Walk-Forward (validation/)
  -> Strategy Ranking + Overfitting + Monte Carlo (ranking/)
  -> Portfolio Construction (portfolio/)
  -> Risk Analysis (risk/)
  -> Research Database (research_db/) -- every experiment persisted here
  -> Daily Research Report (report/)
  -> Paper Trading (broker/)
  -> [future] Live Trading (broker/*_live.py, disabled by construction)
```

`run_research.py` runs this whole chain end to end for both markets.

## Package layout

```
src/quant/
  config.py          # loads config/*.yaml, env vars, hardcodes LIVE_TRADING=False
  data/               # MarketDataProvider interface + KR (pykrx) / US (yfinance) impls
                      # + local parquet/sqlite cache (store.py) + data quality checks
  universe/           # Universe construction rules per market, config-driven
  features/           # Price/Trend/Momentum/Volatility/Volume/MeanReversion/Fundamental
  regime/             # Bull/Bear/Sideways/HighVol/LowVol/RiskOn/RiskOff classifier
  scanner/            # Screening filters + daily candidate scanner with reasons
  strategy/           # BaseStrategy interface + concrete strategy modules
  backtest/           # Event-driven-ish vectorized backtester with realistic costs
  analytics/          # Performance metrics, benchmark comparison, plots
  validation/         # IS/Validation/OOS split, walk-forward analysis, param stability
  ranking/            # Composite Quant Strategy Score, overfitting detection, Monte Carlo
  portfolio/          # Weighting schemes + constraints
  risk/               # Pre-trade Risk Manager (position/exposure/drawdown/vol limits)
  research_db/        # SQLite experiment database (reproducibility metadata)
  report/             # Daily research report generator (Markdown + HTML)
  broker/             # BrokerInterface + KoreaPaperBroker/USPaperBroker (+ live stubs)
  pipeline/           # Orchestrates the full chain
  utils/              # logging, trading calendar, misc helpers
```

`tests/` mirrors this layout one-to-one.

## Data source defaults (no API key required)

- **Korea**: [`pykrx`](https://github.com/sharebook-kr/pykrx) scrapes KRX's
  public data endpoints for OHLCV, market cap, and fundamental
  (PER/PBR/EPS/dividend yield) tables for KOSPI/KOSDAQ, plus ETF price data.
- **US**: [`yfinance`](https://github.com/ranaroussi/yfinance) for OHLCV,
  corporate actions (splits/dividends) and basic fundamentals. Universe
  constituents (S&P 500 / NASDAQ-100) are fetched dynamically from public
  reference tables (e.g. Wikipedia) at run time and cached locally — **no
  ticker list is hardcoded in source code.** A broader "all listed" universe
  can be layered on later via an exchange listing endpoint.

Both providers sit behind a `MarketDataProvider` abstract interface
(`src/quant/data/base.py`), so a paid data vendor can be swapped in later
without touching anything downstream.

> **Sandbox network note:** the cloud workspace this was built in only has
> egress to package registries (pypi), not to KRX/Yahoo/Wikipedia. The data
> layer is fully implemented and unit-tested against synthetic fixtures, but
> live fetches must be exercised from an environment with normal internet
> access (your own machine, a VPS, or a connected desktop folder). See
> `README.md` -> "Running with real data".

## Reproducibility

Every backtest run persisted to the Research DB stores: code version (git
commit hash if available), a dataset version hash, the exact parameter set,
the universe definition, the date range, transaction cost assumptions, and
all computed metrics — so any past result can be located and re-run.

## Safety

`LIVE_TRADING` is `False` both in `.env.example` and hardcoded as a default
in `src/quant/config.py`. `src/quant/broker/kr_live.py` and `us_live.py` are
interface-only stubs that raise `NotImplementedError` on every order method.
No code path in this repository can place a real order.
