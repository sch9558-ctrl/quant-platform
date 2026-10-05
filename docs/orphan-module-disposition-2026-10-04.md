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
| `volatility_targeting.py` | **A — wired** | `run_paper.py` consumes persistent paper NAV history and applies the 12% EWMA target only after 20 return observations. `max_scale=1.0` means the overlay can only reduce risky weights; base PortfolioConstructor/RiskManager remain authoritative. |

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



## Shared prerequisites and unlock order

The hold list is not a flat backlog. The remaining orphan/research modules
cluster around three shared prerequisites:

| Priority | Shared prerequisite | Difficulty | Modules unlocked | Count | Status |
|---|---|---:|---|---:|---|
| **1** | **Point-in-time external observation archive** with publication timestamps, provenance, revision preservation and as-of queries | 4/5 | attribution, consensus_acceleration, index_rebalancing, institutional_flow, supply_chain, report_sentiment, customs_tracker, residual_alpha | **8** | **Completed foundation** in the existing ResearchDB; immutable revisions and as-of queries are enforced |
| **2** | **Persistent position/execution state**: entry session, highest-high-since-entry, tax lots/cost basis, marked NAV, manual-review/order lifecycle | 3/5 | exit_engine production time-stop, tax_optimizer, volatility_targeting, broker_gateway, telegram_alert | **5** | **Started and production-backed**: broker remains authoritative; ResearchDB stores immutable fills and session snapshots. `volatility_targeting` is now wired. Highest-high/tax-lot/manual-review lifecycle remain outstanding. |
| **3** | **Research-to-production promotion protocol** using existing Walk-Forward -> DSR/CPCV gates and an explicit strategy registration contract | 3/5 | pairs_trading, wavelet_filter, agent_committee | **3** | Not started |

Priority 1 ranks first despite the higher implementation difficulty because one
causality-safe store unlocks eight modules and eliminates the largest repeated
source of look-ahead risk: reconstructing historical decisions from current
snapshots.

### Priority 1 implementation plan — point-in-time observations

**Storage location:** extend the existing SQLite ResearchDB; do not create a
parallel database or a new module.

**Schema (implemented):**
- observation_id
- observation_type
- source
- market
- symbol (nullable)
- published_at — the historical visibility gate
- collected_at — ingestion/provenance timestamp
- effective_at — optional event/effective timestamp; may legitimately be in the future
- payload_json
- provenance_json

**Fail-Closed rule:** historical consumers must query through
`latest_observation_as_of` / `query_observations_as_of`. An observation with
`published_at > as_of` is invisible even if it exists in the local database.
Missing observations remain missing; callers must not substitute a current
snapshot.

**Initial source sequence:**
1. Existing analyst/report ingestion -> timestamped report/consensus observations.
2. Official index announcements/membership snapshots.
3. Validated KRX investor-flow observations.
4. Official customs/K-Stat releases with release timestamp.
5. Versioned factor returns for residual-alpha research.

Every external source requires both deterministic fixture tests and a scheduled
live contract test before its observations can influence production decisions.

## Duplicate-authority consolidation

### exit_engine

**Decision: B — compatibility adapter, independent authority removed.**

RiskGuard now owns both trailing-stop and time-stop decisions. ExitEngine
delegates to RiskGuard and only preserves the legacy research-facing response
shape. Production time-stop activation still waits for prerequisite 2 because
the production broker must persist entry session and highest-high-since-entry.

### paper_trader

**Decision: B — compatibility facade, independent ledger removed.**

PaperTrader no longer owns cash, positions, fills or NAV. It delegates to
KoreaPaperBroker/USPaperBroker, the same ledger family used by production
RiskGuard. Independent commission/slippage/tax overrides are rejected because
the shared CostModel is authoritative. This removes the duplicate-account
reason for deferral; remaining production promotion depends only on the manual
review/order lifecycle under prerequisite 2.


### Priority 2 implementation status — persistent paper state

The operational authority remains `KoreaPaperBroker` / `USPaperBroker` and
their existing state file. ResearchDB is an append-only audit/validation
projection, not a third trading ledger.

Persisted records:
- immutable fills with explicit market session and actual fill timestamp;
- account snapshots with session, cash, NAV, peak NAV and loss streak;
- position snapshots with symbol, quantity, average cost and entry session.

Historical queries are session bounded. `latest_paper_state_as_of`,
`paper_nav_history` and `paper_fills_as_of` never include later sessions.

The first module unlocked is `volatility_targeting.py`. `run_paper.py`
uses persistent NAV only when at least 20 return observations exist. The
overlay cannot lever up because `max_scale=1.0`; it can only reduce risky
target weights. When history is insufficient it records that the overlay was
not applied instead of fabricating volatility.

Still blocked under prerequisite 2:
- production time-stop needs persistent highest-high-since-entry / mark history;
- tax optimizer needs tax lots, FX basis and jurisdiction/account rules;
- broker gateway remains blocked by the permanent live-trading lock;
- Telegram needs explicit notification routing and may only surface existing
  manual-review states.
