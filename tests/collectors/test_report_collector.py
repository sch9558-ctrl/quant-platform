from quant.collectors.report_collector import (
    AnalystReport,
    NaverResearchCollector,
    dedupe_reports,
)


def test_naver_detail_parses_target_and_rating():
    target, rating = NaverResearchCollector.parse_detail(
        "<div>목표가 92,000 | 투자의견 Buy  작성일 2026.10.01</div>"
    )
    assert target == 92000
    assert rating == "BUY"


def test_naver_list_parses_current_table_shape():
    html = """<table><tr>
      <td><a href="/item/main.naver?code=005930">삼성전자</a></td>
      <td><a href="/research/company_read.naver?nid=1&page=1">전망</a></td>
      <td>테스트증권</td><td></td><td>26.10.01</td><td>100</td>
    </tr></table>"""
    rows = NaverResearchCollector.parse_list(html)
    assert rows
    assert rows[0]["symbol"] == "005930"
    assert rows[0]["company"] == "삼성전자"
    assert rows[0]["institution"] == "테스트증권"
    assert rows[0]["published_at"] == "2026-10-01"


def test_dedupe_reports_is_stable():
    r = AnalystReport(
        "us", "ABC", None, "2026-01-01", "Bank", None, 120, "BUY", "USD", "fixture"
    )
    assert dedupe_reports([r, r]) == [r]
