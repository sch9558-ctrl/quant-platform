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

## 한국 missing-session 종목 격리 사전 설계 메모

> **설계만 확정한 상태이며 한국 격리 코드는 아직 활성화하지 않는다.**
> `DATA_GO_KR_SERVICE_KEY`의 정상 계약 검증이 먼저다. 아래 값은 누락 데이터를 허용하는 tolerance가 아니라, whole-symbol quarantine을 적용할 때 공급자 장애를 구분하기 위한 회로차단 기준이다.

### 미국과 다르게 처리해야 하는 점

1. **거래정지는 상장폐지가 아니다.** 한국 종목이 여러 세션 동안 바가 없다고 해서 마지막 관측일을 `delisting_dates`로 추론하지 않는다. 거래소의 거래정지 상태가 확인된 종목은 universe 단계에서 명시적인 `trading_halted` 사유로 제외하고, 상장폐지 날짜와 별도로 관리한다.
2. **관리종목도 데이터 누락과 구분한다.** 관리종목 여부가 확인되면 `administrative_issue`로 선행 제외한다. 이 상태를 missing-session quarantine으로 재분류해 정상 데이터 문제처럼 보이게 하지 않는다.
3. **액면분할·병합·권리락 등 기업행동을 먼저 확인한다.** 한국 시장은 가격 단절이 비교적 자주 발생하므로 corporate-action consistency 검사를 거친 뒤에야 OHLC 이상이나 missing-session 문제로 분류한다. 가격을 자동 보정하거나 누락 바를 합성하지 않는다.
4. **상장폐지·종목코드 변경은 trailing gap으로 분리한다.** 내부 한 세션 누락과 특정 시점 이후 연속 누락을 같은 '산발적 공백'으로 취급하지 않는다. 공식 상장/폐지·종목변경 정보가 확인되기 전에는 해당 종목을 투자 가능 집합에 복귀시키지 않는다.

### 한국 quarantine 회로차단선

한국에 whole-symbol quarantine을 도입하게 될 경우 `max_symbol_quarantine_fraction`은 미국의 0.20을 그대로 복사하지 않고 **0.10을 초기 설계값**으로 사용한다.

거래정지·관리종목·기업행동은 위의 명시적 상태 경로에서 먼저 제거되어야 하므로, 그 정상적인 시장 특성을 missing-session quarantine 비율에 포함시킬 이유가 없다. 그 전처리 후에도 검증 대상의 10%를 넘는 종목을 통째로 격리해야 한다면 개별 종목 문제가 아니라 공급자/캘린더/수집 경로 장애일 가능성이 높으므로 시장 전체를 Fail-Closed한다. **10%는 누락 허용률이 아니며, 누락이 있는 개별 종목은 1건이라도 canonical data에서 제외된다.**

실데이터 측정에서 이 설계가 부적절하다는 증거가 나오면 숫자를 먼저 재측정·문서화한 뒤 별도 변경한다. 키가 들어왔다는 이유만으로 임계값을 느슨하게 조정하지 않는다.

### 키 복구 직후 검증 순서

1. **계약 테스트:** `tests/data/test_network_provider_contracts.py`의 data.go.kr 실계약을 먼저 통과시켜 키 형식·응답 스키마·행 수·가격 유효성을 확인한다.
2. **단일 종목:** 현재 정상 거래 중인 한 종목에 대해 명시적 `as_of`의 OHLCV 세션 연속성, freshness, timezone, corporate-action 처리를 확인한다. 이 단계에서 합성 데이터 fallback은 사용하지 않는다.
3. **전체 유니버스:** 전체 검증 대상에서 missing-session 종목 수, internal/trailing gap, 날짜별 동시 누락 수, 거래정지·관리종목·상장폐지 상태를 사유별로 집계한다. 이 측정이 완료되기 전에는 한국 whole-symbol quarantine을 활성화하지 않는다.

순서는 **계약 테스트 → 단일 종목 → 전체 유니버스**로 고정한다. 전체 유니버스에서 다수 종목이 같은 세션을 동시에 누락하면 종목 격리로 숨기지 않고 공급자 또는 거래 캘린더 결함으로 분류해 시장 전체를 Fail-Closed한다.
