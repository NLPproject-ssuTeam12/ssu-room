"""화면 주소 허용(CORS): 기본은 지금과 같이 http://localhost:5173 만. 컴퓨터 2대 시연용 SSUROOM_LAN·SSUROOM_CORS.
환경 변수에 따라 설정이 바뀌므로, 설정 함수(main.cors_settings)로 작은 앱을 다시 만들어 확인한다.
(conftest 가 테스트마다 SSUROOM_LAN·SSUROOM_CORS 를 지운다)

data/private/ 이 없으면(커밋 안 되는 폴더) 이 파일 전체를 건너뛴다. backend.app.main 을 불러오면 서버 저장소(store)가
그 데이터를 읽기 때문이다 (test_api.py 와 같은 처리).
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
if not (DATA / "sections.json").exists():
    pytest.skip(f"{DATA} 에 데이터가 없어 건너뜀", allow_module_level=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402

ALLOW = "access-control-allow-origin"


def make_client():
    """지금 환경 변수로 CORS 를 설정한 작은 앱 (main.app 과 같은 cors_settings)."""
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **main.cors_settings())

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def allowed(client, origin) -> bool:
    """일반 요청과 preflight(OPTIONS) 둘 다 그 주소를 허용하는지. 둘이 다르면 테스트 실패."""
    get = client.get("/ping", headers={"Origin": origin})
    pre = client.options("/ping", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                           "Access-Control-Request-Headers": "content-type"})
    simple = get.headers.get(ALLOW) == origin
    preflight = pre.status_code == 200 and pre.headers.get(ALLOW) == origin
    assert simple == preflight, (origin, get.headers, pre.status_code, pre.headers)
    return simple


def test_default_is_unchanged():
    s = main.cors_settings()
    assert s["allow_origins"] == ["http://localhost:5173"] and "allow_origin_regex" not in s
    c = make_client()
    assert allowed(c, "http://localhost:5173")
    assert not allowed(c, "http://192.168.0.5:5173")
    assert not allowed(c, "http://127.0.0.1:5173")


def test_real_app_default_and_health():
    """실제 서버 앱(환경 변수 없이 켠 것)도 지금처럼: localhost:5173 만, /health 의 lan 은 false."""
    c = TestClient(main.app)
    r = c.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200 and r.headers.get(ALLOW) == "http://localhost:5173"
    assert r.json()["lan"] is False
    assert {"ok", "stage", "engine", "nlp", "gemini_key"} <= set(r.json())          # 다른 키는 그대로
    r = c.get("/health", headers={"Origin": "http://192.168.0.5:5173"})
    assert ALLOW not in r.headers
    pre = c.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and pre.headers.get(ALLOW) == "http://localhost:5173"


@pytest.mark.parametrize("origin", ["http://192.168.0.5:5173", "http://10.0.0.3:5173", "http://172.20.1.2:5173",
                                    "http://172.16.0.1:5173", "http://172.31.255.254:5173"])
def test_lan_allows_private_5173(monkeypatch, origin):
    monkeypatch.setenv("SSUROOM_LAN", "1")
    c = make_client()
    assert allowed(c, origin)
    assert allowed(c, "http://localhost:5173")                          # 기본도 그대로


@pytest.mark.parametrize("origin", ["http://8.8.8.8:5173", "http://192.168.0.5:3000", "http://172.32.0.1:5173",
                                    "http://172.15.0.1:5173", "https://192.168.0.5:5173", "http://192.168.0.5:51730",
                                    "http://192.168.0.5.evil.com:5173"])
def test_lan_blocks_others(monkeypatch, origin):
    monkeypatch.setenv("SSUROOM_LAN", "1")
    assert not allowed(make_client(), origin)


def test_lan_flag_in_health(monkeypatch):
    monkeypatch.setenv("SSUROOM_LAN", "1")
    assert TestClient(main.app).get("/health").json()["lan"] is True
    monkeypatch.setenv("SSUROOM_LAN", "0")
    assert TestClient(main.app).get("/health").json()["lan"] is False


def test_cors_list(monkeypatch):
    monkeypatch.setenv("SSUROOM_CORS", " http://203.0.113.7:5173 , http://demo.example:8080/ ,*")
    s = main.cors_settings()
    assert "*" not in s["allow_origins"]                                # "*" 는 받지 않는다
    c = make_client()
    assert allowed(c, "http://203.0.113.7:5173") and allowed(c, "http://demo.example:8080")
    assert allowed(c, "http://localhost:5173")
    assert not allowed(c, "http://203.0.113.8:5173")
    assert not allowed(c, "http://192.168.0.5:5173")                    # SSUROOM_LAN 없이 사설망은 여전히 막힘
