"""문하윤 솔버 어댑터 검사. solver/tests/test_data.py처럼 메모리 DB를 직접 채워 쓴다 (실제 데이터 필요 없음).
솔버 풀이 시간 한도는 몇 초로 짧게 둔다."""

import functools
import importlib
from pathlib import Path

import pytest

pytest.importorskip("ortools")

REPO_ROOT = Path(__file__).resolve().parents[2]

from backend.app import engine  # noqa: E402
from backend.app.contracts import STARTS, Alternative, Conditions  # noqa: E402
from backend.app.solver import adapter as ad  # noqa: E402

hdb, sc = ad.load_haeyoon()
import seed_time_slot as sd  # noqa: E402  (db/seed_time_slot.py, load_haeyoon이 경로를 잡음)

SECTIONS = {(1, 1): "S1-01", (2, 1): "S2-01", (2, 2): "S2-02", (3, 1): "S3-01", (4, 1): "S4-01"}
DAYN = "월화수목금"


def build_db():
    c = hdb.connect(":memory:")
    c.executescript((REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    sd.seed(c)
    ins = c.execute
    ins("INSERT INTO department(id, name, college) VALUES (1, 'AI소프트웨어학부', 'AI대학')")
    ins("INSERT INTO term(id, year, semester, grid_id) VALUES (1, 2027, '1', 1)")
    ins("INSERT INTO round(id, term_id, round_no, deadline_at, status) VALUES (1, 1, 1, '2027-01-10', 'CLOSED')")
    for i in range(1, 5):
        ins("INSERT INTO user(id, role, name, department_id, password_hash) VALUES (?, 'PROF', ?, 1, 'x')",
            (i, f"교수{i:02d}"))
    ins("INSERT INTO building(id, name) VALUES (1, '정보과학관'), (2, '문화관')")
    for rid, b, no, cap, lab in [(1, 1, "21303", 60, 0), (2, 1, "21304", 60, 0), (3, 1, "21501", 40, 1),
                                 (4, 2, "03407", 60, 0)]:
        ins("INSERT INTO room(id, building_id, room_no, capacity, is_lab) VALUES (?,?,?,?,?)", (rid, b, no, cap, lab))
    # (id, 이름, 교수, 학년, 인원, 주당 횟수, 1회 칸 수)
    for cid, name, prof, yr, enr, n, k in [(1, "자료구조", 1, "2", 40, 2, 1), (2, "알고리즘", 2, "3", 70, 2, 1),
                                          (3, "운영체제", 4, "3", 40, 2, 1), (4, "AI보안", 1, "4", 35, 1, 2)]:
        ins("""INSERT INTO course(id, term_id, department_id, name, professor_id, category, target_year,
               expected_enrollment, session_count, slots_per_session) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, 1, 1, name, prof, "전공선택", yr, enr, n, k))
    ins("INSERT INTO course_section(course_id, section_no, professor_id) VALUES (2, 1, 2), (2, 2, 3)")
    slot = {(d, s): i for i, d, s in c.execute("SELECT id, day, start_time FROM time_slot")}
    # (응답 id, 과목, 교수, 실습실, 주 1회 연강, 불가 칸, 희망 칸)
    for rid, cid, prof, lab, single, block, prefer in [
        (1, 1, 1, 0, "NONE", [("월", "09:00"), ("수", "09:00")], [("화", "13:30"), ("목", "13:30")]),
        (2, 2, 2, 0, "NONE", [], [("월", "10:30"), ("수", "10:30")]),
        (3, 2, 3, 1, "NONE", [("금", "09:00")], []),
        (4, 4, 1, 0, "MUST", [], [("수", "13:30"), ("수", "15:00")]),
    ]:
        ins("""INSERT INTO course_response(id, round_id, course_id, professor_id, lab_requirement, single_day_pref)
               VALUES (?,?,?,?,?,?)""", (rid, 1, cid, prof, lab, single))
        for x in block:
            ins("INSERT INTO response_slot VALUES (?,?, 'BLOCK')", (rid, slot[x]))
        for x in prefer:
            ins("INSERT INTO response_slot VALUES (?,?, 'PREFER')", (rid, slot[x]))
    c.commit()
    return c


@pytest.fixture()
def adapter():
    con = build_db()
    a = ad.SolverAdapter(con, term_id=1, round_id=1, sections=SECTIONS, draft_time_limit=5, alt_time_limit=3)
    yield a
    con.close()


def _end(start: str, k: int) -> str:
    h, m = map(int, start.split(":"))
    e = h * 60 + m + 75 * k + 15 * (k - 1)
    return f"{e // 60:02d}:{e % 60:02d}"


def test_draft_to_blocks_matches_db(adapter):
    tt, delayed = adapter.make_draft()
    assert adapter.timetable_id is not None and delayed == []
    by_id = {a.section_id: a for a in tt.assignments}
    assert set(by_id) == set(SECTIONS.values())
    # DB 뷰(v_schedule)에서 바로 읽은 값과 변환 결과가 같아야 한다
    rows = adapter.con.execute("""SELECT course_id, section_no, day, start_time, end_time, building, room_no
                                  FROM v_schedule WHERE timetable_id=?""", (adapter.timetable_id,)).fetchall()
    want = {}
    for cid, sec, day, st, en, b, no in rows:
        want.setdefault(SECTIONS[(cid, sec)], set()).add((day, st, en, f"{b} {no}"))
    for sid, a in by_id.items():
        # 수업(회차)마다 시각과 강의실이 DB와 같다. 대표 강의실 = 첫 수업의 강의실
        assert {(b.day, b.start, _end(b.start, b.slots), b.room) for b in a.blocks} == want[sid], sid
        assert all(b.start in STARTS for b in a.blocks)
        assert a.room == a.blocks[0].room and a.reason is None
    # 모양: 주 2회 = 1칸×2, 주 1회 연강(MUST) = 2칸×1, 실습실이 필요한 분반은 실습실
    assert sorted(b.slots for b in by_id["S1-01"].blocks) == [1, 1]
    assert [b.slots for b in by_id["S4-01"].blocks] == [2]
    assert by_id["S2-02"].room == "정보과학관 21501"
    # 불가 칸에는 놓지 않는다
    assert not any((b.day, b.start) in {("월", "09:00"), ("수", "09:00")} for b in by_id["S1-01"].blocks)


def test_rooms_differ_per_meeting_go_to_block_room(adapter):
    """솔버가 한 분반의 두 회차를 다른 강의실에 놓은 경우 (예: 화 문화관 03407, 목 정보과학관 21304)."""
    from backend.app.solver.adapter import assignments_from_db
    sl, rm = adapter.slots, adapter.rooms
    tue, thu = sl.id_of[("화", "13:30")], sl.id_of[("목", "13:30")]
    start = {(1, 1, 1): (thu, rm.id_of["정보과학관 21304"]), (1, 1, 0): (tue, rm.id_of["문화관 03407"])}
    ks = {(1, 1, 0): 1, (1, 1, 1): 1}
    a = assignments_from_db(start, ks, sl, rm, adapter.sections)["S1-01"]
    assert [(b.day, b.start, b.room) for b in a.blocks] == [("화", "13:30", "문화관 03407"),
                                                            ("목", "13:30", "정보과학관 21304")]
    assert a.room == "문화관 03407" and a.reason is None


def test_unplaced_becomes_coord(adapter, monkeypatch):
    real = adapter.sc.solve

    @functools.wraps(real)
    def solve_with_left(*a, **k):
        r = real(*a, **k)
        return dict(r, unplaced=[(3, 1, 1)])         # 운영체제 01을 못 놓은 것으로 본다

    monkeypatch.setattr(adapter.sc, "solve", solve_with_left)
    tt, delayed = adapter.make_draft()
    a = next(x for x in tt.assignments if x.section_id == "S3-01")
    assert delayed == ["S3-01"] and a.status == "COORD" and a.blocks == [] and a.reason


def test_alternatives_to_abc(adapter):
    adapter.make_draft()
    for sid, k in (("S1-01", 1), ("S4-01", 2)):
        alts = adapter.make_alternatives(sid)
        assert 1 <= len(alts) <= 3 and all(isinstance(x, Alternative) for x in alts)
        assert [x.key for x in alts] == list("ABC")[:len(alts)]
        rooms = set(adapter.rooms.name_of.values())
        for alt in alts:
            assert len(alt.meetings) == (2 if k == 1 else 1)
            for m in alt.meetings:
                assert 0 <= m.day <= 4 and m.start in STARTS and m.end == _end(m.start, k) and m.room in rooms
        assert adapter.last_options[sid]                      # save_proposal에 쓸 원본이 남아 있다
    pid = adapter.save_proposal("S4-01", reason="테스트")
    n = adapter.con.execute("SELECT COUNT(*) FROM proposal_option WHERE proposal_id=?", (pid,)).fetchone()[0]
    assert n == len(adapter.last_options["S4-01"])


def test_day_slots_condition_reaches_solver(adapter, monkeypatch):
    adapter.make_draft()
    seen = {}
    real = adapter.sc.make_alternatives

    @functools.wraps(real)
    def spy(*a, **k):
        seen["condition"] = k.get("condition")
        return real(*a, **k)

    monkeypatch.setattr(adapter.sc, "make_alternatives", spy)
    cond = Conditions.model_validate({"day_slots": {"1": ["09:00", "10:30"], "3": []}})
    alts = adapter.make_alternatives("S1-01", cond)
    assert seen["condition"] == {"day_slots": {"1": ["09:00", "10:30"], "3": []}, "end_before": []}
    assert alts, "조건을 만족하는 대안이 있어야 한다"
    for alt in alts:
        for m in alt.meetings:
            assert m.day in (1, 3), alt                         # 화·목 안에서만
            if m.day == 1:
                assert m.start in ("09:00", "10:30"), alt       # 화요일은 오전만
    # 옛 모양(days·slots)으로 줘도 day_slots로 바뀌어 간다
    adapter.make_alternatives("S1-01", Conditions.model_validate({"days": [1, 3], "slots": ["09:00", "10:30"]}))
    assert seen["condition"]["day_slots"] == {"1": ["09:00", "10:30"], "3": ["09:00", "10:30"]}
    # 조건이 비면 넘기지 않는다
    adapter.make_alternatives("S1-01", Conditions())
    assert seen["condition"] is None


def test_reassign_uses_alternative(adapter):
    tt, _ = adapter.make_draft()
    before = [b.model_dump() for b in next(x for x in tt.assignments if x.section_id == "S4-01").blocks]
    alt = adapter.make_alternatives("S4-01")[0]
    new = adapter.reassign(tt, "S4-01", alt)
    a = next(x for x in new.assignments if x.section_id == "S4-01")
    m = alt.meetings[0]
    assert [(b.day, b.start, b.slots) for b in a.blocks] == [(DAYN[m.day], m.start, 2)] and a.room == m.room
    after_orig = [b.model_dump() for b in next(x for x in tt.assignments if x.section_id == "S4-01").blocks]
    assert after_orig == before                                   # 원본 시간표는 그대로 (DB에도 안 씀)


def test_call_passes_only_known_kwargs():
    def old(con, term_id, round_id, time_limit=30):
        return dict(time_limit=time_limit)

    def new(con, term_id, round_id, time_limit=30, wish_round_id=None):
        return dict(time_limit=time_limit, wish_round_id=wish_round_id)

    assert ad._call(old, 1, 2, 3, time_limit=5, wish_round_id=9) == {"time_limit": 5}
    assert ad._call(new, 1, 2, 3, time_limit=5, wish_round_id=9) == {"time_limit": 5, "wish_round_id": 9}


def test_unknown_section_is_clear_error(adapter):
    adapter.make_draft()
    with pytest.raises(KeyError, match="DB에 대응하는 분반이 없음"):
        adapter.make_alternatives("없는분반")


# ---------- engine: SSUROOM_ENGINE=solver일 때만 어댑터를 쓴다 ----------

@pytest.fixture()
def reload_engine(monkeypatch):
    yield monkeypatch
    monkeypatch.delenv("SSUROOM_ENGINE", raising=False)
    importlib.reload(engine)
    ad.configure(None)


def test_engine_uses_stub_by_default(reload_engine):
    reload_engine.delenv("SSUROOM_ENGINE", raising=False)
    importlib.reload(engine)
    assert all(engine.sources()[n] == "stub" for n in engine.ASSIGN_NAMES)


def test_engine_uses_adapter_when_asked(reload_engine, adapter):
    reload_engine.setenv("SSUROOM_ENGINE", "solver")
    importlib.reload(engine)
    src = engine.sources()
    mod = "real (backend.app.solver.adapter)"
    assert (src["make_draft"], src["make_alternatives"], src["reassign"]) == (mod, mod, mod)
    assert src["check_rules"] == "stub" and src["what_if"] == "stub"      # 솔버에 없는 함수는 가짜
    assert engine.load_warnings() == []
    reload_engine.setenv("SSUROOM_DB", str(Path(__file__).parent / "없는파일.db"))   # 시드가 없을 때
    with pytest.raises(RuntimeError, match="configure"):
        engine.make_draft([], [], [])
    ad.configure(adapter)
    tt, delayed = engine.make_draft([], [], [])
    assert {a.section_id for a in tt.assignments} == set(SECTIONS.values())


def test_options_that_only_swap_sessions_are_one(adapter):
    """솔버가 회차 번호만 바꾼 안(1회차 월·2회차 수 ↔ 1회차 수·2회차 월)을 따로 내면 하나로 본다."""
    sl, rm = adapter.slots, adapter.rooms
    mon, wed, tue = sl.id_of[("월", "12:00")], sl.id_of[("수", "10:30")], sl.id_of[("화", "12:00")]
    r = rm.id_of["정보과학관 21303"]
    ks = {(1, 1): 1, (1, 2): 1}
    a = {"placements": {(1, 1): (wed, r), (1, 2): (mon, r)}, "ks": ks}
    b = {"placements": {(1, 1): (mon, r), (1, 2): (wed, r)}, "ks": ks}
    c = {"placements": {(1, 1): (tue, r), (1, 2): (wed, r)}, "ks": ks}
    assert ad.unique_options([a, b, c], 1, sl, rm) == [a, c]
