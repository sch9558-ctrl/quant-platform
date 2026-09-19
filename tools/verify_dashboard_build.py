#!/usr/bin/env python3
"""Pre-deployment verification of the built dashboard directory.

The last gate before a deployment goes out. It answers, against the files
that are actually about to be uploaded (not against in-memory objects a
test constructed):

  * is the entry point there and non-trivial?
  * does every required data file exist and parse?
  * does the payload carry the metadata the front-end and the audit trail
    depend on (generated_at, as_of, data_source_mode, publishability)?
  * is the payload REAL and FRESH, or is it an honest unavailable state?
  * is anything secret-shaped about to be published?
  * did any test/fixture/demo artifact leak into the deploy directory?

Exit codes:
  0  safe to deploy
  1  refused -- reasons printed

Two deliberate design points:

`--require-publishable` is OFF by default. A deployment carrying an honest
"데이터 없음" state is a legitimate, desirable deployment: it is how the
dashboard tells its user that today's data could not be validated. What
must never deploy is a payload that *claims* to be current research while
being synthetic or stale, and that is caught by the metadata checks
regardless of this flag. Turn the flag on to additionally require that
real, fresh research is present.

The secret scan here is a narrow, high-signal net over deployable text,
not a replacement for gitleaks (which runs over the repository and its
history in CI). Its job is to catch a credential that reached the built
artifact specifically -- the one place a repo-wide scan can miss because
the file did not exist at scan time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_DATA_FILES = ["dashboard.json", "history.json"]

REQUIRED_TOP_LEVEL_FIELDS = [
    "schema_version", "generated_at", "as_of",
    "data_source_mode", "publishability",
    "overview", "markets", "disclaimer",
]

REQUIRED_OVERVIEW_FIELDS = [
    "data_integrity", "mandatory_validation_pass_rate", "pipeline_health",
    "strategy_validation", "investment_readiness",
]

#: Artifacts that must never appear in a deploy directory. Production and
#: test data are separated by construction elsewhere; this is the check
#: that the separation actually held for the bytes being shipped.
FORBIDDEN_PATH_PARTS = ["tests", "fixtures", "fixture", "sample", "demo", "__pycache__", ".pytest_cache"]

#: Narrow, high-signal credential patterns. Deliberately not a generic
#: "high entropy string" heuristic: dashboard payloads are full of hashes
#: and data-version fingerprints, and a scanner that cries wolf on those
#: gets switched off, which is worse than no scanner.
SECRET_PATTERNS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
     "hardcoded credential assignment"),
    (re.compile(r"(?i)\bCLOUDFLARE_API_TOKEN\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"), "Cloudflare API token"),
]

TEXT_SUFFIXES = {".html", ".htm", ".js", ".css", ".json", ".txt", ".md", ".yml", ".yaml", ".svg"}


class Verifier:
    def __init__(self, site_dir: Path, require_publishable: bool):
        self.site = site_dir
        self.require_publishable = require_publishable
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # -- checks -------------------------------------------------------
    def check_entry_point(self) -> None:
        index = self.site / "index.html"
        if not index.is_file():
            self.error(f"진입 파일이 없습니다: {index}")
            return
        html = index.read_text(encoding="utf-8", errors="replace")
        if len(html) < 1000:
            self.error(f"index.html 이 비정상적으로 작습니다 ({len(html)} bytes).")
        if "data/dashboard.json" not in html:
            self.error("index.html 이 data/dashboard.json 을 참조하지 않습니다.")

    def check_data_files(self) -> dict | None:
        data_dir = self.site / "data"
        if not data_dir.is_dir():
            self.error(f"데이터 디렉터리가 없습니다: {data_dir}")
            return None
        payload = None
        for name in REQUIRED_DATA_FILES:
            path = data_dir / name
            if not path.is_file():
                self.error(f"필수 데이터 파일이 없습니다: {name}")
                continue
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                self.error(f"{name} 을 JSON 으로 읽을 수 없습니다: {e}")
                continue
            if name == "dashboard.json":
                payload = parsed
            if name == "history.json" and not isinstance(parsed, list):
                self.error("history.json 은 배열이어야 합니다.")
        return payload

    def check_payload_metadata(self, payload: dict) -> None:
        for field in REQUIRED_TOP_LEVEL_FIELDS:
            if field not in payload:
                self.error(f"dashboard.json 에 필수 항목이 없습니다: {field}")
        overview = payload.get("overview") or {}
        for field in REQUIRED_OVERVIEW_FIELDS:
            if field not in overview:
                self.error(f"dashboard.json overview 에 필수 항목이 없습니다: {field}")

        if not payload.get("generated_at"):
            self.error("generated_at 이 비어 있습니다.")

        verdict = payload.get("publishability")
        if not isinstance(verdict, dict):
            self.error("publishability 정보가 없습니다 (신선도 판정을 계산할 수 없습니다).")
            return
        if "publishable" not in verdict or "markets" not in verdict:
            self.error("publishability 구조가 올바르지 않습니다.")
            return

        mode = payload.get("data_source_mode")
        publishable = verdict.get("publishable")

        # The contradiction that started all of this: a payload asserting
        # healthy research while its own metadata says it is not current.
        if publishable and mode != "real":
            self.error(
                f"모순: publishable=true 인데 데이터 출처가 '{mode}' 입니다. "
                "합성 데이터는 게시 가능 상태가 될 수 없습니다."
            )
        if publishable and overview.get("data_integrity") == "FAIL":
            self.error("모순: publishable=true 인데 데이터 무결성이 FAIL 입니다.")
        if not publishable and overview.get("data_integrity") == "PASS":
            self.error(
                "모순: 게시 불가 상태(합성 또는 지연)인데 데이터 무결성이 PASS 로 표시됩니다. "
                "이 조합이 바로 2022-06-01 데이터가 PASS 로 게시된 원인입니다."
            )

        for market, fresh in (verdict.get("markets") or {}).items():
            status = fresh.get("status")
            if status not in {"FRESH", "STALE", "UNKNOWN"}:
                self.error(f"{market} 신선도 상태값이 올바르지 않습니다: {status!r}")

        if not publishable:
            reasons = verdict.get("reasons") or []
            if not reasons:
                self.error("게시 불가 상태인데 사용자에게 보여줄 사유가 없습니다.")
            self.notes.append(
                "게시 불가 상태로 배포합니다(정상 동작): " + " / ".join(reasons[:3])
            )
            if self.require_publishable:
                self.error(
                    "--require-publishable 이 지정되었지만 실제·최신 데이터가 아닙니다."
                )

    def check_no_test_artifacts(self) -> None:
        for path in self.site.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.site)
            parts = {p.lower() for p in rel.parts}
            hit = parts & set(FORBIDDEN_PATH_PARTS)
            if hit:
                self.error(f"배포 디렉터리에 테스트/샘플 산출물이 포함되어 있습니다: {rel}")

    def check_no_secrets(self) -> None:
        for path in self.site.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(text):
                    self.error(
                        f"배포 산출물에 비밀정보로 보이는 값이 있습니다 "
                        f"({label}): {path.relative_to(self.site)}"
                    )

    def check_noindex(self) -> None:
        robots = self.site / "robots.txt"
        if not robots.is_file():
            self.warn("robots.txt 가 없습니다 (검색엔진 노출 방지 보조조치).")
        elif "Disallow: /" not in robots.read_text(encoding="utf-8"):
            self.warn("robots.txt 에 Disallow: / 가 없습니다.")

    # -- driver -------------------------------------------------------
    def run(self) -> int:
        if not self.site.is_dir():
            print(f"배포 디렉터리가 없습니다: {self.site}")
            return 1

        self.check_entry_point()
        payload = self.check_data_files()
        if payload is not None:
            self.check_payload_metadata(payload)
        self.check_no_test_artifacts()
        self.check_no_secrets()
        self.check_noindex()

        for note in self.notes:
            print(f"[안내] {note}")
        for warning in self.warnings:
            print(f"[경고] {warning}")
        for err in self.errors:
            print(f"[실패] {err}")

        if self.errors:
            print(f"\n대시보드 빌드 검증 실패: 문제 {len(self.errors)}건. 배포하지 않습니다.")
            return 1
        print("\n대시보드 빌드 검증 통과.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site-dir", default="site", help="배포할 디렉터리 (기본: site)")
    parser.add_argument(
        "--require-publishable", action="store_true",
        help="실제·최신 데이터가 아니면 실패로 처리합니다. 기본값은 '데이터 없음' "
             "상태의 정직한 배포를 허용합니다.",
    )
    args = parser.parse_args()
    return Verifier(Path(args.site_dir), args.require_publishable).run()


if __name__ == "__main__":
    sys.exit(main())
