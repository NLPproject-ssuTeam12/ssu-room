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
    assert rep["parse"]["kind"] in ("수용", "조건부", "거절", "확인 필요")
    assert set(rep["parse"]) >= {"kind", "picks", "conditions", "method", "fallback"}
    proposal = rep["proposal"]
    assert proposal["action"] in ("move", "next", "decide")

    if proposal["action"] == "move":
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
    days = "월화수목금"
    assert [(b["day"], b["start"]) for b in a["blocks"]] == [(days[m["day"]], m["start"]) for m in applied["meetings"]]
    assert a["room"] == applied["meetings"][0]["room"]

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

    def parse_reply(text, choice=None, *, alternatives=None, message="", method="keyword"):
        return engine.stubs.parse_reply(text, choice, alternatives=alternatives, message=message, method=method)

    fake.parse_reply = parse_reply
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


def test_engine_warns_when_signature_differs(client, restore_engine):
    """진짜 함수의 인자 모양이 서버(stubs.py)와 다르면 가짜를 쓰고 경고한다."""
    fake = types.ModuleType(COORD_MOD)
    fake.__spec__ = importlib.machinery.ModuleSpec(COORD_MOD, None)
    fake.parse_reply = lambda text, method="keyword": None            # 예전 모양 (choice 없음)
    fake.match_conditions = lambda parse, alternatives, round, unavailable=(): None   # 같은 모양
    sys.modules[COORD_MOD] = fake
    importlib.reload(engine)

    src = engine.sources()
    assert src["parse_reply"] == "stub"
    assert src["match_conditions"] == f"real ({COORD_MOD})"
    w = [x for x in engine.load_warnings() if x.startswith("parse_reply: 진짜 함수 모양이 서버와 다름")]
    assert len(w) == 1 and "choice" in w[0], engine.load_warnings()
    assert not any(x.startswith("match_conditions") for x in engine.load_warnings())
    h = client.get("/health").json()
    assert any(x.startswith("parse_reply: 진짜 함수 모양이 서버와 다름") for x in h["load_warnings"])


def test_engine_signature_diff_details():
    def real(text, choice=None, *, message="", method="llm"):
        pass

    diff = engine.signature_diff(real, engine.stubs.parse_reply)
    assert any("alternatives" in d for d in diff)          # 키워드 전용 인자 하나가 빠짐
    assert engine.signature_diff(engine.stubs.parse_reply, engine.stubs.parse_reply) == []


def test_engine_no_warning_for_current_coord():
    # 진짜 coord.py가 없으면 경고가 없어야 하고, 있으면 모양이 서버와 같아서 경고가 없어야 한다
    importlib.reload(engine)
    assert engine.load_warnings() == []


# ---------- 조율 함수 모양 (최재성 coord.py 기준) ----------

def _sent_section(client) -> str:
    sid = start_round(client)
    r = client.post(f"/coord/{enc(sid)}/message")
    assert r.status_code == 200 and r.json()["sent"], r.text
    return sid


def _sid_with_blocker(client):
    from backend.app.main import store
    start_round(client)
    for c in client.get("/coord").json():
        if store.message_input(c["section_id"]).blocker_prof:
            return c["section_id"]
    pytest.fail("겹친 상대를 찾은 조율 분반이 없음 (데이터 확인)")


def test_message_record_shape_and_opponent_name_shown_by_default(client):
    from backend.app.main import store
    assert client.get("/settings").json() == {"reveal_opponent": True}   # 기본 켬
    sid = _sid_with_blocker(client)
    inp = store.message_input(sid)
    assert inp.reveal is True and inp.round == 1 and inp.alternatives
    assert not ({"seniority", "hired", "priority"} & set(type(inp).model_fields))
    r = client.post(f"/coord/{enc(sid)}/message", json={"method": "keyword"})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert set(rec) >= {"text", "method", "fallback", "problems", "issues", "sent"}
    assert rec["issues"] == [] and rec["sent"] is True
    assert f"{inp.blocker_prof} 교수" in rec["text"] and inp.blocker_course in rec["text"]
    for w in ("연차", "임용", "우선순위"):
        assert w not in rec["text"]
    assert inp.course in rec["text"] and inp.wish in rec["text"]


def test_settings_turn_off_opponent_name(client):
    from backend.app.main import store
    sid = _sid_with_blocker(client)
    r = client.post("/settings", json={"reveal_opponent": False})
    assert r.status_code == 200 and r.json() == {"reveal_opponent": False}
    inp = store.message_input(sid)
    assert inp.reveal is False
    rec = client.post(f"/coord/{enc(sid)}/message").json()
    assert rec["sent"] is True and f"{inp.blocker_prof} 교수" not in rec["text"]
    # 모르는 칸은 422, /reset 하면 기본값(켬)으로
    assert client.post("/settings", json={"reveal_opponent": "maybe"}).status_code == 422
    client.post("/reset")
    assert client.get("/settings").json()["reveal_opponent"] is True


def test_reply_choice_button(client):
    sid = _sent_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": "", "choice": "B"})
    assert r.status_code == 200, r.text
    p = r.json()["parse"]
    assert p["picks"][:1] == ["B"] and p["kind"] in ("수용", "조건부")
    assert r.json()["choice"] == "B"


def test_reply_choice_none_then_confirm_next(client):
    from backend.app.main import store
    sid = _sent_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": "목요일 오후면 됩니다", "choice": "none"})
    assert r.status_code == 200, r.text
    assert r.json()["parse"]["kind"] == "거절"
    prop = r.json()["proposal"]
    assert prop["action"] == "next"
    # 다음 차수로 넘기는 처리안을 [확인] → 시간표는 그대로, 조건만 기록
    before = client.get("/timetable").json()["assignments"]
    r = client.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["action"] == "confirm_next"
    assert r.json()["coord"]["state"] == "NEXT"
    assert client.get("/timetable").json()["assignments"] == before
    # 2차: 확인된 조건이 메시지 입력의 prev_conditions로 들어간다
    assert client.post("/rounds/next").json()["round_no"] == 2
    inp = store.message_input(sid)
    assert inp.round == 2
    cond = prop["conditions"]
    if cond["days"] or cond["slots"] or cond["end_before"]:     # 가짜 parse_reply는 요일을 안 뽑을 수 있다
        assert inp.prev_conditions is not None and inp.prev_conditions.days == cond["days"]
    assert store.get_coord(sid)["prev_conditions"] is not None


def test_unconfirmed_reply_not_used_next_round(client):
    from backend.app.main import store
    sid = _sent_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": "목요일 오후면 됩니다", "choice": "none"})
    assert r.json()["proposal"]["action"] == "next"
    # [확인]을 누르지 않고 다음 차수 → 답장 조건은 반영하지 않는다
    assert client.post("/rounds/next").json()["round_no"] == 2
    assert store.get_coord(sid)["prev_conditions"] is None
    assert store.message_input(sid).prev_conditions is None


def test_decide_proposal_cannot_be_confirmed(client):
    sid = _sent_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": "음 글쎄요"})
    assert r.json()["parse"]["kind"] == "확인 필요"
    assert r.json()["proposal"]["action"] == "decide"
    r = client.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"})
    assert r.status_code == 409 and "action=decide" in r.json()["detail"]


def test_reply_needs_text_or_choice(client):
    sid = _sent_section(client)
    assert client.post(f"/coord/{enc(sid)}/reply", json={"text": "  "}).status_code == 422
    assert client.post(f"/coord/{enc(sid)}/reply", json={"text": "x", "choice": "D"}).status_code == 422


def test_conditions_shape_and_end_before(client):
    sid = _sent_section(client)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": REPLY})
    k = r.json()["parse"]["conditions"]
    assert set(k) == {"days", "slots", "end_before"}
    assert {"day": 2, "time": "17:00"} in k["end_before"]      # 수요일 = 2


def test_reply_note_shown_but_not_used(client, monkeypatch):
    """답장 note(교수 요청)는 응답에 처리안과 함께 나가고, 다음 차수 조건에는 들어가지 않는다."""
    from backend.app.contracts import Conditions, ReplyParse
    from backend.app.main import store
    sid = _sent_section(client)

    # keyword 방식은 note를 비워 둔다 (언어 모델만 채움)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": REPLY, "method": "keyword"})
    assert r.status_code == 200, r.text
    assert r.json()["parse"]["note"] == "" and r.json()["note"] == ""

    # 언어 모델이 note를 채운 경우 (실제 호출 대신 가짜 응답)
    def fake_parse(text, choice=None, *, alternatives=None, message="", method="keyword"):
        return ReplyParse(kind="거절", conditions=Conditions(days=[3], slots=["13:30", "15:00"]),
                          note="실습용 PC가 있는 방", method="llm")

    monkeypatch.setattr(engine, "parse_reply", fake_parse)
    r = client.post(f"/coord/{enc(sid)}/reply", json={"text": "목요일 오후, 실습용 PC 있는 방이면 좋겠어요"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["note"] == "실습용 PC가 있는 방" and j["parse"]["note"] == "실습용 PC가 있는 방"
    assert j["proposal"]["action"] == "next"
    r = client.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"})
    assert r.status_code == 200, r.text
    applied = r.json()["decision"]["applied"]          # 다음 차수로 넘기는 것 = 조건만
    assert applied == {"days": [3], "slots": ["13:30", "15:00"], "end_before": []}
    assert "실습용" not in str(applied)
    nxt = store.get_coord(sid)["next_conditions"]
    assert nxt.slots == ["13:30", "15:00"] and nxt.days == [3]


def test_conditions_slots_validation():
    from backend.app.contracts import Conditions
    assert Conditions(slots=["16:30", "13:30", "13:30"]).slots == ["13:30", "16:30"]   # 교시 순, 중복 없음
    with pytest.raises(Exception):
        Conditions(slots=["13:00"])
    assert Conditions(slots=["13:30"]).is_empty() is False
    assert Conditions().is_empty() is True


def test_stub_fits_uses_slots():
    from backend.app.contracts import Block, Conditions
    from backend.app.stubs import _fits
    pm = Conditions(slots=["13:30", "15:00", "16:30"])
    assert _fits([Block(day="월", start="13:30", slots=1)], pm)[0] is True
    assert _fits([Block(day="월", start="12:00", slots=1)], pm) == (False, "월 12:00~13:15가 가능한 교시 밖")
    assert _fits([Block(day="수", start="15:00", slots=2)], pm)[0] is True          # 15:00·16:30 둘 다 있음
    assert _fits([Block(day="수", start="16:30", slots=2)], pm)[0] is False         # 18:00 교시가 없음
