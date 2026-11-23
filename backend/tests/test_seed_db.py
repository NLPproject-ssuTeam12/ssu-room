"""시드 스크립트(backend/tools/seed_db.py) 검사. 작은 가짜 데이터로 본다 (실제 데이터 검사는 없으면 건너뜀)."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from backend.tools import seed_db as sd

REPO_ROOT = Path(__file__).resolve().parents[2]


def sec(sid, code, name="가상과목", prof="교수01", cat="전선-AI소프트웨어", year=2, weekly=2, enroll=30, division=None):
    return {"id": sid, "code": code, "name": name, "division": division, "year": year, "category": cat,
            "enrollment": enroll, "weekly_blocks": weekly, "professor": prof, "lab_need": "NONE"}


def wish(sid, prof="교수01", cells=None, lab="NONE", building=None, note=""):
    return {"section_id": sid, "professor": prof, "cells": cells or {}, "must": False, "lab": lab,
            "single_day": "NONE", "building": building, "room": None, "note": note}


def twice(sid, start="09:00", room="정보과학관 21303"):
    return {"section_id": sid, "room": room, "blocks": [{"day": "월", "start": start, "slots": 1},
                                                         {"day": "수", "start": start, "slots": 1}]}


def long_(sid, room="정보과학관 21303"):
    return {"section_id": sid, "room": room, "blocks": [{"day": "화", "start": "13:30", "slots": 2}]}


ROOMS = [{"id": "정보과학관 21303", "building": "정보과학관", "room_no": "21303", "capacity": 60, "is_lab": False,
          "estimated": True},
         {"id": "문화관 03407", "building": "문화관", "room_no": "03407", "capacity": 60, "is_lab": True,
          "estimated": False}]


def fake():
    sections = [
        # 과목 A: 분반 02·05만 있음(빈칸) → 1·2로 다시 매김. 같은 교수, 희망이 다름
        sec("2150000005", "2150000005", "자료구조", cat="전필-AI소프트웨어"),
        sec("2150000002", "2150000002", "자료구조", cat="전필-AI소프트웨어"),
        # 과목 B: 교양필수 카테고리, 다른 교수
        sec("2150000101", "2150000101", "글쓰기", prof="교수02", cat="교필-공통", year=1),
        # 과목 C: MANUAL (주 4칸)
        sec("2150000201", "2150000201", "현장실습", prof="교수03", weekly=4),
    ]
    wishes = [
        wish("2150000002", cells={"월-09:00": "PREFER", "수-09:00": "PREFER", "금-09:00": "BLOCK"}, building="문화관"),
        wish("2150000005", cells={"월-09:00": "BLOCK", "화-10:30": "PREFER", "토-09:00": "PREFER"}, lab="MUST",
             building="문화관", note="좌석 여유가 있으면 좋겠습니다."),
        wish("2150000101", prof="교수02", cells={"목-12:00": "PREFER"}),
        wish("2150000201", prof="교수03"),
    ]
    timetable = {"assignments": [twice("2150000002"), long_("2150000005"), twice("2150000101", "10:30"),
                                 {"section_id": "2150000201", "room": "문화관 03407",
                                  "blocks": [{"day": "토", "start": "09:00", "slots": 4}]}]}
    return sections, wishes, timetable


def test_category_mapping():
    assert sd.db_category("전필-AI소프트웨어") == "전공필수"
    assert sd.db_category("교필-공통") == "교양필수"
    assert sd.db_category("전선-정보보호") == "전선-정보보호"      # 솔버가 쓰지 않는 값은 그대로
    assert sd.department_of("전선-정보보호") == "정보보호학과"


def test_plan_renumbers_sections_and_excludes_manual():
    plan = sd.build_plan(*fake())
    assert plan["manual"] == ["2150000201"]
    assert [c["code"] for c in plan["courses"]] == ["21500000", "21500001"]   # MANUAL만 있는 과목은 없음
    a = plan["courses"][0]
    assert (a["category"], a["category_orig"]) == ("전공필수", "전필-AI소프트웨어")
    assert a["expected_enrollment"] == 60
    rows = {r["section_id"]: r for r in plan["sections"]}
    assert (rows["2150000002"]["section_no"], rows["2150000002"]["orig_section_no"]) == (1, "02")
    assert (rows["2150000005"]["section_no"], rows["2150000005"]["orig_section_no"]) == (2, "05")


def test_merge_wishes_same_professor():
    plan = sd.build_plan(*fake())
    r = next(x for x in plan["responses"] if x["course_id"] == 1)
    assert r["n_sections"] == 2 and r["differ"] and r["mixed_shape"]
    assert r["block"] == ["금-09:00", "월-09:00"]                    # 불가는 합집합
    assert r["prefer"] == ["수-09:00", "화-10:30"]                  # 희망은 합집합 − 불가 (토요일 칸은 버림)
    assert r["lab"] == 1 and r["single_day"] == "PREFER"            # 연강·주 2회가 섞이면 PREFER
    assert r["note"] == "좌석 여유가 있으면 좋겠습니다."
    assert len(plan["responses"]) == 2                              # (과목, 교수)마다 하나


def test_db_and_map_round_trip(tmp_path):
    plan = sd.build_plan(*fake())
    con = sqlite3.connect(":memory:")
    term, rnd, room_ids = sd.create_db(con, plan, ROOMS)
    mp = sd.section_map(plan, ROOMS, ":memory:", term, rnd, room_ids)
    path = tmp_path / "section_map.json"
    path.write_text(json.dumps(mp, ensure_ascii=False), encoding="utf-8")
    back = json.loads(path.read_text(encoding="utf-8"))
    assert back["sections"]["2150000201"] == "MANUAL"
    pairs = sd.section_pairs(back)
    assert pairs == {(1, 1): "2150000002", (1, 2): "2150000005", (2, 1): "2150000101"}
    # DB의 분반·교수가 대응표와 같다
    got = {(c, s): n for c, s, n in con.execute(
        "SELECT cs.course_id, cs.section_no, u.name FROM course_section cs JOIN user u ON u.id = cs.professor_id")}
    assert got == {(1, 1): "교수01", (1, 2): "교수01", (2, 1): "교수02"}
    assert con.execute("SELECT category FROM course WHERE id=2").fetchone()[0] == "교양필수"
    assert con.execute("SELECT COUNT(*) FROM course_response").fetchone()[0] == 2
    # 분반 수 요청(SECTION_COUNT)이 교수의 분반 수와 같다
    assert con.execute("""SELECT i.value_int FROM request_item i JOIN course_response r ON r.id = i.response_id
                          WHERE r.course_id=1 AND i.type='SECTION_COUNT'""").fetchone()[0] == 2
    assert back["rooms"]["정보과학관 21303"]["estimated"] is True
    assert sd.real_name_hits(con) == []


# ---------- 솔버와 함께 (재성 요청: 같은 교수 01·02, 응답 1번 → 서로 다른 시간) ----------

def test_same_professor_sections_get_different_times():
    pytest.importorskip("ortools")
    from backend.app.solver.adapter import load_haeyoon
    _, solver = load_haeyoon()
    # 같은 교수가 분반 01·02, 희망은 둘 다 월·수 09:00 한 칸뿐 (응답은 하나로 합쳐짐). 강의실은 넉넉하다
    cells = {"월-09:00": "PREFER", "수-09:00": "PREFER"}
    sections = [sec("2150000001", "2150000001"), sec("2150000002", "2150000002")]
    wishes = [wish("2150000001", cells=cells), wish("2150000002", cells=cells)]
    tt = {"assignments": [twice("2150000001"), twice("2150000002", room="문화관 03407")]}
    plan = sd.build_plan(sections, wishes, tt)
    con = sqlite3.connect(":memory:")
    term, rnd, _ = sd.create_db(con, plan, ROOMS)
    assert con.execute("SELECT COUNT(*) FROM course_response").fetchone()[0] == 1
    r = solver.solve(con, term, rnd, time_limit=10)
    assert r["unplaced"] == []
    slots = {}
    for s, slot in con.execute("SELECT section_no, slot_id FROM assignment WHERE timetable_id=?", (r["timetable_id"],)):
        slots.setdefault(s, set()).add(slot)
    assert set(slots) == {1, 2} and not (slots[1] & slots[2])        # 같은 칸에 두 분반을 놓지 않는다
    assert con.execute("SELECT COUNT(*) FROM v_professor_conflict WHERE timetable_id=?",
                       (r["timetable_id"],)).fetchone()[0] == 0


# ---------- 실제(가명) 데이터 ----------

DATA = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")


@pytest.mark.skipif(not (DATA / "sections.json").exists(), reason=f"{DATA} 에 데이터가 없음")
def test_real_data_seed(tmp_path):
    out = sd.seed(DATA, tmp_path / "t.db", tmp_path / "section_map.json")
    mp = json.loads((tmp_path / "section_map.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in json.loads((DATA / "sections.json").read_text(encoding="utf-8"))}
    assert set(mp["sections"]) == ids                                  # 모든 분반이 대응표에 있다
    n = dict(out["counts"])
    manual = sum(1 for v in mp["sections"].values() if v == "MANUAL")
    assert n["분반"] + manual == len(ids) and n["MANUAL (DB에 안 넣음)"] == manual
    assert len(sd.section_pairs(mp)) == n["분반"]
    assert out["real_names"] == []
    # 과목마다 분반 번호가 1..n으로 빈칸 없이
    by_course = {}
    for v in mp["sections"].values():
        if v != "MANUAL":
            by_course.setdefault(v["course_id"], []).append(v["section_no"])
    assert all(sorted(v) == list(range(1, len(v) + 1)) for v in by_course.values())
