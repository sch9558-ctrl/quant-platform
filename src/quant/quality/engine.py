"""Data Quality Engine orchestrator (spec sections 3-21).

`DataQualityEngine.run(...)` is the single entry point everything else
(the scanner, `validate_data.py`, `run_research.py`) calls before any data
reaches the Universe/Feature/Strategy layers. It runs every mandatory
check, builds the Canonical Data table, and returns a `DataQualityReport`
whose `overall_status` is the Fail-Closed gate: "FAIL" means the caller
must not generate today's candidates from this data (spec section 2).

Design note on `mandatory_validation_pass_rate`: it is always exactly 0.0
or 100.0, never a number in between (spec section 14 -- "99.99%라도
FAIL이다"). A continuous `data_integrity_score` is also reported, but is
explicitly informational/dashboard-only and never used to decide
`overall_status` -- see the module docstring in `models.py` and
`ARCHITECTURE.md` "0. 가장 중요한 절대 원칙" for why these two numbers
must never be confused with each other or with prediction accuracy.
"""
from __future__ import annotations

import pandas as pd

from quant import config
from quant.quality import adapters, audit, canonical as canonical_mod
from quant.quality import completeness, corporate_actions, cross_source, ohlc, schema
from quant.quality.models import CheckResult, DataQualityReport, ValidationIssue


class DataQualityEngine:
    def __init__(self, market: str):
        assert market in ("korea", "us")
        self.market = market
        self.cfg = config.quality_config()

    def run(
        self,
        primary_ohlcv_map: dict[str, pd.DataFrame],
        *,
        source_primary: str,
        currency: str,
        start: str,
        end: str,
        as_of: str,
        secondary_ohlcv_map: dict[str, pd.DataFrame] | None = None,
        source_secondary: str | None = None,
        listing_dates: dict[str, pd.Timestamp] | None = None,
        delisting_dates: dict[str, pd.Timestamp] | None = None,
        stored_canonical_records: pd.DataFrame | None = None,
        retrieved_at: pd.Timestamp | str | None = None,
        version_store: audit.VersionStore | None = None,
        audit_log: audit.AuditLog | None = None,
    ) -> tuple[DataQualityReport, dict[str, pd.DataFrame], list]:
        """Returns (report, canonical_ohlcv_map, provenance_records).

        `canonical_ohlcv_map` is empty if `report.overall_status == "FAIL"`
        -- callers must check that before using it (this is the Fail-Closed
        contract; see `gate.py`)."""
        primary = adapters.to_long_records(primary_ohlcv_map, self.market, source_primary, currency, retrieved_at)
        secondary = (
            adapters.to_long_records(secondary_ohlcv_map, self.market, source_secondary, currency, retrieved_at)
            if secondary_ohlcv_map else None
        )

        checks: list[CheckResult] = []

        schema_result = schema.validate_schema(primary, self.market, self.cfg["schema"])
        checks.append(schema_result)
        if not schema_result.passed:
            # every subsequent check assumes the required columns exist --
            # stop here rather than raising confusing secondary errors.
            return self._finalize(checks, primary, pd.DataFrame(), [], n_symbols=len(primary_ohlcv_map))

        ohlc_result = ohlc.validate_ohlc_integrity(primary, self.market)
        checks.append(ohlc_result)

        dup_result = completeness.validate_duplicates(primary, self.market, self.cfg)
        checks.append(dup_result)

        ca_dates = corporate_actions.corporate_action_dates(primary)
        ca_result = corporate_actions.validate_corporate_action_consistency(primary, self.market)
        checks.append(ca_result)

        classified, outlier_counts = ohlc.classify_outliers(primary, self.cfg, ca_dates)

        # rows that failed hard OHLC integrity are QUARANTINED regardless of
        # what the outlier classifier said -- structural invalidity always
        # wins over "the price move looked plausible".
        bad_keys = {
            (i.symbol, i.date) for i in ohlc_result.issues if i.symbol is not None and i.date is not None
        }
        if bad_keys and not classified.empty:
            key_series = list(zip(classified["symbol"], classified["date"].astype(str)))
            quarantine_mask = pd.Series([k in bad_keys for k in key_series], index=classified.index)
            classified.loc[quarantine_mask, "outlier_status"] = "QUARANTINED"
        if not classified.empty:
            # recompute from the final per-row status (post-quarantine
            # override) so counts always sum to exactly the row count,
            # rather than incrementally patching a stale tally.
            recomputed = classified["outlier_status"].value_counts().to_dict()
            for s in ("VALID", "REVIEW", "QUARANTINED", "REJECTED"):
                recomputed.setdefault(s, 0)
            outlier_counts = {k: int(v) for k, v in recomputed.items()}

        missing_result = completeness.validate_missing_sessions(
            primary, self.market, start, end, self.cfg, listing_dates, delisting_dates,
        )
        checks.append(missing_result)

        freshness_result = completeness.validate_freshness(primary, self.market, as_of, self.cfg)
        checks.append(freshness_result)

        timezone_result = completeness.validate_timezone(primary, self.market, self.cfg)
        checks.append(timezone_result)

        cross_source_result = cross_source.validate_cross_source(primary, secondary, self.market, self.cfg, ca_dates)
        checks.append(cross_source_result)

        comparison = cross_source.compare_sources(primary, secondary, self.cfg, ca_dates) if secondary is not None else None
        usable = classified[classified["outlier_status"].isin(["VALID", "REVIEW"])] if not classified.empty else classified
        canonical_df, provenance = canonical_mod.build_canonical(
            usable, secondary, comparison, source_primary, source_secondary,
        )

        if stored_canonical_records is not None:
            revision_issues, n_revised = audit.detect_historical_revision(
                stored_canonical_records, canonical_df, self.market, self.cfg,
            )
            checks.append(CheckResult("historical_revision", mandatory=False, passed=True,
                                       issues=revision_issues, details={"n_revised": n_revised}))

        report = self._finalize(checks, primary, canonical_df, provenance, n_symbols=len(primary_ohlcv_map),
                                 outlier_counts=outlier_counts)

        if version_store is not None:
            checksum = audit.compute_checksum(canonical_df if report.overall_status == "PASS" else primary)
            dv = version_store.record(self.market, as_of, checksum)
            report.data_version = dv.tag
            report.checksum = checksum

        if audit_log is not None:
            self._write_audit_trail(audit_log, report, source_primary, checks)

        canonical_ohlcv_map = adapters.to_ohlcv_map(canonical_df) if report.overall_status == "PASS" else {}
        return report, canonical_ohlcv_map, provenance

    def _finalize(
        self, checks: list[CheckResult], primary: pd.DataFrame, canonical_df: pd.DataFrame,
        provenance: list, n_symbols: int, outlier_counts: dict | None = None,
    ) -> DataQualityReport:
        mandatory = [c for c in checks if c.mandatory]
        mandatory_pass = all(c.passed for c in mandatory) if mandatory else True
        pass_rate = 100.0 if mandatory_pass else 0.0

        n_total_rows = len(primary) if primary is not None else 0
        outlier_counts = outlier_counts or {}
        n_bad_rows = outlier_counts.get("REJECTED", 0) + outlier_counts.get("QUARANTINED", 0)
        integrity_score = round(1.0 - (n_bad_rows / n_total_rows), 4) if n_total_rows else 0.0

        return DataQualityReport(
            market=self.market,
            as_of=pd.Timestamp.now().strftime("%Y-%m-%d"),
            generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            checks=checks,
            outlier_counts=outlier_counts,
            n_symbols_checked=n_symbols,
            data_integrity_score=integrity_score,
            mandatory_validation_pass_rate=pass_rate,
            overall_status="PASS" if mandatory_pass else "FAIL",
        )

    def _write_audit_trail(self, audit_log: audit.AuditLog, report: DataQualityReport,
                            source_primary: str, checks: list[CheckResult]) -> None:
        for check in checks:
            audit_log.append(audit.AuditRecord(
                timestamp=pd.Timestamp.now(tz="UTC").isoformat(),
                market=self.market, symbol=None, source=source_primary,
                data_version=report.data_version, checksum=report.checksum,
                check=check.check, result="PASS" if check.passed else "FAIL",
                rule=check.check,
                error=None if check.passed else f"{len(check.issues)} issue(s)",
                canonical_source=source_primary,
            ))
