# Korean market data paths on GitHub Actions — 2026-10-04

This page records the verified provider state so future maintenance does not repeat unsafe bypass attempts.

| Path | Current GitHub runner state | Classification | Required action |
|---|---|---|---|
| data.krx.co.kr via pykrx | HTTP 403, Content-Type text/html;charset=iso-8859-1 | Runner IP blocked. Downstream pykrx KeyError is a symptom, not a schema target. | Do not spoof User-Agent or retry around the block. |
| FinanceDataReader KS11 | alternative_available=False | Not a viable index fallback in current CI | Keep diagnostic-only unless a future live contract proves it works. |
| data.go.kr stock snapshot V2 | Stored credential is truncated: 64 characters vs 88 expected | Viable after credential repair | Replace DATA_GO_KR_SERVICE_KEY in GitHub Actions secrets with the complete issued key. |
| KIS Open API | KIS_APP_KEY / KIS_APP_SECRET missing | Viable read-only event/credit source once configured | Register both GitHub Actions secrets from the KIS developer portal. |

## Fail-Closed behavior

If all Korean data paths fail, Korea is returned as blocked and produces no candidates, strategy evaluation, portfolio allocation, or paper orders. The US market still runs independently. The dashboard renders Korea as DATA VALIDATION FAILED with an empty candidate list and the cause. No synthetic or stale fallback is substituted.

This behavior is covered by tests/pipeline/test_market_isolation.py and dashboard export blocked-market tests.

## Live contract readiness

tests/data/test_network_provider_contracts.py already contains a live data.go.kr contract. Once the 88-character key is restored, the scheduled network workflow immediately verifies recent closed-session snapshot retrieval, required OHLCV/market-cap columns, more than 500 rows, and more than 95% valid close values.

Network-contract failures remain failures and are never downgraded to warnings.
