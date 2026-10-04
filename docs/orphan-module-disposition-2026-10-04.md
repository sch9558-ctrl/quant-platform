# Orphan module disposition — 2026-10-04

The platform's priority order is data correctness, completeness, calculation
correctness, backtest reliability, reproducibility, overfitting prevention,
verifiability, long pre-validation, Fail-Closed architecture, then automation.

An existing module is **not** production functionality until a production
caller supplies validated point-in-time inputs and its output participates in
an auditable decision path. This document prevents "file exists" from being
reported as "feature delivered".

| Module | Decision | Production condition / rationale |
|---|---|---|
| `analytics/attribution.py` | **B — hold** | Needs realized portfolio + benchmark return history and stable sector classifications. Attribution is reporting, not an entry gate. |
| `analytics/consensus_acceleration.py` | **B — hold** | Needs timestamped point-in-time analyst estimate history. A current consensus snapshot cannot support first/second differences without look-ahead risk. |
| `analytics/index_rebalancing.py` | **B — hold** | Needs an official point-in-time index announcement/rebalance feed and membership history. |
| `analytics/institutional_flow.py` | **B — hold** | Needs a validated KRX per-symbol investor-flow feed. Do not infer foreign/institutional flow from price/volume. |
| `analytics/pairs_trading.py` | **B — hold** | Needs pair-universe construction, point-in-time membership, and independent cointegration/stationarity validation before strategy registration. |
| `analytics/supply_chain.py` | **B — hold** | Needs a curated, dated supplier/customer graph. A static hand-built graph would introduce survivorship/look-ahead bias. |
| `decision/agent_committee.py` | **B — hold** | Must consume a calibrated feature contract and can never override hard Fail-Closed gates. Current hard gates remain authoritative. |
| `execution/broker_gateway.py` | **B — hold** | Live trading remains disabled. Only consider mock/manual-review integration after order reconciliation and broker credentials are separately validated. |
| `nlp/report_sentiment.py` | **B — hold** | Needs complete licensed/public report text coverage and an accuracy benchmark. The lexical scorer alone is not sufficient evidence for production decisions. |
| `notification/telegram_alert.py` | **B — hold** | Needs explicit notification routing/secrets and should only emit already-approved manual-review states; it must not become a trading authority. |
| `nowcasting/customs_tracker.py` | **B — hold** | Needs an official point-in-time customs/K-Stat feed plus dated HS-to-company mapping. |
| `residual_alpha.py` | **B — hold** | Needs validated point-in-time factor returns (US and Korea-specific where applicable) before residual alpha can be trusted. |
| `risk_guard.py` | **A — wired** | Production caller exists in `pipeline/research_pipeline.py`: portfolio VaR, NAV drawdown state, hard kill-switch candidate removal, entry R/R and ATR trailing reference. Missing NAV/returns fails closed. |
| `signal/wavelet_filter.py` | **B — hold** | Must never alter canonical raw prices. Only wire after a strategy-specific study proves denoising improves OOS behavior without leakage. |
| `tax_optimizer.py` | **B — hold** | Needs private tax-lot/cost-basis records, FX basis and jurisdiction/account rules. Do not infer these inputs. |
| `trading/exit_engine.py` | **B — hold / consolidation candidate** | Trailing-stop authority already lives in RiskGuard. Time-stop policy must be reconciled into one risk authority before this module can be called. |
| `trading/paper_trader.py` | **B — hold / consolidation candidate** | Production already has KoreaPaperBroker/USPaperBroker. A second ledger would create conflicting NAV/trade histories until a migration/reconciliation plan exists. |
| `volatility_targeting.py` | **B — hold** | Needs an explicit portfolio target-vol policy, calibrated horizon and interaction tests with BL/HRP, cash floor and RiskGuard. |

## Rules for future promotion from B to A

1. A point-in-time data source and provenance record must exist.
2. Missing required evidence must fail closed.
3. Deterministic fixture tests and, where external contracts are involved,
   scheduled live contract tests must both exist.
4. The production caller and dashboard/export contract must be traceable.
5. No module may override Data Quality, strategy approval, filing/event,
   portfolio RiskGuard, or manual-review gates.

No module is classified C today because deleting a tested research primitive
without a dedicated migration/deprecation change would violate the current
"do not delete or weaken tests" constraint. Duplicate authorities
(`exit_engine`, `paper_trader`) are explicitly held for later consolidation
rather than silently removed.
