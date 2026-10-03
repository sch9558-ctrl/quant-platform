from quant.collectors.report_collector import NaverResearchCollector

def test_naver_detail_parses_target_and_rating():
    target,rating=NaverResearchCollector.parse_detail("<div>목표가 92,000 | 투자의견 Buy  작성일 2026.10.01</div>")
    assert target==92000 and rating=="BUY"

def test_naver_list_parses_basic_metadata():
    html='<table><tr><td><a href="/item/main.naver?code=005930">삼성전자</a></td><td><a href="/research/company_read.naver?nid=1&code=005930">전망</a></td><td>테스트증권</td><td>26.10.01</td></tr></table>'
    rows=NaverResearchCollector.parse_list(html)
    assert rows and rows[0]["symbol"]=="005930" and rows[0]["company"]=="삼성전자"
