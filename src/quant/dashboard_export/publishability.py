"""Whether a dashboard payload is fit to publish as production research.

This module exists because of a specific failure, and the failure is worth
stating plainly so nobody re-introduces it:

The published dashboard showed `generated_at: 2026-08-26` next to
`as_of: 2022-06-01`, with candidate tickers like `KETF0061` and a headline
status of DATA INTEGRITY **PASS**. Every individual component was working
as designed. The data-quality engine really had passed every mandatory
check -- against a synthetic dataset generated four years before the
displayed generation date. Nothing in the system was responsible for
asking the question a human asks in one second: *does this payload
describe today's market at all?*

Two independent holes made that possible:

1. **Synthetic data was indistinguishable from real data downstream.**
   `build_dashboard_data()` took a `demo` flag and spent it on a
   human-readable provenance string. No machine-readable marker reached
   the payload, so no check could refuse it and no test could catch it.

2. **Nothing compared `as_of` against the calendar.** Freshness was
   validated *within* the fetched dataset (are there gaps? is the last bar
   recent relative to the requested window?) but never against "what is
   the latest session the exchange has actually completed by now".

So this module answers exactly two questions, and `write_dashboard_json`
refuses to write a production payload that fails either:

- Is this real market data?
- Does it describe the most recent completed trading session?

Fail-Closed applies here the same way it does to candidate generation:
publishing nothing, or publishing an explicit DATA UNAVAILABLE state, is
strictly better than publishing stale or synthetic numbers under a fresh
timestamp. A dashboard that is honestly empty costs a morning; a
dashboard that is confidently wrong costs trust in every number on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant.utils.calendar import latest_closed_session, trading_days
from quant.utils.logging import get_logger

logger = get_logger(__name__)

#: Payload marker for how the data was produced. Anything other than
#: "real" is refused for production publication.
REAL = "real"
SYNTHETIC = "synthetic"

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"


class NotPublishableError(RuntimeError):
    """Raised instead of writing a production payload that is synthetic or
    stale. Carries the per-market detail so the caller can render an
    honest failure state rather than a generic error."""

    def __init__(self, message: str, report: "PublishabilityReport"):
        super().__init__(message)
        self.report = report


@dataclass
class MarketFreshness:
    market: str
    expected_session: str | None
    actual_session: str | None
    gap_sessions: int | None
    status: str

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "expected_session": self.expected_session,
            "actual_session": self.actual_session,
            "gap_sessions": self.gap_sessions,
            "status": self.status,
        }


@dataclass
class PublishabilityReport:
    data_source_mode: str
    markets: dict[str, MarketFreshness] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_real(self) -> bool:
        return self.data_source_mode == REAL

    @property
    def all_fresh(self) -> bool:
        return bool(self.markets) and all(m.status == FRESH for m in self.markets.values())

    @property
    def publishable(self) -> bool:
        return self.is_real and self.all_fresh

    def to_dict(self) -> dict:
        return {
            "data_source_mode": self.data_source_mode,
            "publishable": self.publishable,
            "markets": {m: f.to_dict() for m, f in self.markets.items()},
            "reasons": list(self.reasons),
        }


def _gap_sessions(market: str, actual: pd.Timestamp, expected: pd.Timestamp) -> int:
    """How many completed sessions the data is behind, counted on the
    exchange's own calendar -- not in calendar days. A Monday payload
    holding Friday's bar is one session stale, not three days stale, and a
    payload spanning a holiday week must not be punished for the holiday."""
    if actual >= expected:
        return 0
    sessions = trading_days(actual.strftime("%Y-%m-%d"), expected.strftime("%Y-%m-%d"), market)
    # `sessions` includes both endpoints; the gap is the number of sessions
    # completed after `actual`.
    return max(0, len(sessions) - 1)


def assess_market_freshness(
    market: str, actual_session: str | None, now: pd.Timestamp | str | None = None,
) -> MarketFreshness:
    if actual_session is None:
        return MarketFreshness(market, None, None, None, UNKNOWN)
    try:
        expected = latest_closed_session(market, now=now)
    except Exception as e:  # noqa: BLE001 -- a calendar failure must not read as "fresh"
        logger.warning("Could not determine expected session for %s: %s", market, e)
        return MarketFreshness(market, None, str(actual_session), None, UNKNOWN)

    actual = pd.Timestamp(actual_session).normalize()
    expected = pd.Timestamp(expected).normalize()
    gap = _gap_sessions(market, actual, expected)
    # A payload dated *ahead* of the latest completed session is not
    # "extra fresh" -- it means something is wrong with the clock, the
    # calendar, or the as_of that was requested. Treat it as unknown
    # rather than silently passing.
    if actual > expected:
        status = UNKNOWN
    else:
        status = FRESH if gap == 0 else STALE
    return MarketFreshness(
        market=market,
        expected_session=expected.strftime("%Y-%m-%d"),
        actual_session=actual.strftime("%Y-%m-%d"),
        gap_sessions=gap,
        status=status,
    )


def assess(
    data_source_mode: str,
    market_sessions: dict[str, str | None],
    now: pd.Timestamp | str | None = None,
) -> PublishabilityReport:
    """Build the publishability verdict for a payload.

    `market_sessions` maps market -> the latest session the payload
    actually describes (normally its `as_of`).
    """
    report = PublishabilityReport(data_source_mode=data_source_mode)
    for market, session in market_sessions.items():
        report.markets[market] = assess_market_freshness(market, session, now=now)

    if not report.is_real:
        report.reasons.append(
            "합성(테스트용) 데이터로 생성된 결과입니다. 실제 시장 데이터가 아니므로 "
            "운영 대시보드에 게시하지 않습니다."
        )
    for market, fresh in report.markets.items():
        label = {"korea": "국내시장", "us": "미국시장"}.get(market, market)
        if fresh.status == STALE:
            report.reasons.append(
                f"{label} 데이터가 최신 거래일까지 갱신되지 않았습니다. "
                f"예상 최신 거래일: {fresh.expected_session} / "
                f"실제 최신 거래일: {fresh.actual_session} / 차이: {fresh.gap_sessions}거래일"
            )
        elif fresh.status == UNKNOWN:
            report.reasons.append(
                f"{label}의 최신 거래일을 확인할 수 없습니다 "
                f"(실제 최신 거래일: {fresh.actual_session or '없음'})."
            )
    return report


def assert_publishable(report: PublishabilityReport) -> None:
    """Refuse publication rather than shipping stale or synthetic numbers."""
    if report.publishable:
        return
    raise NotPublishableError(
        "대시보드 데이터를 게시할 수 없습니다: " + " / ".join(report.reasons),
        report,
    )
