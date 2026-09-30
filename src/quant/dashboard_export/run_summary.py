"""A short, readable verdict for whoever is looking at the run afterwards.

The daily pipeline can take an hour and print tens of thousands of lines.
GitHub's log viewer renders only the beginning of a step, so on 2026-09-30
a run that had actually *worked* -- 42 minutes of real US market data --
was indistinguishable from one that had not, because the one line that said
whether the payload could be published was somewhere in the middle of a log
nobody could scroll to.

So the verdict goes to the job summary instead: publishable or not, why not,
and what each market did. Two dozen lines that answer "did today's run
produce anything trustworthy?" without opening a log at all.

This renders from the dashboard payload itself, so it cannot drift from what
was actually decided -- it is the same `publishability` block the publication
gate acts on, not a second opinion about it.
"""
from __future__ import annotations

import os
from pathlib import Path

_OK = "✅"
_NO = "⛔"
_WARN = "⚠️"


def _fmt_market(key: str, market: dict | None, freshness: dict | None) -> list[str]:
    if not market:
        return [f"| {key} | — | 결과 없음 | |"]
    status = market.get("status", "—")
    blocked = market.get("blocked")
    mark = _NO if blocked else _OK
    size = market.get("universe_size", 0)
    detail = market.get("block_reason") or f"후보 {len(market.get('candidates') or [])}개 / 유니버스 {size}개"
    if freshness:
        fresh = freshness.get("state") or freshness.get("status") or ""
        gap = freshness.get("gap_sessions")
        bits = [b for b in (fresh, f"{gap} 세션 지연" if gap else "") if b]
        if bits:
            detail = f"{detail} ({', '.join(bits)})"
    return [f"| {mark} {key} | {status} | {_squash(detail)} | {market.get('as_of') or ''} |"]


def _squash(text: str, limit: int = 220) -> str:
    """Markdown tables are one row per line and `|` ends a cell."""
    s = " ".join(str(text).split()).replace("|", "/")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def render_run_summary(data: dict) -> str:
    """Markdown for the job summary, rendered from the payload itself."""
    pub = data.get("publishability") or {}
    publishable = bool(pub.get("publishable"))
    overview = data.get("overview") or {}
    markets = data.get("markets") or {}
    freshness = (pub.get("markets") or {})

    head = _OK + " 게시 가능" if publishable else _NO + " 게시 불가"
    lines = [
        "## 오늘 실행 결과",
        "",
        f"**{head}** · 데이터 출처: `{pub.get('data_source_mode') or data.get('data_source_mode') or '?'}`"
        f" · 기준 세션: `{data.get('as_of') or '—'}`",
        "",
    ]

    if not publishable:
        reasons = pub.get("reasons") or []
        lines += ["게시하지 않은 이유:", ""]
        lines += [f"- {_squash(r)}" for r in reasons] or ["- (사유가 기록되지 않았습니다)"]
        lines += [
            "",
            f"{_WARN} `site/data/dashboard.json` 은 **갱신하지 않았습니다.** 낡거나 합성된 데이터를",
            "정상 결과처럼 게시하지 않는 것이 이 게이트의 목적입니다.",
            "",
        ]

    lines += [
        "| 시장 | 상태 | 내용 | 기준일 |",
        "|---|---|---|---|",
    ]
    for key in ("korea", "us"):
        lines += _fmt_market(key, markets.get(key), freshness.get(key))

    lines += [
        "",
        "| 점검 | 결과 |",
        "|---|---|",
        f"| 데이터 무결성 | {overview.get('data_integrity', '—')} |",
        f"| 필수 검증 통과율 | {overview.get('mandatory_validation_pass_rate', '—')} |",
        f"| 파이프라인 | {overview.get('pipeline_health', '—')} |",
        f"| 투자 준비 단계 | {overview.get('investment_readiness', '—')} |",
        "",
        "_\"검증 통과\"는 필수 데이터 품질 검사를 모두 통과했다는 뜻입니다._",
        "_수익을 예측할 수 있다는 뜻도, 손실이 없다는 뜻도 아닙니다._",
    ]
    return "\n".join(lines) + "\n"


def write_job_summary(data: dict, path: str | os.PathLike | None = None) -> bool:
    """Append the verdict to GitHub's job summary when running in Actions.

    Returns whether anything was written. Outside CI there is no summary
    file and this is a no-op -- a local run should not need an environment
    variable set to avoid crashing.
    """
    target = path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return False
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(render_run_summary(data))
    except OSError:
        # Reporting is never allowed to fail the run it is reporting on.
        return False
    return True
