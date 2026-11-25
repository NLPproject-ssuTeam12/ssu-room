"""수업(회차)마다 강의실이 다른 분반 (Block.room).

솔버는 한 분반의 두 수업을 다른 강의실에 놓을 수 있다 (예: 화 문화관 03407, 목 정보과학관 21304).
Assignment.room은 대표 강의실(첫 수업의 강의실)로 남기고, 수업마다 강의실은 blocks[].room에 둔다.
"""

import os
from pathlib import Path
from urllib.parse import quote

import pytest

from backend.app import stubs
from backend.app.contracts import (
    Alternative, Assignment, Block, Meeting, Section, Timetable, block_room, blocks_to_meetings, dump,
    meetings_to_blocks, parse, set_place, set_room,
)
from backend.app.export import timetable_rows

R1, R2 = "문화관 03407", "정보과학관 21304"


def split(sid="X-02"):
    """화 13:30 문화관 03407 / 목 13:30 정보과학관 21304."""
    return Assignment(section_id=sid, blocks=[Block(day="화", start="13:30", slots=1, room=R1),
                                              Block(day="목", start="13:30", slots=1, room=R2)])


# ---------- 모델 규칙 ----------

def test_room_rules():
    # 블록에 강의실이 없으면 대표 강의실로 채운다 (옛 모양 데이터)
    old = parse(Assignment, {"section_id": "A", "room": R1,
                             "blocks": [{"day": "월", "start": "09:00", "slots": 1},
                                        {"day": "수", "start": "09:00", "slots": 1}]})
    assert [b.room for b in old.blocks] == [R1, R1]
    # 대표 강의실이 없으면 첫 수업의 강의실
    a = split()
    assert a.room == R1 and [block_room(a, b) for b in a.blocks] == [R1, R2]
    # block_room: Block.room이 비면 Assignment.room
    a.blocks[1].room = None
    assert block_room(a, a.blocks[1]) == R1
    # 강의실만 바꾸면 분반 전체 수업에 적용
    a = set_room(split(), "정보과학관 21303")
    assert a.room == "정보과학관 21303" and {b.room for b in a.blocks} == {"정보과학관 21303"}
    # 응답(JSON)에 블록마다 room이 나온다
    assert [b["room"] for b in dump(split())["blocks"]] == [R1, R2]


def test_meetings_round_trip_keeps_each_room():
    ms = blocks_to_meetings(split().blocks)
    assert [m.room for m in ms] == [R1, R2]
    blocks, rep = meetings_to_blocks(ms)
    assert [b.room for b in blocks] == [R1, R2] and rep == R1
    # room을 주면 모든 수업을 그 강의실로 (예전 호출 모양)
    assert {m.room for m in blocks_to_meetings(split().blocks, "정보과학관 21303")} == {"정보과학관 21303"}


# ---------- 규칙 검사 ----------

def test_check_rules_uses_each_meeting_room():
    other_thu = Assignment(section_id="Y-01", blocks=[Block(day="목", start="13:30", slots=1)], room=R2)
    hits = stubs.check_rules(Timetable(assignments=[split(), other_thu]))
    assert len(hits) == 1 and set(hits[0].section_ids) == {"X-02", "Y-01"} and R2 in hits[0].detail
    # 목요일에 대표 강의실(문화관)을 쓰는 분반과는 겹치지 않는다 (목요일 수업은 정보과학관)
    other_r1 = Assignment(section_id="Y-01", blocks=[Block(day="목", start="13:30", slots=1)], room=R1)
    assert stubs.check_rules(Timetable(assignments=[split(), other_r1])) == []


# ---------- 대안 반영 ----------

def test_reassign_keeps_each_meeting_room():
    alt = Alternative(key="A", meetings=[Meeting(day=0, start="12:00", end="13:15", room=R1),
                                         Meeting(day=2, start="12:00", end="13:15", room=R2)])
    tt = stubs.reassign(Timetable(assignments=[split()]), "X-02", alt)
    a = tt.assignments[0]
    assert [(b.day, b.start, b.room) for b in a.blocks] == [("월", "12:00", R1), ("수", "12:00", R2)]
    assert a.room == R1


# ---------- 엑셀 ----------

def test_export_pairs_time_and_room():
    secs = [Section(id="X-02", code="2150000002", name="가상과목", weekly_blocks=2, professor="교수01")]
    a = split()
    a.blocks.reverse()   # 순서가 섞여 있어도 요일 순으로 짝지어 보인다
    row = timetable_rows(Timetable(assignments=[a]), secs)[0]
    assert row["요일·시간"] == "화 13:30~14:45 / 목 13:30~14:45"
    assert row["강의실"] == f"{R1} / {R2}"


# ---------- API (실제 데이터) ----------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
needs_data = pytest.mark.skipif(not (DATA / "sections.json").exists(), reason=f"{DATA} 에 데이터가 없음")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    c = TestClient(app)
    assert c.post("/reset").status_code == 200
    yield c
    c.post("/reset")


def _split_in_store(sid):
    """시간표에서 그 분반의 둘째 수업만 다른 강의실로 바꾼다. (첫 강의실, 둘째 강의실)."""
    from backend.app.store import store
    a = next(x for x in store.timetable.assignments if x.section_id == sid)
    first = a.room
    second = next(r.id for r in store.list_rooms() if r.id != first)
    blocks = [b.model_copy(update={"room": first if i == 0 else second}) for i, b in enumerate(a.blocks)]
    set_place(a, blocks)
    return first, second


def _sid(name, num):
    from backend.app.store import store
    return next(s.id for s in store.list_sections() if s.name == name and s.code[-2:] == num)


@needs_data
def test_api_timetable_and_assistant_show_both_rooms(client):
    client.post("/draft")
    sid = _sid("확률및통계", "02")
    r1, r2 = _split_in_store(sid)

    a = next(x for x in client.get("/timetable").json()["assignments"] if x["section_id"] == sid)
    assert a["room"] == r1 and [b["room"] for b in a["blocks"]] == [r1, r2]

    # 설명: 수업마다 강의실
    ans = client.post("/assistant", json={"text": "확통 2분반 왜 밀렸어?"}).json()["answer"]
    assert r1 in ans and r2 in ans and " / " in ans

    # 이동: 미리보기에 두 강의실, [적용] 뒤에도 수업마다 강의실 유지
    j = client.post("/assistant", json={"text": "확통 월수 12시로 옮겨줘"}).json()
    assert j["proposal_id"], j["answer"]
    after = j["changes"][0]["after"]
    assert f"월 12:00~13:15 {r1}" in after and f"수 12:00~13:15 {r2}" in after
    r = client.post("/assistant/apply", json={"proposal_id": j["proposal_id"], "reason": "테스트"})
    assert r.status_code == 200, r.text
    a = next(x for x in client.get("/timetable").json()["assignments"] if x["section_id"] == sid)
    assert [(b["day"], b["start"], b["room"]) for b in a["blocks"]] == [("월", "12:00", r1), ("수", "12:00", r2)]
    assert a["room"] == r1


@needs_data
def test_assistant_room_only_change_applies_to_all_meetings(client):
    from backend.app.nlp.assistant import AssistantQuery, run_assistant
    from backend.app.store import store
    client.post("/draft")
    sid = _sid("확률및통계", "02")
    r1, r2 = _split_in_store(sid)
    target = next(r.id for r in store.list_rooms() if r.id not in (r1, r2))
    out = run_assistant(AssistantQuery(intent="what_if", section_id=sid, room=target), store)
    assert out["changes"][0]["after"].endswith(f"· {target}")      # 두 수업 모두 그 강의실


@needs_data
def test_coord_decide_keeps_each_meeting_room(client):
    from backend.app.store import store
    client.post("/draft")
    client.post("/rounds/next")
    sid = client.get("/coord").json()[0]["section_id"]
    item = store.get_coord(sid)
    base = item["alternatives"][0]
    rooms = [r.id for r in store.list_rooms()][:2]
    two = base.model_copy(update={"meetings": [m.model_copy(update={"room": rooms[i % 2]})
                                               for i, m in enumerate(base.meetings)]})
    store.update_coord(sid, alternatives=[two] + list(item["alternatives"][1:]))
    r = client.post(f"/coord/{quote(sid, safe='')}/decide", json={"action": "edit", "reason": "테스트", "choice": two.key})
    assert r.status_code == 200, r.text
    a = next(x for x in client.get("/timetable").json()["assignments"] if x["section_id"] == sid)
    assert [b["room"] for b in a["blocks"]] == [m.room for m in two.meetings]
    assert a["room"] == two.meetings[0].room
