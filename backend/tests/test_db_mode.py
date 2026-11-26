"""DB 모드(SSUROOM_ENGINE=solver) 조율 한 바퀴: 희망 → 초안 → 조율 대상(OPEN·HOLD·NO_OPTION) → 메시지 → 답장
(A+B 순서, 기타 조건 있음/없음, 지금 자리 그대로) → 조교 결정(확인·수정·유지·따로 연락) → 다음 차수(조건 쌓기·보낸 대안 제외)
→ 확정 → 엑셀. 하윤 test_data 방식으로 메모리 DB를 직접 채운다 (가상 데이터). 재성 함수는 keyword 방식."""

import io
import os
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("ortools")
REPO_ROOT = Path(__file__).resolve().parents[2]
if not (REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real") / "sections.json").exists():
    pytest.skip("서버 store가 읽을 data/private 데이터가 없어 건너뜀", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import dbmode  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.solver import adapter as ad  # noqa: E402
from backend.app.store import store  # noqa: E402
from backend.tests.helpers import free_meetings  # noqa: E402

hdb, sc = ad.load_haeyoon()
import seed_time_slot  # noqa: E402

DAYS = "월화수목금"
CELLS = [(d, t) for d in DAYS for t in ("09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30")]

# (서버 분반 id, 과목 id, 분반, 교수, 희망 칸, 불가 칸)
#  - 과목 1·6·7 (주 1회 연강): 같은 교수의 과목 8·9·10이 그 두 칸만 되므로 희망 칸을 못 받음 → MISMATCH (자동 보냄)
#  - 과목 2·3: 교수 2의 과목 3이 화·금 09:00만 되고, 과목 2는 화·목 09:00 희망 → 과목 2는 일부만 어긋남(PARTIAL, HOLD)
#  - 과목 4: 모든 칸이 불가 → 못 놓음(UNPLACED), 대안도 없음(NO_OPTION)
ONLY = lambda keep: [c for c in CELLS if c not in keep]   # noqa: E731
MON, TUE, WED = [("월", "09:00"), ("월", "10:30")], [("화", "13:30"), ("화", "15:00")], [("수", "13:30"), ("수", "15:00")]
SECS = [
    ("C1-01", 1, 1, "교수01", MON, []),
    ("C8-01", 8, 1, "교수01", [], ONLY(MON)),
    ("C2-01", 2, 1, "교수02", [("화", "09:00"), ("목", "09:00")], []),
    ("C3-01", 3, 1, "교수02", [], ONLY([("화", "09:00"), ("금", "09:00")])),
    ("C4-01", 4, 1, "교수04", [], ONLY([])),
    ("C6-01", 6, 1, "교수03", TUE, []),
    ("C9-01", 9, 1, "교수03", [], ONLY(TUE)),
    ("C7-01", 7, 1, "교수05", WED, []),
    ("C10-01", 10, 1, "교수05", [], ONLY(WED)),
]
LONG = {1, 6, 7, 8, 9, 10}   # 주 1회 연강 MUST
ROOMS = [("정보과학관", "21303", 60, 0), ("정보과학관", "21304", 60, 0), ("문화관", "03407", 60, 1)]


def build():
    c = hdb.connect(":memory:")
    c.close()
    import sqlite3
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript((REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    grid = seed_time_slot.seed(c)
    q = c.execute
    q("INSERT INTO department(id, name) VALUES (1, 'AI소프트웨어학부')")
    q("INSERT INTO term(id, year, semester, grid_id) VALUES (1, 2026, '2', ?)", (grid,))
    q("INSERT INTO round(id, term_id, round_no, deadline_at) VALUES (1, 1, 1, '2026-12-31')")
    q("INSERT INTO user(id, role, name, password_hash) VALUES (100, 'TA', '조교', 'x')")
    profs = sorted({s[3] for s in SECS})
    uid = {p: i for i, p in enumerate(profs, start=1)}
    for p, i in uid.items():
        q("INSERT INTO user(id, role, name, password_hash) VALUES (?, 'PROF', ?, 'x')", (i, p))
    for i, (b, no, cap, lab) in enumerate(ROOMS, start=1):
        bid = q("SELECT id FROM building WHERE name=?", (b,)).fetchone()
        bid = bid[0] if bid else q("INSERT INTO building(name) VALUES (?)", (b,)).lastrowid
        q("INSERT INTO room(id, building_id, room_no, capacity, is_lab) VALUES (?,?,?,?,?)", (i, bid, no, cap, lab))
    for cid in sorted({s[1] for s in SECS}):
        first = next(s for s in SECS if s[1] == cid)
        q("""INSERT INTO course(id, term_id, department_id, code, name, professor_id, category, target_year,
                                session_count, slots_per_session) VALUES (?,1,1,?,?,?, '전공선택', '2', 2, 1)""",
          (cid, f"2150{cid:04d}", f"가상과목{cid}", uid[first[3]]))
    slot = {(d, st): i for i, d, st in q("SELECT id, day, start_time FROM time_slot")}
    mapping = {"term_id": 1, "round_id": 1, "ta_id": 100, "sections": {}, "rooms": {}}
    for sid, cid, sec, prof, prefer, block in SECS:
        q("INSERT INTO course_section(course_id, section_no, professor_id, enrollment) VALUES (?,?,?,30)",
          (cid, sec, uid[prof]))
        single = "MUST" if cid in LONG else "NONE"
        rid = q("""INSERT INTO course_response(round_id, course_id, section_no, professor_id, lab_requirement,
                                               single_day_pref) VALUES (1,?,?,?, 'NONE', ?)""",
                (cid, sec, uid[prof], single)).lastrowid
        for x in prefer:
            q("INSERT INTO response_slot VALUES (?,?, 'PREFER')", (rid, slot[x]))
        for x in block:
            q("INSERT INTO response_slot VALUES (?,?, 'BLOCK')", (rid, slot[x]))
        mapping["sections"][sid] = dict(course_id=cid, section_no=sec, manual=False, code=f"2150{cid:04d}{sec:02d}",
                                        name=f"가상과목{cid}", division=None, category_orig="전선-AI소프트웨어",
                                        category="전공선택", professor=prof, enrollment=30, year=2, shape="TWICE")
    c.commit()
    return c, mapping


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SSUROOM_ENGINE", "solver")
    con, mapping = build()
    db = dbmode.DBMode(con, mapping, draft_time_limit=10, alt_time_limit=5)
    dbmode.use(db)
    db.sync(store)
    yield TestClient(app), db
    dbmode.use(None)
    ad.configure(None)
    monkeypatch.delenv("SSUROOM_ENGINE")
    store.reset()


def enc(sid):
    return quote(sid, safe="")


def coord(c):
    return {x["section_id"]: x for x in c.get("/coord").json()}


def test_db_mode_full_loop(client):
    c, db = client
    assert c.get("/health").json()["stage"] == "COLLECT"

    # ---- 희망 (분반마다, 미회신 분반도 됨) ----
    w = {"section_id": "C2-01", "professor": "교수02", "cells": {"화-09:00": "PREFER", "목-09:00": "PREFER"},
         "lab": "NONE", "single_day": "NONE", "building": "정보과학관", "note": "실습 조교 배치 부탁드립니다"}
    r = c.post("/wishes", json=w)
    assert r.status_code == 200, r.text
    assert db.q("SELECT COUNT(*) FROM other_request WHERE response_id IS NOT NULL").fetchone()[0] == 1
    assert c.post("/wishes/pair", json={"section_id": "C1-01", "mode": "NONE"}).status_code == 200

    # ---- 초안 → 조율 대상 ----
    r = c.post("/draft")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["stage"] == "DRAFT" and d["violations"] == 0
    items = coord(c)
    kinds = {sid: (x["kind"], x["state"]) for sid, x in items.items()}
    states = [s for _, s in kinds.values()]
    assert {"OPEN", "HOLD", "NO_OPTION"} <= set(states), kinds
    assert kinds["C2-01"] == ("PARTIAL", "HOLD")
    no_opt = "C4-01"
    assert kinds[no_opt] == ("UNPLACED", "NO_OPTION") and items[no_opt]["current"] is None
    opens = sorted(sid for sid, (k, s) in kinds.items() if s == "OPEN")
    a1, a6, a7 = "C1-01", "C6-01", "C7-01"
    assert opens == [a1, a6, a7] and all(kinds[s][0] == "MISMATCH" for s in opens), kinds
    assert c.post(f"/coord/{enc(a1)}/message").status_code == 409          # 차수 전에는 못 보냄

    # ---- 1차: OPEN 은 자동으로 보냄 ----
    r = c.post("/rounds/next", json={"method": "keyword"})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["sent"]) == opens
    items = coord(c)
    assert all(items[s]["state"] == "SENT" and items[s]["message"] for s in opens)
    assert "지금은" in items[a1]["message"]                                  # 지금 자리 줄 (current)
    assert c.post(f"/coord/{enc('C2-01')}/message").status_code == 409     # HOLD 는 조교가 [보내기] 먼저

    # HOLD → [보내기] → 메시지 → 지금 자리 그대로 → [확인] = 유지
    r = c.post(f"/coord/{enc('C2-01')}/hold", json={"send": True})
    assert r.status_code == 200 and r.json()["coord"]["state"] == "OPEN"
    assert c.post(f"/coord/{enc('C2-01')}/message").json()["sent"]
    r = c.post(f"/coord/{enc('C2-01')}/reply", json={"choices": ["KEEP"]})
    assert r.status_code == 200 and r.json()["proposal"]["action"] == "keep"
    r = c.post(f"/coord/{enc('C2-01')}/decide", json={"action": "confirm"})
    assert r.status_code == 200 and r.json()["coord"]["state"] == "KEPT"

    # NO_OPTION → [확인] → 따로 연락 → 수동 배치(고정, 경고만)
    assert c.post(f"/coord/{enc(no_opt)}/ack").json()["coord"]["state"] == "OFFLINE"
    meet = free_meetings(no_opt)          # 지금 시간표에서 빈 강의실·교수가 빈 시각 (초안마다 다름)
    r = c.post(f"/coord/{enc(no_opt)}/manual", json={"meetings": meet, "reason": "교수님과 통화"})
    assert r.status_code == 200, r.text
    assert r.json()["coord"]["state"] == "RESOLVED" and r.json()["violations"] >= 1    # 불가 칸이라 경고
    cid, sec = db.section_key(no_opt)
    assert db.q("""SELECT status, locked FROM timetable_section WHERE timetable_id=? AND course_id=? AND section_no=?""",
                (db.current_tt(), cid, sec)).fetchone() == ("MANUAL", 1)

    # A+B, 글로 순서(B 먼저) → [확인] → pick_best(respect_order) → 새 시간표 버전
    r = c.post(f"/coord/{enc(a1)}/reply", json={"choices": ["A", "B"], "text": "B가 좋고 안 되면 A"})
    assert r.status_code == 200, r.text
    assert r.json()["parse"]["picks"] == ["B", "A"] and r.json()["parse"]["ordered"] is True
    before, warned = db.current_tt(), len(db.violations())          # 수동 배치 경고는 이미 있음
    r = c.post(f"/coord/{enc(a1)}/decide", json={"action": "confirm"})
    assert r.status_code == 200, r.text
    assert r.json()["coord"]["state"] == "RESOLVED" and r.json()["violations"] == warned   # 새 위반 없음
    assert db.current_tt() != before
    kind, parent = db.q("SELECT kind, parent_id FROM timetable WHERE id=?", (db.current_tt(),)).fetchone()
    assert kind == "TA_EDIT" and parent == before
    b_alt = next(x for x in items[a1]["alternatives"] if x["key"] == "B")
    got = next(x for x in c.get("/timetable").json()["assignments"] if x["section_id"] == a1)
    assert [(b["day"], b["start"]) for b in got["blocks"]] == [(DAYS[m["day"]], m["start"]) for m in b_alt["meetings"]]

    # 기타 조건 없음("다 어렵다") → 조교가 정함 → [따로 연락]
    r = c.post(f"/coord/{enc(a7)}/reply", json={"choices": ["ETC"], "text": "위 안은 다 어렵습니다"})
    assert r.json()["proposal"]["action"] == "decide"
    r = c.post(f"/coord/{enc(a7)}/decide", json={"action": "offline"})
    assert r.status_code == 200 and r.json()["coord"]["state"] == "OFFLINE"

    # 기타 조건 있음("목요일이면") → [확인] = 다음 차수(조건)
    r = c.post(f"/coord/{enc(a6)}/reply", json={"choices": ["ETC"], "text": "목요일이면 됩니다"})
    assert r.json()["proposal"]["action"] == "next"
    r = c.post(f"/coord/{enc(a6)}/decide", json={"action": "confirm"})
    assert r.status_code == 200 and r.json()["coord"]["state"] == "NEXT"
    sent1 = {tuple((m["day"], m["start"]) for m in x["meetings"]) for x in coord(c)[a6]["alternatives"]}

    # ---- 2차: 이어받은 조건(목요일)으로 새 대안, 1차에 보낸 안 제외, 자동 발송 ----
    r = c.post("/rounds/next", json={"method": "keyword"})
    assert r.status_code == 200, r.text
    assert r.json()["round_no"] == 2 and a6 in r.json()["sent"]
    assert r.json()["next_opened"][0]["conditions"] == {"day_slots": {"3": []}, "end_before": []}
    item = coord(c)[a6]
    assert item["round_no"] == 2 and item["state"] == "SENT" and item["alternatives"]
    for x in item["alternatives"]:
        ms = tuple((m["day"], m["start"]) for m in x["meetings"])
        assert any(m["day"] == 3 for m in x["meetings"]) and ms not in sent1
    assert item["prev_conditions"] == {"day_slots": {"3": []}, "end_before": []}

    # 2차 답장 → 조교 [수정](사유 필수)
    r = c.post(f"/coord/{enc(a6)}/reply", json={"choices": ["ETC"], "text": "잘 모르겠어요"})
    assert r.status_code == 200
    assert c.post(f"/coord/{enc(a6)}/decide", json={"action": "edit", "choice": "A"}).status_code == 422
    r = c.post(f"/coord/{enc(a6)}/decide", json={"action": "edit", "choice": "A", "reason": "교수님과 통화로 A안"})
    assert r.status_code == 200, r.text
    assert r.json()["coord"]["state"] == "RESOLVED"
    assert db.q("SELECT reason FROM timetable WHERE id=?", (db.current_tt(),)).fetchone()[0] == "교수님과 통화로 A안"

    # 따로 연락한 C7 → 수동 배치
    r = c.post(f"/coord/{enc(a7)}/manual", json={"meetings": free_meetings(a7)})
    assert r.status_code == 200, r.text

    # ---- 확정 → 엑셀 ----
    r = c.post("/finalize")
    assert r.status_code == 200 and r.json()["stage"] == "FINAL"
    assert db.q("SELECT kind FROM timetable WHERE id=?", (db.current_tt(),)).fetchone()[0] == "FINAL"
    r = c.get("/export.xlsx")
    assert r.status_code == 200
    from openpyxl import load_workbook
    rows = list(load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))
    assert "가상/가명" in rows[0][0] and len(rows) - 2 == len(SECS)

    # 처음으로: 조율·시간표 기록만 지워지고 희망은 남는다
    assert c.post("/reset").json()["stage"] == "COLLECT"
    assert db.current_tt() is None and db.q("SELECT COUNT(*) FROM proposal").fetchone()[0] == 0
    assert db.q("SELECT COUNT(*) FROM course_response").fetchone()[0] == len(SECS)


def test_db_mode_reply_rules(client):
    c, db = client
    c.post("/draft")
    c.post("/rounds/next")
    sid = next(s for s, x in coord(c).items() if x["state"] == "SENT")
    url = f"/coord/{enc(sid)}/reply"
    assert c.post(url, json={"choices": ["ETC"], "text": ""}).status_code == 422      # 기타는 글 필수
    assert c.post(url, json={"choices": ["KEEP", "A"]}).status_code == 422             # KEEP은 A·B·C와 같이 못 고름
    # 못 놓은 분반은 KEEP 불가 (DB add_reply 도 막음)
    unplaced = next(s for s, x in coord(c).items() if x["kind"] == "UNPLACED")
    assert coord(c)[unplaced]["current"] is None
    # 글만 보내도(예전 화면) 기타로 받는다
    r = c.post(url, json={"text": "A안 괜찮습니다"})
    assert r.status_code == 200, r.text
    mid = db.q("SELECT MAX(id) FROM message WHERE kind='REPLY'").fetchone()[0]
    assert [x["choice"] for x in hdb.reply_choices(db.con, mid)] == ["ETC"]
    label, model = db.q("SELECT label, model_name FROM reply_interpretation WHERE message_id=?", (mid,)).fetchone()
    assert label in ("ACCEPT", "CONDITIONAL", "REJECT", "UNCLEAR") and model == "keyword"


def test_late_next_is_carried_to_a_later_round(client):
    """1차 답장 대기 → 2차 시작 → 1차 답장을 확인해 NEXT → 3차 시작 때 그 안건이 3차에 열린다."""
    c, db = client
    c.post("/draft")
    c.post("/rounds/next")                                              # 1차, OPEN 은 자동 발송
    sid = "C6-01"
    assert coord(c)[sid]["state"] == "SENT"
    p1 = coord(c)[sid]["proposal_id"]
    assert c.post("/rounds/next").json()["round_no"] == 2               # 답장 대기 중 2차로
    assert coord(c)[sid]["proposal_id"] == p1                           # 아직 1차 안건
    r = c.post(f"/coord/{enc(sid)}/reply", json={"choices": ["ETC"], "text": "목요일이면 됩니다"})
    assert r.json()["proposal"]["action"] == "next"
    assert c.post(f"/coord/{enc(sid)}/decide", json={"action": "confirm"}).json()["coord"]["state"] == "NEXT"
    assert db.pending_next(3) == [(p1, 1)]
    r = c.post("/rounds/next")                                          # 3차
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["round_no"] == 3 and [o["from_round"] for o in j["next_opened"]] == [1]
    item = coord(c)[sid]
    assert item["round_no"] == 3 and item["proposal_id"] != p1 and item["state"] in ("SENT", "NO_OPTION")
    assert db.q("SELECT prev_proposal_id FROM proposal WHERE id=?", (item["proposal_id"],)).fetchone()[0] == p1
    assert item["prev_conditions"] == {"day_slots": {"3": []}, "end_before": []}   # 1차 조건 이어받음
    assert db.pending_next(3) == []                                     # 두 번 열지 않음


# ---------- 분반 연강·교차 읽기 (GET /wishes pairs) ----------

@pytest.fixture()
def pair_client(monkeypatch):
    """test 데이터에 같은 교수가 한 과목 분반 둘을 맡은 과목(11)을 더한다."""
    monkeypatch.setenv("SSUROOM_ENGINE", "solver")
    con, mapping = build()
    q = con.execute
    q("INSERT INTO user(id, role, name, password_hash) VALUES (50, 'PROF', '교수06', 'x')")
    q("""INSERT INTO course(id, term_id, department_id, code, name, professor_id, category, target_year, session_count,
                            slots_per_session) VALUES (11, 1, 1, '21500011', '가상과목11', 50, '전공선택', '2', 2, 1)""")
    for sec in (1, 2):
        q("INSERT INTO course_section(course_id, section_no, professor_id, enrollment) VALUES (11, ?, 50, 30)", (sec,))
        q("""INSERT INTO course_response(round_id, course_id, section_no, professor_id, lab_requirement, single_day_pref)
             VALUES (1, 11, ?, 50, 'NONE', 'NONE')""", (sec,))
        mapping["sections"][f"C11-0{sec}"] = dict(course_id=11, section_no=sec, manual=False, code=f"215000110{sec}",
                                                 name="가상과목11", division=None, category_orig="전선-AI소프트웨어",
                                                 category="전공선택", professor="교수06", enrollment=30, year=2,
                                                 shape="TWICE")
    con.commit()
    db = dbmode.DBMode(con, mapping, draft_time_limit=10, alt_time_limit=5)
    dbmode.use(db)
    db.sync(store)
    yield TestClient(app), db
    dbmode.use(None)
    ad.configure(None)
    monkeypatch.delenv("SSUROOM_ENGINE")
    store.reset()


def test_pairs_round_trip_db(pair_client):
    c, db = pair_client
    assert c.get("/wishes").json()["pairs"] == []
    body = {"section_id": "C11-02", "mode": "BACK_TO_BACK", "order": ["C11-02", "C11-01"]}
    r = c.post("/wishes/pair", json=body)
    assert r.status_code == 200, r.text
    got = c.get("/wishes").json()["pairs"]
    assert got == [body]                                        # 보낸 모양 그대로 다시 채울 수 있다
    assert c.post("/wishes/pair", json=got[0]).status_code == 200   # 받은 값을 그대로 다시 보내도 됨
    assert c.post("/wishes/pair", json={"section_id": "C11-01", "mode": "NONE"}).status_code == 200
    assert c.get("/wishes").json()["pairs"] == []
    assert set(c.get("/wishes").json()) >= {"wishes", "professors", "pairs"}   # 기존 칸은 그대로


# ---------- 분반 수강 인원 (DB 모드: course_section.enrollment) ----------

def test_enrollment_saved_and_room_capacity_used(client):
    c, db = client
    db.q("UPDATE room SET capacity=40 WHERE id=1")                       # 정보과학관 21303 은 40명
    db.con.commit()
    db.sync(store)
    w = {"section_id": "C2-01", "professor": "교수02", "cells": {"화-09:00": "PREFER", "목-09:00": "PREFER"},
         "enrollment": 50}
    assert c.post("/wishes", json=dict(w, enrollment=47)).status_code == 422
    r = c.post("/wishes", json=w)
    assert r.status_code == 200, r.text
    cid, sec = db.section_key("C2-01")
    assert db.q("SELECT enrollment FROM course_section WHERE course_id=? AND section_no=?",
                (cid, sec)).fetchone()[0] == 50
    assert next(x for x in c.get("/wishes").json()["wishes"] if x["section_id"] == "C2-01")["enrollment"] == 50
    assert next(s for s in c.get("/sections").json() if s["id"] == "C2-01")["enrollment"] == 50
    # 정원(40)보다 많은 분반은 그 강의실을 쓰지 않는다 (엔진 하드 규칙)
    assert c.post("/draft").status_code == 200
    a = next(x for x in c.get("/timetable").json()["assignments"] if x["section_id"] == "C2-01")
    assert a["blocks"] and all(b["room"] != "정보과학관 21303" for b in a["blocks"])
    assert db.q("""SELECT COUNT(*) FROM assignment WHERE timetable_id=? AND course_id=? AND section_no=? AND room_id=1""",
                (db.current_tt(), cid, sec)).fetchone()[0] == 0


def test_enrollment_bigger_than_every_room_is_unplaced(client):
    c, db = client
    w = {"section_id": "C2-01", "professor": "교수02", "cells": {"화-09:00": "PREFER", "목-09:00": "PREFER"},
         "enrollment": 65}                                                # 강의실은 모두 60명
    assert c.post("/wishes", json=w).status_code == 200
    c.post("/draft")
    item = coord(c)["C2-01"]
    assert item["kind"] == "UNPLACED"


def test_confirm_uses_fresh_room_when_stored_room_is_taken(client):
    """대안 B의 강의실을 그사이 다른 분반(수동 배치)이 쓰면, [확인]은 pick_best 가 고른 같은 시각 다른 강의실로 반영한다.
    같은 묶음에 다른 방이 없으면 DB 제약 오류(UNIQUE)가 아니라 '놓을 수 없습니다'로 거부한다."""
    c, db = client
    c.post("/draft")
    c.post("/rounds/next")
    a1 = "C1-01"
    b = next(x for x in coord(c)[a1]["alternatives"] if x["key"] == "B")
    assert c.post(f"/coord/{enc('C4-01')}/ack").status_code == 200
    r = c.post(f"/coord/{enc('C4-01')}/manual", json={"meetings": b["meetings"]})   # B 자리를 C4 가 차지
    assert r.status_code == 200, r.text
    assert c.post(f"/coord/{enc(a1)}/reply", json={"choices": ["B"]}).status_code == 200
    r = c.post(f"/coord/{enc(a1)}/decide", json={"action": "confirm"})
    if r.status_code == 200:
        applied = r.json()["decision"]["applied"]["meetings"]
        assert [(m["day"], m["start"]) for m in applied] == [(m["day"], m["start"]) for m in b["meetings"]]
        assert any(m["room"] != n["room"] for m, n in zip(applied, b["meetings"]))   # 다른 강의실
    else:
        assert r.status_code == 409 and "UNIQUE" not in r.json()["detail"], r.text
