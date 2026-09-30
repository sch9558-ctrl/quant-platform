#!/usr/bin/env python3
"""오늘자 대시보드 데이터가 이미 "제대로" 만들어져 있는지 한 줄로 답한다.

07:15 KST 복구 실행이 스스로를 건너뛸지 판단하는 데만 쓰인다.

예전 워크플로우는 `dashboard.json` 의 `as_of` 가 오늘 날짜인지만 봤다.
그런데 `as_of` 는 07:00 실행이 **실패했을 때에도** 오늘 날짜로 적혔고
(그 실패의 원인이 바로 '오늘'을 요구한 것이었다), 그래서 복구 실행은
고장 난 결과물을 보고 "이미 됐네"라고 판단하며 매일 자신을 건너뛰었다.
복구 실행이 존재하는 이유를 정확히 무력화한 것이다.

그래서 두 가지를 모두 요구한다:

  1. `generated_at` 이 오늘(Asia/Seoul) 만들어졌을 것 -- 즉 07:00 실행이
     실제로 오늘 돌아서 파일을 새로 썼을 것.
  2. `publishability.publishable` 이 참일 것 -- 즉 그 결과가 실데이터
     기반이고 최신일 것. 정직한 "데이터 없음" 페이지는 게시할 가치는
     있어도 복구 실행을 건너뛸 이유는 되지 못한다.

출력은 "yes" 또는 "no" 한 줄뿐이고, 어떤 이유로든 판단할 수 없으면
"no" 를 낸다 -- 판단 불가일 때 건너뛰는 쪽으로 기울면 그게 바로 위에서
설명한 실패다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_PATH = Path("site/data/dashboard.json")


def is_todays_publishable_build(path: Path, run_date: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False

    generated_at = payload.get("generated_at") or ""
    if not isinstance(generated_at, str) or generated_at[:10] != run_date:
        return False

    publishability = payload.get("publishability")
    if not isinstance(publishability, dict):
        # schema_version 1 에는 이 정보가 아예 없다. 게시 가능 여부를
        # 확인할 수 없으므로 건너뛰지 않는다.
        return False
    return publishability.get("publishable") is True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("no")
        return 0
    run_date = argv[1]
    path = Path(argv[2]) if len(argv) > 2 else DEFAULT_PATH
    print("yes" if is_todays_publishable_build(path, run_date) else "no")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
