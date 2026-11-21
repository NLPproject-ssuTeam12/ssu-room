"""SSU:room 서버 API 테스트 (실제 데이터 data/private/real 사용).

실행 (저장소 루트에서):
    python -m pytest backend/tests -q

data/private/real/ 이 없으면(커밋 안 되는 폴더) 이 파일 전체를 건너뛴다.
먼저 python backend/tools/import_real.py --src <원본 폴더> 로 만든다.
"""

import importlib
import importlib.abc
import importlib.machinery
import os
import re
import sys
import types
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
if not (DATA / "sections.json").exists():
    pytest.skip(f"{DATA} 에 데이터가 없어 건너뜀", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import engine  # noqa: E402
from backend.app.main import app  # noqa: E402

REPLY = "A나 C 다 괜찮아요. 수요일은 17시 전에 끝나야 해요"
COORD_MOD = "backend.app.nlp.coord"


# ---------- 도우미 ----------

@pytest.fixture()
def client():
    c = TestClient(app)
    assert c.post("/reset").status_code == 200
    yield c
    c.post("/reset")


def enc(sid: str) -> str:
    """분반 id에는 한글·괄호가 있어 경로에 넣을 때 인코딩한다 (화면의 encodeURIComponent와 같음)."""
    return quote(sid, safe="")


def sections(client):
    r = client.get("/sections")
    assert r.status_code == 200
    return r.json()


def first_auto_section(client) -> str:
    return next(s["id"] for s in sections(client) if s["shape"] != "MANUAL")


def first_manual_section(client) -> str:
    return next(s["id"] for s in sections(client) if s["shape"] == "MANUAL")


def start_round(client) -> str:
    """초안 → 1차. 조율 대상 분반 id 하나를 돌려준다."""
    assert client.post("/draft").status_code == 200
    assert client.post("/rounds/next").json()["round_no"] == 1
    return client.get("/coord").json()[0]["section_id"]


# ---------- 전체 흐름 ----------

def test_full_flow(client):
    r = client.get("/health")
    assert r.status_code == 200
    h = r.json()
    assert h["stage"] == "COLLECT"
    assert set(h["engine"]) == set(engine.ASSIGN_NAMES + engine.COORD_NAMES)

    secs = sections(client)
    assert len(secs) == 97
    shape = Counter(s["shape"] for s in secs)
    assert set(shape) <= {"TWICE", "ONCE_LONG", "MANUAL"}
    assert sum(shape.values()) == 97

    r = client.post("/draft")
    assert r.status_code == 200
    d = r.json()
    assert d["stage"] == "DRAFT"
    assert d["status_count"].get("MANUAL") == shape["MANUAL"]

    coord = client.get("/coord").json()
    assert len(coord) >= 1

    # 한글·괄호가 든 분반 id를 고른다 (없으면 첫 번째)
    item = next((c for c in coord if re.search(r"[가-힣()]", c["section_id"])), coord[0])
    sid = item["section_id"]
    assert re.search(r"[가-힣()]", sid), "실제 데이터의 조율 분반 id에 한글·괄호가 있어야 인코딩 검사가 됨"

    # 조율 메시지·답장은 차수 안에서만 → 1차 시작
    r = client.post("/rounds/next")
    assert r.status_code == 200 and r.json()["round_no"] == 1

    r = client.post(f"/coord/{enc(sid)}/message")
    assert r.status_code == 200, r.text
    msg = r.json()
    assert msg["section_id"] == sid and msg["sent"] is True and msg["text"]

    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": REPLY, "method": "keyword"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["parse"]["decision"] in ("수용", "조건부", "거절", "확인필요")
    proposal = rep["proposal"]

    if proposal["action"] == "MOVE":
        r = client.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"})
    else:
        r = client.post(f"/coord/{enc(sid)}/decide",
                        json={"action": "edit", "reason": "테스트: 조교가 A안 선택", "choice": "A"})
    assert r.status_code == 200, r.text
    applied = r.json()["decision"]["applied"]
    assert r.json()["coord"]["state"] == "RESOLVED"

    tt = client.get("/timetable").json()
    a = next(x for x in tt["assignments"] if x["section_id"] == sid)
    assert a["status"] == "DONE"
    assert a["blocks"] == applied["blocks"] and a["room"] == applied["room"]

    # 지금 1차. 2차·3차로 가고, 그다음은 409
    for n in (2, 3):
        r = client.post("/rounds/next")
        assert r.status_code == 200 and r.json()["round_no"] == n
    r = client.post("/rounds/next")
    assert r.status_code == 409

    r = client.post("/finalize")
    assert r.status_code == 200
    assert r.json()["stage"] == "FINAL"
    assert client.get("/timetable").json()["status"] == "FINAL"


def test_rounds_next_three_times_then_409(client):
    assert client.post("/draft").status_code == 200
    for n in (1, 2, 3):
        r = client.post("/rounds/next")
        assert r.status_code == 200 and r.json()["round_no"] == n
    r = client.post("/rounds/next")
    assert r.status_code == 409
    assert "3차" in r.json()["detail"]


# ---------- 단계 위반 ----------

def test_reply_in_collect_409(client):
    sid = first_auto_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": REPLY})
    assert r.status_code == 409
    assert "COLLECT" in r.json()["detail"]


def test_wish_after_final_409(client):
    sid = first_auto_section(client)
    assert client.post("/draft").status_code == 200
    assert client.post("/finalize").status_code == 200
    r = client.post("/wishes", json={"section_id": sid, "cells": {"월-09:00": "PREFER"}})
    assert r.status_code == 409


def test_draft_twice_409(client):
    assert client.post("/draft").status_code == 200
    assert client.post("/draft").status_code == 409


def test_timetable_before_draft_409(client):
    assert client.get("/timetable").status_code == 409


# ---------- decide 검사 ----------

def test_decide_edit_needs_reason_and_choice(client):
    sid = start_round(client)
    url = f"/coord/{enc(sid)}/decide"
    assert client.post(url, json={"action": "edit", "choice": "A"}).status_code == 422
    assert client.post(url, json={"action": "edit", "reason": "  ", "choice": "A"}).status_code == 422
    assert client.post(url, json={"action": "edit", "reason": "조교 판단"}).status_code == 422
    assert client.post(url, json={"action": "nope"}).status_code == 422
    # 사유와 안이 있으면 반영된다
    r = client.post(url, json={"action": "edit", "reason": "조교 판단", "choice": "A"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["reason"] == "조교 판단"


def test_confirm_without_proposal_409(client):
    sid = start_round(client)
    r = client.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"})
    assert r.status_code == 409


# ---------- 희망 형식 ----------

@pytest.mark.parametrize("cells", [
    {"토-09:00": "PREFER"},      # 토요일 칸
    {"월-09:30": "PREFER"},      # 없는 시작 시각
    {"월-17:00": "BLOCK"},       # 없는 시작 시각
    {"월-09:00": "MAYBE"},       # PREFER/BLOCK 외 값
])
def test_wish_format_422(client, cells):
    sid = first_auto_section(client)
    r = client.post("/wishes", json={"section_id": sid, "cells": cells})
    assert r.status_code == 422


def test_wish_ok(client):
    sid = first_auto_section(client)
    r = client.post("/wishes", json={"section_id": sid, "cells": {"월-09:00": "PREFER", "금-19:30": "BLOCK"},
                                     "lab": "PREFER"})
    assert r.status_code == 200, r.text
    w = next(x for x in client.get("/wishes").json()["wishes"] if x["section_id"] == sid)
    assert w["cells"] == {"월-09:00": "PREFER", "금-19:30": "BLOCK"}


# ---------- MANUAL·없는 분반 ----------

def test_manual_section_coord_409(client):
    sid = first_manual_section(client)
    start_round(client)
    for path, body in (("message", None), ("reply", {"text": REPLY}), ("decide", {"action": "keep"})):
        r = client.post(f"/coord/{enc(sid)}/{path}", json=body)
        assert r.status_code == 409, path
        assert "조교 직접 배정" in r.json()["detail"]


def test_manual_sections_visible_in_timetable(client):
    manual = {s["id"] for s in sections(client) if s["shape"] == "MANUAL"}
    client.post("/draft")
    tt = client.get("/timetable").json()["assignments"]
    shown = {a["section_id"] for a in tt if a["status"] == "MANUAL"}
    assert shown == manual
    # 토요일 블록은 MANUAL 분반에만 있다
    for a in tt:
        if any(b["day"] == "토" for b in a["blocks"]):
            assert a["status"] == "MANUAL"


def test_unknown_section_404(client):
    start_round(client)
    for path in ("message", "reply", "decide"):
        r = client.post(f"/coord/{enc('없는-분반(가짜)')}/{path}", json={"text": "x", "action": "keep"})
        assert r.status_code == 404, path
    r = client.post("/wishes", json={"section_id": "없는-분반", "cells": {}})
    assert r.status_code == 404


# ---------- 실명 검사 ----------

ALIAS = re.compile(r"^교수\d+$")


def _professor_values(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "professor":
                yield v
            else:
                yield from _professor_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _professor_values(v)


def test_professor_values_are_aliases(client):
    def check_all():
        n = 0
        for path in ("/health", "/sections", "/rooms", "/wishes", "/timetable", "/coord"):
            r = client.get(path)
            if r.status_code != 200:
                continue
            for v in _professor_values(r.json()):
                n += 1
                assert v is None or ALIAS.match(v), f"{path}: 가명이 아닌 교수 값 {v!r}"
        return n

    assert check_all() > 0          # COLLECT
    for key in client.get("/wishes").json()["professors"]:
        assert ALIAS.match(key), f"/wishes professors 키가 가명이 아님: {key!r}"
    start_round(client)
    assert check_all() > 0          # ROUND (시간표·조율 포함)


# ---------- engine 교체 검사 (메모리에서만) ----------

@pytest.fixture()
def restore_engine():
    yield
    sys.modules.pop(COORD_MOD, None)
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _BrokenFinder)]
    importlib.reload(engine)


def test_engine_uses_real_function_when_present(client, restore_engine):
    fake = types.ModuleType(COORD_MOD)
    fake.__spec__ = importlib.machinery.ModuleSpec(COORD_MOD, None)
    fake.parse_reply = lambda text, method="keyword": engine.stubs.parse_reply(text, method)
    sys.modules[COORD_MOD] = fake
    importlib.reload(engine)

    src = engine.sources()
    assert src["parse_reply"] == f"real ({COORD_MOD})"
    assert src["write_message"] == "stub"      # 함수마다 따로 판단
    assert all(src[n] == "stub" for n in engine.ASSIGN_NAMES)
    assert engine.load_warnings() == []
    h = client.get("/health").json()
    assert h["engine"]["parse_reply"].startswith("real")


class _BrokenLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        # 모듈 안에서 필요한 패키지가 없을 때와 같은 에러
        raise ModuleNotFoundError("No module named 'some_llm_sdk'", name="some_llm_sdk")


class _BrokenFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == COORD_MOD:
            return importlib.machinery.ModuleSpec(fullname, _BrokenLoader())
        return None


def test_engine_warns_when_real_module_is_broken(client, restore_engine):
    sys.modules.pop(COORD_MOD, None)
    sys.meta_path.insert(0, _BrokenFinder())
    importlib.reload(engine)

    assert all(engine.sources()[n] == "stub" for n in engine.COORD_NAMES)
    warnings = engine.load_warnings()
    assert len(warnings) == len(engine.COORD_NAMES)
    assert any(w.startswith("parse_reply 함수: 진짜 모듈 불러오기 실패 → 가짜 사용") and "some_llm_sdk" in w
               for w in warnings)
    h = client.get("/health").json()
    assert any("parse_reply 함수: 진짜 모듈 불러오기 실패" in w for w in h["load_warnings"])


def test_engine_no_warning_when_module_missing():
    # 지금 저장소에는 진짜 모듈이 없으므로 경고가 없어야 한다
    importlib.reload(engine)
    assert engine.load_warnings() == []
