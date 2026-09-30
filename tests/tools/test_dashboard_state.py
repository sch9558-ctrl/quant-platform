"""복구 실행이 스스로를 건너뛸 조건 (tools/dashboard_state.py).

이 판단이 틀리면 증상이 조용하다. 07:00 실행이 실패해도 복구 실행이
"이미 됐네" 하고 넘어가 버리면, 워크플로우는 초록색인데 대시보드는 몇 주째
낡은 채로 남는다 -- 실제로 그렇게 3주 반이 지나갔다. 그래서 "건너뛴다"는
판단은 두 조건을 모두 만족할 때에만 나와야 한다.
"""
from __future__ import annotations

import json

import pytest

from tools.dashboard_state import is_todays_publishable_build

RUN_DATE = "2026-09-21"


def _write(tmp_path, payload):
    path = tmp_path / "dashboard.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _good_payload():
    return {
        "generated_at": f"{RUN_DATE}T22:04:11.512+00:00",
        "as_of": RUN_DATE,
        "data_source_mode": "real",
        "publishability": {"publishable": True},
    }


def test_todays_publishable_build_is_skippable(tmp_path):
    assert is_todays_publishable_build(_write(tmp_path, _good_payload()), RUN_DATE) is True


def test_yesterdays_build_is_not_skippable(tmp_path):
    payload = _good_payload()
    payload["generated_at"] = "2026-09-20T22:04:11.512+00:00"
    assert is_todays_publishable_build(_write(tmp_path, payload), RUN_DATE) is False


def test_todays_unpublishable_build_is_not_skippable(tmp_path):
    """정직한 '데이터 없음' 페이지는 게시할 가치는 있지만, 복구 실행을
    건너뛸 이유는 되지 못한다 -- 복구 실행은 바로 그 상태를 고치려고 있다."""
    payload = _good_payload()
    payload["publishability"] = {"publishable": False, "reasons": ["합성 데이터"]}
    assert is_todays_publishable_build(_write(tmp_path, payload), RUN_DATE) is False


def test_as_of_alone_does_not_make_it_skippable(tmp_path):
    """정확히 이것이 예전 동작이었다. as_of 는 실패한 실행에서도 오늘
    날짜로 적혔고, 그 실패의 원인이 바로 '오늘'을 요구한 것이었다."""
    payload = {"as_of": RUN_DATE, "generated_at": "2026-08-26T08:15:56.441913+00:00"}
    assert is_todays_publishable_build(_write(tmp_path, payload), RUN_DATE) is False


def test_schema_version_1_payload_without_publishability_is_not_skippable(tmp_path):
    payload = {"generated_at": f"{RUN_DATE}T22:04:11+00:00", "as_of": RUN_DATE}
    assert is_todays_publishable_build(_write(tmp_path, payload), RUN_DATE) is False


@pytest.mark.parametrize(
    "broken",
    ["", "{", "null", "[]", '"a string"'],
    ids=["empty", "truncated", "null", "list", "string"],
)
def test_unreadable_payloads_never_skip(tmp_path, broken):
    """판단할 수 없으면 건너뛰지 않는다. 판단 불가일 때 건너뛰는 쪽으로
    기울면 고장이 조용해진다."""
    assert is_todays_publishable_build(_write(tmp_path, broken), RUN_DATE) is False


def test_missing_file_never_skips(tmp_path):
    assert is_todays_publishable_build(tmp_path / "nope.json", RUN_DATE) is False


def test_publishable_must_be_the_boolean_true(tmp_path):
    """문자열 "false" 는 파이썬에서 참이다. 게시 가능 여부를 느슨하게
    보면 정확히 반대 결론이 나올 수 있다."""
    payload = _good_payload()
    payload["publishability"] = {"publishable": "false"}
    assert is_todays_publishable_build(_write(tmp_path, payload), RUN_DATE) is False
