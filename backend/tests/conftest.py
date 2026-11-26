"""테스트 경로 설정. 저장소 맨 위와 backend/ 안 어디서 pytest를 돌려도 `backend.app`을 찾게 한다.

(backend/ 안에서 돌리면 저장소 맨 위가 import 경로에 없어 'No module named backend'가 났다.)
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _keyword_by_default(monkeypatch):
    """테스트는 늘 키워드 방식이 기본: 서버 기본 해석 방식(SSUROOM_NLP)을 지운다 (.env 나 셸 값에 흔들리지 않게)."""
    monkeypatch.delenv("SSUROOM_NLP", raising=False)
    # 화면 주소 허용(CORS)도 기본값으로: 컴퓨터 2대 시연용 환경 변수를 지운다
    monkeypatch.delenv("SSUROOM_LAN", raising=False)
    monkeypatch.delenv("SSUROOM_CORS", raising=False)
