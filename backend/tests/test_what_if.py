"""AI 도우미 가정 실행(what_if)을 하윤 엔진으로 (DB 모드). 메모리 DB 복사본에서만 계산하고 진짜 DB는 그대로인지 본다.
데이터는 test_db_mode.py 의 가상 데이터를 쓴다."""

import pytest

from backend.tests.test_db_mode import build, client  # noqa: F401  (fixture 재사용)
from backend.app.nlp import assistant
from backend.app.nlp.assistant import AssistantQuery, run_assistant
from backend.app.store import store


def snapshot(db):
    return list(db.con.iterdump())


def free_room(cells, skip=None):
    """지금 초안(store.timetable)에서 그 칸들(["월-16:30", ...])에 아무 수업도 없는 강의실 하나.
    CP-SAT가 점수가 같은 다른 초안을 고를 수 있어서 강의실을 고정하지 않고 그때그때 찾는다 (강의실 겹침을 피함)."""
    busy = {(blk.room, c) for a in store.timetable.assignments if a.section_id != skip
            for blk in a.blocks for c in assistant._cells(blk)}
    room = next((r.id for r in store.list_rooms() if not r.is_lab and all((r.id, c) not in busy for c in cells)),
                None)
    assert room, f"그 칸에 빈 강의실이 없음: {cells}"
    return room


def move_blocks(sid, days=("월", "수"), start="16:30"):
    room = free_room([f"{d}-{start}" for d in days], skip=sid)
    return [{"day": d, "start": start, "slots": 1, "room": room} for d in days], room


@pytest.fixture()
def drafted(client):  # noqa: F811
    c, db = client
    assert c.post("/draft").status_code == 200
    return c, db


def test_move_to_free_place(drafted):
    c, db = drafted
    before = snapshot(db)
    a = next(x for x in store.timetable.assignments if x.section_id == "C2-01")
    blocks, _ = move_blocks("C2-01")
    r = db.what_if({"kind": "move", "section_id": "C2-01", "blocks": blocks})
    assert r["supported"] and r["feasible"] and r["violations"] == 0 and r["changed"][0] == "C2-01"
    assert r["option"] is not None                                   # 엔진도 그 시각에 놓는 안을 찾음
    assert snapshot(db) == before                                    # 진짜 DB는 그대로
    assert a.blocks == next(x for x in store.timetable.assignments if x.section_id == "C2-01").blocks


def test_move_into_blocked_cells_reports_rules(drafted):
    c, db = drafted
    before = snapshot(db)
    # C3 은 화·금 09:00 말고 모두 불가 → 월·수 16:30 (빈 강의실)으로 옮기면 강의실 겹침 없이 불가 칸 위반
    blocks, _ = move_blocks("C3-01")
    r = db.what_if({"kind": "move", "section_id": "C3-01", "blocks": blocks})
    assert r["supported"] and not r["feasible"] and r["clash"] is None and r["violations"] >= 1
    assert all(x["section_id"] == "C3-01" for x in r["rules"]) and r["option"] is None
    assert snapshot(db) == before


def test_move_onto_used_room_is_clash(drafted):
    c, db = drafted
    other = next(x for x in store.timetable.assignments if x.section_id == "C8-01")   # 월 09:00 연강
    b = other.blocks[0]
    blocks = [{"day": b.day, "start": b.start, "slots": 1, "room": b.room},
              {"day": "목", "start": "16:30", "slots": 1, "room": b.room}]
    r = db.what_if({"kind": "move", "section_id": "C2-01", "blocks": blocks})
    assert r["supported"] and not r["feasible"] and "강의실" in (r["clash"] or "")


def test_room_off_resolves_affected_sections(drafted):
    c, db = drafted
    before = snapshot(db)
    used = {}
    for a in store.timetable.assignments:
        for blk in a.blocks:
            used.setdefault(blk.room, set()).add(a.section_id)
    room, secs = max(used.items(), key=lambda kv: len(kv[1]))
    secs = {s for s in secs if s != "C4-01"}                          # 수동 배치 전이라 C4 는 자리 없음
    r = db.what_if({"kind": "room_off", "room": room})
    assert r["supported"] and set(r["changed"]) == secs
    moved = {m["section_id"]: m for m in r["moved"]}
    for s in secs:                                                    # 옮겨졌으면 그 강의실을 안 쓴다, 아니면 못 놓음
        assert (s in moved and room not in moved[s]["after"]) or s in r["unplaced"]
    assert snapshot(db) == before


def test_free_slot_moves_sections_off_it(drafted):
    c, db = drafted
    before = snapshot(db)
    a = next(x for x in store.timetable.assignments if x.section_id == "C2-01")
    b = a.blocks[0]
    r = db.what_if({"kind": "free", "day": b.day, "start": b.start})
    assert r["supported"] and "C2-01" in r["changed"]
    for m in r["moved"]:
        assert f"{b.day} {b.start}" not in m["after"]
    assert snapshot(db) == before


def test_unsupported_is_said_not_made_up(drafted):
    c, db = drafted
    assert db.what_if({"kind": "swap"})["note"] == "이 가정은 아직 계산할 수 없어요."
    r = db.what_if({"kind": "move", "section_id": "C2-01",
                    "blocks": [{"day": "토", "start": "09:00", "slots": 1, "room": "정보과학관 21303"}]})
    assert not r["supported"] and "계산할 수 없어요" in r["note"]
    assert not db.what_if({"kind": "room_off", "room": "없는관 00000"})["supported"]
    assert not db.what_if({"kind": "free", "day": "월", "start": "09:10"})["supported"]


def test_assistant_uses_engine_in_db_mode(drafted):
    c, db = drafted
    a = next(x for x in store.timetable.assignments if x.section_id == "C2-01")
    room = a.blocks[0].room
    out = run_assistant(AssistantQuery(intent="what_if", room=room), store)
    assert "엔진이 다시 놓아" in out["answer"] and assistant.STUB_NOTE not in out["answer"]
    out = run_assistant(AssistantQuery(intent="explain", section_id="C3-01"), store)
    assert "하드 규칙 위반 0건" in out["answer"]
    # 이동 미리보기: 불가 칸으로는 [적용] 제안을 만들지 않는다
    room = free_room(["월-16:30", "수-16:30"], skip="C2-01")
    out = run_assistant(AssistantQuery(intent="move", section_id="C2-01", days=["월", "수"], start="16:30", room=room),
                        store)
    assert out["proposal_id"] and "하드 규칙 위반 없이" in out["answer"]


def test_memory_mode_says_stub():
    """메모리 모드(가짜 엔진) 가정 실행 답에는 가짜 결과 표시가 붙는다 (허위 구현으로 보이지 않게)."""
    from fastapi.testclient import TestClient
    from backend.app.main import app
    c = TestClient(app)
    c.post("/reset")
    c.post("/draft")
    room = next(b.room for a in store.timetable.assignments for b in a.blocks if b.room)
    out = run_assistant(AssistantQuery(intent="what_if", room=room), store)
    assert assistant.STUB_NOTE in out["answer"]
    c.post("/reset")


# ---------- DB 모드 규칙 검사 = 하윤 check_timetable (가짜 check_rules 아님) ----------

def _alt(blocks):
    from backend.app.contracts import Alternative
    day = "월화수목금"
    return Alternative(key="A", meetings=[{"day": day.index(b["day"]), "start": b["start"],
                                           "end": {"09:00": "10:15", "16:30": "17:45"}.get(b["start"], "17:45"),
                                           "room": b["room"]} for b in blocks])


def test_violations_after_follow_real_rules(drafted):
    from backend.app import main
    c, db = drafted
    before = snapshot(db)
    ok, _ = move_blocks("C2-01")                          # 빈 자리 → 위반 0
    bad, _ = move_blocks("C3-01")                         # C3 은 화·금 09:00 말고 모두 불가 → 불가 칸 위반
    v_ok = main._violations_after("C2-01", _alt(ok))
    v_bad = main._violations_after("C3-01", _alt(bad))
    assert v_ok == [] and len(v_bad) >= 1 and len(v_ok) != len(v_bad)
    assert {v.rule for v in v_bad} == {"불가 칸"} and all(v.section_ids == ["C3-01"] for v in v_bad)
    assert "칸 " not in v_bad[0].detail and ("월" in v_bad[0].detail or "수" in v_bad[0].detail)   # 칸 번호 대신 요일 시각
    assert snapshot(db) == before                         # 진짜 DB는 그대로
    assert main._violations() == []                       # 지금 시간표(하윤 check_timetable) 위반 없음


def test_professor_overlap_names_both_sections(drafted):
    from backend.app import main
    c, db = drafted
    c8 = next(x for x in store.timetable.assignments if x.section_id == "C8-01")     # 교수01, 월 09:00 연강
    b = c8.blocks[0]
    room = free_room([f"{b.day}-{b.start}", f"{b.day}-10:30"], skip="C1-01")
    alt = _alt([{"day": b.day, "start": b.start, "room": room}])
    alt.meetings[0].end = "11:45"                                                    # 연강 두 칸
    vs = main._violations_after("C1-01", alt)
    prof = [v for v in vs if v.rule == "교수 겹침"]
    assert prof and set(prof[0].section_ids) == {"C1-01", "C8-01"}
    assert "None" not in prof[0].detail and "교수01" in prof[0].detail


def test_assistant_proposal_reports_after_move_violations(drafted):
    c, db = drafted
    room = free_room(["월-16:30", "수-16:30"], skip="C2-01")
    j = c.post("/assistant", json={"text": f"가상과목2 01분반 월수 16:30 {room.split()[1]}로 옮겨줘"}).json()
    if j.get("proposal_id"):                              # 키워드가 과목을 찾으면: 옮긴 뒤 위반 0
        assert j["violations"] == 0 and j["violation_list"] == []
    out = run_assistant(AssistantQuery(intent="move", section_id="C2-01", days=["월", "수"], start="16:30", room=room),
                        store)
    from backend.app import main
    p = assistant.get_proposal(out["proposal_id"])
    assert len(main._violations_after("C2-01", p["alternative"])) == 0
