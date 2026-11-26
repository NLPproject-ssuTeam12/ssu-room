"""SSU:room 솔버 코어 (CP-SAT).

DB(schema.sql)에서 입력을 읽어 초안 시간표를 만들고 같은 DB에 저장한다.

모델
  결정변수 x[세션, 시작칸, 강의실묶음] = 1  → 이 수업 회차가 그 칸에서 시작해 그 묶음의 강의실 하나를 쓴다
  세션 = (과목, 분반번호, 회차번호). 분반은 오프라인 회의에서 정해져 조교가 course_section 에 한 행씩 넣는다
    (번호·담당 교수·수강 인원). 솔버는 분반 수를 바꾸지 않는다. 번호는 1부터 빈틈없이. 행이 없는 과목은
    course.professor_id 가 맡는 1분반 하나로 본다.
  분반마다 담당 교수가 다를 수 있다. 교수 겹침·응답(불가 시간·실습실·연강)은 분반의 교수 기준.
  희망 입력은 분반마다(course_response.section_no, 11/25): 칠한 칸·실습실·주 1회 연강. 그 분반 담당 교수의 응답만 읽는다.
  수강 인원(course_section.enrollment)이 강의실 정원보다 많으면 그 강의실은 후보에서 뺀다(하드). 인원이 비어 있으면 검사하지 않는다.
  희망 건물: 교수당 하나(professor_building_pref). 그 밖의 건물에 배정하면 벌점.
  강의실묶음 = 건물·정원·실습실 여부·전용 학과가 모두 같은 강의실들. 묶음 안의 방은 서로 구별할 필요가
              없으므로 변수를 줄이고(대칭 제거), 풀이 뒤에 실제 호실을 따로 배정한다.
  못 놓은 세션은 unplaced 변수로 큰 벌점을 주고 남긴다 → "못 맞춘 과목" 목록이 됨(2차 조율의 입력)

  용어 두 가지 (섞어 쓰지 말 것)
    주 1회 연강 = 한 분반이 하루에 2칸을 이어서 수업 (course_response.single_day_pref)
        MUST   하루에 연속 2칸 한 번으로만 배정
        NONE   1칸씩 두 번(이틀)으로만 배정   ※ 주당 2칸짜리 수업에만 적용. '선호'(PREFER)는 11/24에 없앰
    분반 연강/교차 = 한 교수가 한 과목의 두 분반 이상을 맡을 때 가반 끝나자마자 나반 / 교차
        (pair_request: 과목 단위로 한 번, 모드 BACK_TO_BACK / CROSS와 붙일 분반을 교수가 적은 순서대로.
         솔버는 앞 두 분반만 붙인다. 셋째 분반부터는 unsupported 로 알리고 조교가 수동 배치·고정한다. 11/25)
  필수과목(같은 학과·같은 학년끼리만, 학년이 다르면 겹쳐도 됨. 11/24):
        교양필수 ↔ 전공필수는 겹치지 않는다(하드). 교양필수끼리는 겹쳐도 된다.
        서로 다른 전공필수 과목 A·B는 겹치지 않는다(하드). 다만 둘 다 분반이 둘 이상이면 일부 겹쳐도 된다:
            A의 분반마다 안 겹치는 B 분반이 하나 이상, B의 분반마다 안 겹치는 A 분반이 하나 이상 있어야 한다(모든 학생이 둘 다 들을 수 있게).
        같은 과목의 분반끼리는 겹쳐도 된다(교수가 같으면 교수 겹침 규칙이 막는다).
  채플: 학년별 채플 칸(chapel_slot)에는 그 학년 전공필수를 놓지 않는다(하드).
  시간: 19:30 교시는 큰 감점(late), 18:00 이후 시작하는 연속 2칸 이상 수업은 놓지 않는다(하드).
  동선(11/25): 같은 학과·같은 학년의 전공 과목(이수구분이 '전공'으로 시작) 둘이 같은 요일 바로 이어진 교시에
        같은 건물이면 좋은 배치(flow). 강의실은 달라도 된다. 학년이 다르면 같이 듣지 않으므로 세지 않는다.
        두 단계 풀이: 1단계에서 동선 없이 풀고, 2단계에서 1단계 점수(희망·건물·못 놓음 …)를 나빠지지 않게 묶은 채
        동선만 늘린다. 그래서 동선은 다른 점수가 모두 같을 때만 따진다(교수 희망이 항상 먼저).
  동점 처리(11/25): 같은 희망 칸을 두고 점수가 같으면 ① 가능한 시간(불가가 아닌 칸)이 적은 분반 ② 먼저 임용된 교수
        (user.hire_year, 비면 건너뜀) ③ 과목·분반 번호 순서로 그 칸을 준다. 모든 점수를 TIE_SCALE 배 하고
        이 순위를 그보다 작은 보너스로 더해, 점수가 같을 때만 순서를 정한다(같은 입력이면 같은 결과).
  실습실: MUST(필요 → 실습실만 배정) / NONE(필요 없음 → 실습실 쓰면 약한 벌점). 희망 칸: PREFER(희망)/BLOCK(불가), 칠하지 않으면 상관없음

  고정: 이전 시간표에서 고정(timetable_section.locked=1)된 분반은 모든 풀이(부분 재풀이·대안·전체 재풀이)에서 움직이지 않는다.
        조교가 교수와 따로 정해 수동 배치한 분반이 규칙을 어겨도 풀이가 막히지 않도록, 고정된 수업끼리의 위반은 그대로 두고
        나머지 수업만 피하게 한다.

공개 함수
  solve(...)          전체 풀이 또는 일부 과목·분반만 다시 풀기(free_courses)
  alternatives(...)   못 놓은 과목(분반)의 대안 N개. 조율 쪽 조건(days/window/end_before 또는 slot_ids)을 받는다
  coord_targets(...)  조율 대상 분반: 못 놓음(UNPLACED) / 희망에서 어긋남(MISMATCH) / 일부 어긋남(PARTIAL)
  open_coord_proposals(...) 조율 대상마다 대안을 만들어 안건으로 저장 (OPEN 자동 보냄 / HOLD 조교 선택 / NO_OPTION 대안 없음)
  fill_options(...)   다음 차수 안건(db.open_next_proposal)에 대안을 채움. 없으면 NO_OPTION
  pick_best(...)      교수가 고른 대안(여러 개 가능)과 기타 조건으로 만든 안 중 점수가 가장 좋은 안
  check_timetable(...) 시간표의 하드 규칙 위반 목록 (조교 수동 배치 경고용)
  save_proposal(...)  대안을 proposal 테이블에 저장 / add_option(...) 안건에 대안 하나 더
  apply_option(...)   조교 [확인]·[수정]·도우미 [적용]한 안을 새 시간표 버전(TA_EDIT)으로 저장, 새 위반이 생기면 거부
  finalize(...)       시간표를 FINAL로 확정 (다음 해의 건물·강의실 기본값이 됨)
"""
import json
from collections import defaultdict

from ortools.sat.python import cp_model

MAJOR_REQUIRED = "전공필수"   # 채플 칸을 피할 과목 구분 (course.category)
GENERAL_REQUIRED = "교양필수"  # 같은 학년 전공필수와 겹치면 안 되는 과목 구분
LATE_START = "19:30"          # 이 시각에 시작하는 칸은 큰 감점
LONG_LAST_START = "16:30"     # 연속 2칸 이상 수업은 이 시각까지만 시작 (18:00 시작 연강 금지)
GROUP_ROOMS = True   # False면 강의실마다 따로 변수를 만든다(비교 실험용)
MAJOR_PREFIX = "전공"         # 동선 보너스를 줄 이수구분 (전공필수·전공선택·전공기초 …)
FLOW_TIME_LIMIT = 20          # 2단계(동선) 기본 제한 시간(초). 실제 82분반: 20초면 동선 103, 60초면 107
TIE_SCALE = 100000            # 점수 단위. 동점 순위 보너스(희망 칸마다 경쟁 분반 수 이하)를 이 단위보다 작게 둔다
DAYS = ["월", "화", "수", "목", "금", "토", "일"]   # 조율 쪽 days 번호: 0=월 … 4=금

DEFAULT_WEIGHTS = {
    "unplaced": 100000,   # 못 놓음
    "prefer": 10,         # 교수가 희망한 칸 (보너스)
    "building_other": 50, # 교수가 고른 희망 건물이 아닌 건물이면 큰 벌점 (11/24: 하드는 아님. 유지 30 + 희망 칸 2칸 20 과 같은 크기)
    "lab_waste": 5,       # 실습실이 필요 없다고 답한 수업(NONE)이 실습실 사용
    "keep": 30,           # 이전 배정을 그대로 두면 보너스 (최소 변경)
    "late": 60,           # 19:30 교시를 쓰면 큰 감점 (11/21·11/24: 다른 방법이 없을 때만)
    "history_room": 8,    # 회신 안 한 교수: 전년에 같은 과목을 한 강의실이면 보너스
    "flow": 4,            # 0이 아니면 2단계에서 동선(같은 학년 전공 연강 같은 건물)을 늘린다. 0이면 2단계를 하지 않음
}


# ---------------------------------------------------------------- 입력
def load_history(con, term_id):
    """전년도 같은 학기의 FINAL 시간표에서 교수별로 가장 많이 쓴 건물과 (교수, 과목명)별 강의실을 뽑는다.
    없으면 빈 값 → 아무 가정도 하지 않는다."""
    empty = ({}, {})
    row = con.execute("""SELECT tt.id FROM term t
                         JOIN term p ON p.year = t.year - 1 AND p.semester = t.semester
                         JOIN timetable tt ON tt.term_id = p.id AND tt.kind = 'FINAL'
                         WHERE t.id = ? ORDER BY tt.id DESC LIMIT 1""", (term_id,)).fetchone()
    if not row:
        return empty
    tt = row[0]
    hist_room = defaultdict(set)                 # (교수, 과목명) -> {강의실}
    bld_count = defaultdict(lambda: defaultdict(int))
    for prof, name, room, bld in con.execute(
            """SELECT DISTINCT COALESCE(cs.professor_id, c.professor_id), c.name, a.room_id, r.building_id
               FROM assignment a JOIN course c ON c.id = a.course_id
               LEFT JOIN course_section cs ON cs.course_id = a.course_id AND cs.section_no = a.section_no
               JOIN room r ON r.id = a.room_id WHERE a.timetable_id = ?""", (tt,)):
        hist_room[(prof, name)].add(room)
        bld_count[prof][bld] += 1
    hist_bld = {}
    for prof, cnt in bld_count.items():          # 가장 많이 쓴 건물 하나 (같으면 번호가 작은 건물)
        hist_bld[prof] = min(cnt, key=lambda b: (-cnt[b], b))
    return hist_bld, dict(hist_room)


def _has_column(con, table, column):
    return any(row[1] == column for row in con.execute(f"PRAGMA table_info({table})"))


def load_input(con, term_id, round_id):
    """-> by_day, courses, secs, rooms, pref, slot_info
    secs[(과목, 분반)] = 그 분반의 담당 교수, 수강 인원과 그 교수의 응답(불가·희망 칸, 실습실, 연강)
    pref[교수] = 희망 건물 id (하나)"""
    q = con.execute
    slots = q("""SELECT ts.id, ts.day, ts.period_no, ts.start_time, ts.end_time FROM time_slot ts
                 JOIN term t ON t.grid_id = ts.grid_id WHERE t.id=?
                 ORDER BY ts.day, ts.period_no""", (term_id,)).fetchall()
    by_day = defaultdict(list)                 # day -> [(period_no, slot_id)]
    slot_info = {}                             # slot_id -> (day, period, start, end)
    for sid, day, p, st, en in slots:
        by_day[day].append((p, sid))
        slot_info[sid] = (day, p, st, en)
    courses = {}
    for (cid, name, prof, dept, cat, yr, sc, sps) in q(
            """SELECT id, name, professor_id, department_id, category, target_year,
                      session_count, slots_per_session
               FROM course WHERE term_id=?""", (term_id,)):
        courses[cid] = dict(id=cid, name=name, prof=prof, dept=dept, cat=cat, year=yr,
                            sessions=sc, k=sps, sections=1)
    resp = {}                                   # (과목, 분반, 교수) -> 그 분반 응답 (11/25: 분반마다)
    for rid, cid, sec, prof, lab, single_day in q(
            """SELECT id, course_id, section_no, professor_id, lab_requirement, single_day_pref
               FROM course_response WHERE round_id=?""", (round_id,)):
        if cid not in courses:
            continue
        r = dict(lab=lab, single_day=single_day, block=set(), prefer=set(), id=rid)
        for sid, kind in q("SELECT slot_id, kind FROM response_slot WHERE response_id=?", (rid,)):
            r[{"BLOCK": "block", "PREFER": "prefer"}[kind]].add(sid)
        resp[(cid, sec, prof)] = r
    pair_req = defaultdict(list)                # 과목 -> [(교수, 모드, [교수가 적은 순서의 분반])]
    for pid, cid, prof, mode in q("SELECT id, course_id, professor_id, mode FROM pair_request WHERE round_id=?", (round_id,)):
        if cid in courses:
            order = [r[0] for r in q("SELECT section_no FROM pair_request_section WHERE request_id=? ORDER BY seq", (pid,))]
            pair_req[cid].append((prof, mode, order))
    # 분반: 조교가 course_section 에 넣은 행 그대로 (오프라인 회의에서 정한 분반 수·담당 교수·수강 인원).
    #   행이 없는 과목은 course.professor_id 가 맡는 1분반 하나 (인원 미정). 번호는 1부터 빈틈없어야 한다.
    given = defaultdict(dict)                    # 과목 -> {분반: (교수, 인원)}
    for cid, sec, prof, enr in q("SELECT course_id, section_no, professor_id, enrollment FROM course_section"):
        if cid in courses:
            given[cid][sec] = (prof, enr)
    for c in courses.values():
        rows = given.get(c["id"]) or {1: (c["prof"], None)}
        if sorted(rows) != list(range(1, len(rows) + 1)):
            raise ValueError(f"과목 {c['id']}({c['name']})의 분반 번호는 1부터 빈틈없어야 합니다: {sorted(rows)}")
        c["sections"] = len(rows)
        c["section_prof"] = {sec: p for sec, (p, _) in rows.items()}
        c["section_enroll"] = {sec: e for sec, (_, e) in rows.items()}
    # 분반 연강·교차 (pair_request): 교수가 적은 순서에서 그 교수가 맡은 분반만. 적은 분반이 없으면 맡은 분반 번호 순서.
    #   솔버는 앞 두 분반(가반·나반)만 붙인다.
    for c in courses.values():
        c["pairs"] = []                          # [([분반 번호들, 교수가 적은 순서], 모드)]
        for prof, mode, order in pair_req.get(c["id"], []):
            if order:
                mine = [sec for sec in order if c["section_prof"].get(sec) == prof]
            else:
                mine = sorted(sec for sec, p in c["section_prof"].items() if p == prof)
            c["pairs"].append((mine, mode))
    # migration 011 전 DB(user.hire_year 없음)는 그 사람의 연차기준을 무시한다(동점 처리가 다음 순서로 넘어감)
    hire = ({u: y for u, y in q("SELECT id, hire_year FROM user WHERE hire_year IS NOT NULL")}
            if _has_column(con, "user", "hire_year") else {})      # 교수 -> 임용 연도
    secs = {}
    for c in courses.values():
        for sec in range(1, c["sections"] + 1):
            prof = c["section_prof"][sec]
            r = resp.get((c["id"], sec, prof))
            secs[(c["id"], sec)] = dict(
                prof=prof, responded=r is not None, enroll=c["section_enroll"][sec],
                paired=any(sec in mine[:2] for mine, _ in c["pairs"] if len(mine) >= 2),
                lab=r["lab"] if r else None, single_day=r["single_day"] if r else None,
                block=r["block"] if r else set(), prefer=r["prefer"] if r else set(),
                hire_year=hire.get(prof),
                )
    rooms = {rid: dict(id=rid, bld=b, cap=cap, lab=lab or 0, dept=rd)
             for rid, b, cap, lab, rd in q(
                 "SELECT id, building_id, capacity, is_lab, reserved_department_id FROM room")}
    pref = {p: b for p, b in q("SELECT professor_id, building_id FROM professor_building_pref")}   # 교수 -> 희망 건물
    chapel = defaultdict(set)                    # 학년 -> 채플 칸
    for yr, sid in q("SELECT target_year, slot_id FROM chapel_slot WHERE term_id=?", (term_id,)):
        chapel[str(yr)].add(sid)
    for c in courses.values():
        c["chapel"] = chapel.get(str(c["year"]), set()) if c["cat"] == MAJOR_REQUIRED and c["year"] else set()
    return by_day, courses, secs, rooms, pref, slot_info


def _tie_ranks(secs, slot_info):
    """동점 순위 (11/25). 희망 칸마다 그 칸을 희망한 분반들을 줄 세워, 앞 순서일수록 큰 보너스(경쟁 분반 수 - 순위).
    순서: ① 가능한 칸(불가가 아닌 칸)이 적은 분반 ② 먼저 임용된 교수(hire_year 작은 쪽, 없으면 뒤) ③ 과목·분반 번호.
    -> {(과목, 분반, 칸): 보너스}. 보너스 합은 TIE_SCALE 보다 훨씬 작아 원래 점수가 같을 때만 순서를 정한다."""
    total = len(slot_info)
    by_cell = defaultdict(list)
    for (cid, sec), sd in secs.items():
        for sid in sd["prefer"]:
            by_cell[sid].append((total - len(sd["block"]),
                                 sd.get("hire_year") if sd.get("hire_year") is not None else 9999, cid, sec))
    out = {}
    for sid, rows in by_cell.items():
        rows.sort()
        n = len(rows)
        for r, (_, _, cid, sec) in enumerate(rows):
            out[(cid, sec, sid)] = n - r
    return out


def _any_pos(m, vs, name):
    """vs 중 하나라도 1일 때만 1이 될 수 있는 변수 (보너스용: 위로만 막는다)"""
    b = m.NewBoolVar(name)
    m.Add(b <= sum(vs))
    return b


def make_classes(rooms):
    """건물·정원·실습실·전용학과가 같은 강의실을 한 묶음으로. -> (묶음들, 방->묶음 번호)"""
    classes, room2class, index = [], {}, {}
    for r in sorted(rooms.values(), key=lambda r: r["id"]):
        key = (r["bld"], r["cap"], r["lab"], r["dept"]) if GROUP_ROOMS else (r["id"],)
        if key not in index:
            index[key] = len(classes)
            classes.append(dict(id=index[key], bld=r["bld"], cap=r["cap"], lab=r["lab"], dept=r["dept"], rooms=[]))
        classes[index[key]]["rooms"].append(r["id"])
        room2class[r["id"]] = index[key]
    return classes, room2class


def load_assignment(con, timetable_id):
    """시간표 -> ({(과목, 분반, 회차): (시작칸, 강의실)}, {(과목, 분반, 회차): 차지한 칸 수})"""
    start, kk = {}, defaultdict(int)
    for c, s, ss, slot, room in con.execute(
            """SELECT a.course_id, a.section_no, a.session_no, a.slot_id, a.room_id
               FROM assignment a JOIN time_slot ts ON ts.id = a.slot_id
               WHERE a.timetable_id=? ORDER BY a.course_id, a.section_no, a.session_no, ts.day, ts.period_no""",
            (timetable_id,)):
        start.setdefault((c, s, ss), (slot, room))      # 첫 칸이 시작칸
        kk[(c, s, ss)] += 1
    return start, dict(kk)


def _minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _norm_time(t):
    """'9:00' 같은 표기도 '09:00'로 맞춘다."""
    h, m = str(t).split(":")
    return f"{int(h):02d}:{int(m):02d}"


def _apply_day_slots(cond, slot_info):
    """조율 쪽의 day_slots를 솔버가 아는 조건(days, slot_ids)으로 바꾼다.
      day_slots = {요일(0~4): [그 요일에 되는 교시의 시작 시각, ...]}   빈 목록 = 그 요일 아무 교시나
        요일 둘 이상 -> slot_ids = 그 요일들의 해당 교시 칸 (수업은 그 요일들 안에서만)
        요일 하나    -> days=[그 요일] + slot_ids = 그 요일의 해당 교시 칸 + 나머지 요일 전체 칸
                        (그 요일이 들어가야 하고, 주 2회의 다른 하루는 자유)
        비어 있음    -> 요일·교시 조건 없음
      연강(2칸 이어진 수업)은 두 교시가 모두 slot_ids 안에 있어야 놓인다.
    다른 키(days, window, by_day, end_before, slot_ids)는 그대로 두고 함께 적용한다(모두 AND).
    시작 시각이 격자의 어느 교시 시작과도 맞지 않으면 그 교시는 없는 것으로 본다."""
    ds = cond.get("day_slots")
    if not ds:
        return {k: v for k, v in cond.items() if k != "day_slots"}
    want = {int(k): [_norm_time(t) for t in (v or [])] for k, v in ds.items()}
    by_idx = defaultdict(list)                          # 요일 번호 -> [(slot_id, 시작시각)]
    for sid, (day, _p, st, _en) in slot_info.items():
        by_idx[DAYS.index(day)].append((sid, _norm_time(st)))

    def pick(d):                                         # 그 요일에서 되는 칸
        return {sid for sid, st in by_idx[d] if not want[d] or st in want[d]}

    out = {k: v for k, v in cond.items() if k != "day_slots"}
    slots = set()
    if len(want) >= 2:
        for d in want:
            slots |= pick(d)
    else:
        (d0,) = want
        slots = pick(d0)
        for d, lst in by_idx.items():
            if d != d0:
                slots |= {sid for sid, _ in lst}
        if not out.get("days"):
            out["days"] = [d0]
    if out.get("slot_ids"):
        slots &= set(out["slot_ids"])                    # slot_ids도 함께 주면 둘 다 만족
    out["slot_ids"] = sorted(slots) or [-1]              # 빈 집합이면 아무 데도 못 놓는다(-1은 없는 칸)
    return out


def _structures(c, sd):
    """한 분반이 가질 수 있는 수업 구성들. 각 구성 = [(회차번호, 한 회 칸 수), ...]
    주당 2칸짜리 수업이고 교수가 답했을 때만 MUST='연속 2칸 한 번', NONE='1칸 두 번'. 그 밖에는 입력 구성 그대로."""
    fixed = [(ss, c["k"]) for ss in range(1, c["sessions"] + 1)]
    if c["sessions"] * c["k"] == 2 and sd["single_day"] and not sd["paired"]:
        long_, split = [(1, 2)], [(1, 1), (2, 1)]
        return {"MUST": [long_], "NONE": [split]}[sd["single_day"]]
    return [fixed]


# ---------------------------------------------------------------- 모델
def _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk, free,
                 seed, forbid=None, must_sections=None, cond=None, cond_sections=None, locked=None, flow_time_limit=None, skip=None):
    """모델을 만들어 풀고 결과를 메모리로 돌려준다(DB에는 쓰지 않음).
    prev/prevk: 이전 시간표 {(과목,분반,회차): (시작칸, 강의실)} / {(과목,분반,회차): 칸 수}
    free: None이면 전부 새로 풀고, 집합(과목 id 또는 (과목,분반))이면 그 분반만 풀고 나머지는 prev 그대로 고정
    forbid: [(dict(세션키 -> 시작칸), 허용되는 같은 칸 수)]  대안끼리 달라지게 하는 금지 조건
    must_sections: 모든 회차를 반드시 놓아야 하는 (과목, 분반) 집합
    cond/cond_sections: 조율 쪽 조건(요일·시간대)과 그것이 적용될 (과목, 분반) 집합
    locked: 고정된 (과목, 분반) 집합. free 에 들어 있어도 prev 그대로 둔다
    두 단계로 푼다(11/25): 1단계 원래 점수 + 동점 순위, 2단계 원래 점수를 1단계보다 나빠지지 않게 묶고 동선을 늘린 뒤 동점 순위.
    skip: 이번 풀이에서 아예 빼는 (과목, 분반) 집합 (변수를 만들지 않음, 그리디 기준선용).
    flow_time_limit: 2단계 제한 시간(초). 없으면 min(time_limit, FLOW_TIME_LIMIT=20). 2단계가 끝나지 않아도 찾은 해를 쓴다(원래 점수는 그대로)."""
    by_day, courses, secs, rooms, pref, slot_info = load_input(con, term_id, round_id)
    hist_bld, hist_room = load_history(con, term_id)
    classes, room2class = make_classes(rooms)

    def is_free(cid, sec):
        return free is None or cid in free or (cid, sec) in free

    prev_by_sec = defaultdict(dict)
    for (c, s, ss), v in prev.items():
        prev_by_sec[(c, s)][ss] = v

    tie = _tie_ranks(secs, slot_info)            # (과목, 분반, 칸) -> 동점 순위 보너스
    flow_end, flow_start = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    # 동선: (학과, 학년, 요일, 교시, 건물) -> 과목 -> 그 교시에 끝나는(또는 시작하는) 회차 변수들

    m = cp_model.CpModel()
    x, cost = {}, {}
    fixed = set()                               # 고정된 수업의 변수 번호 (항상 1)
    occ_room, occ_prof = defaultdict(list), defaultdict(list)
    occ_req = defaultdict(lambda: defaultdict(list))   # (학과, 학년, 칸, 교필/전필) -> 변수들
    maj_sec = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # (학과, 학년) -> 전필 과목 -> (분반, 칸) -> 변수들
    day_use = defaultdict(list)
    unplaced = {}                               # (과목,분반,회차,칸수) -> 못 놓음 변수
    day_idx = {d: i for i, d in enumerate(by_day)}
    day_terms, per_terms = defaultdict(list), defaultdict(list)
    sorted_days = {d: sorted(p) for d, p in by_day.items()}
    unsupported, frozen_secs = [], set()
    cond_day_vars = []                          # 조건이 요일 하나일 때: 그 요일에 놓인 변수들
    cond_single_day = None
    allowed_days = window = None
    by_day_win = {}                             # 요일 -> [(시작분, 끝분), ...]  그 요일에는 이 시간대 안에서만
    end_before = {}
    cond_slots = None
    if cond:
        ds = cond.get("days") or []
        if len(ds) == 1:
            cond_single_day = DAYS[ds[0]]
        elif len(ds) >= 2:
            allowed_days = {DAYS[i] for i in ds}
        if cond.get("window"):
            window = (_minutes(cond["window"][0]), _minutes(cond["window"][1]))
        for k_, v_ in (cond.get("by_day") or {}).items():       # 요일별 시간대: {"1": ["09:00","10:15"], "3": [["13:30","14:45"], ...]}
            rs = [v_] if v_ and isinstance(v_[0], str) else v_    # 시간대 하나면 [시작,끝], 여러 개면 [[시작,끝], ...]
            by_day_win[DAYS[int(k_)]] = [(_minutes(a), _minutes(b)) for a, b in rs]
        for e in cond.get("end_before") or []:
            end_before[DAYS[e["day"]]] = _minutes(e["time"])
        if cond.get("slot_ids"):
            cond_slots = set(cond["slot_ids"])

    for c in courses.values():
        n = c["sections"]
        for sec in range(1, n + 1):
            if skip and (c["id"], sec) in skip:
                continue                                 # 아직 놓지 않을 분반 (그리디 기준선)
            sd = secs[(c["id"], sec)]
            cid = c["id"]
            if sd["paired"] and sd["single_day"] == "MUST":
                unsupported.append((cid, "주 1회 연강 응답과 분반 연강·교차 요청을 함께 받으면 분반 요청을 우선하고 주 1회 연강 응답은 무시"))
            structs = _structures(c, sd)
            ps = sorted((ss, prevk[(cid, sec, ss)]) for ss in prev_by_sec.get((cid, sec), {}))
            matched = next((st for st in structs if sorted(st) == ps), None) if ps else None
            if locked and (cid, sec) in locked and ps:   # 고정: 구성이 응답과 달라도(수동 배치) 그대로
                matched, structs = ps, [ps]
            frozen = ((not is_free(cid, sec)) or bool(locked and (cid, sec) in locked)) and matched is not None
            if frozen:
                structs = [matched]
                frozen_secs.add((cid, sec))
            bp = pref.get(sd["prof"]) or (hist_bld.get(sd["prof"]) if not sd["responded"] else None)   # 희망 건물 하나
            hroom = hist_room.get((sd["prof"], c["name"]), set()) if not sd["responded"] else set()
            use_cond = bool(cond) and (cid, sec) in (cond_sections or ()) and not frozen

            for struct in structs:                      # 구성은 하나 (MUST·NONE·입력 그대로)
                act = 1
                for (ss, k) in struct:
                    key = (cid, sec, ss)
                    skey = (cid, sec, ss, k)
                    if frozen:
                        fslot, froom = prev_by_sec[(cid, sec)][ss][:2]
                        fclass = room2class[froom]
                    feasible = []
                    for day, plist in sorted_days.items():
                        for i in range(len(plist) - k + 1):
                            chunk = plist[i:i + k]
                            if any(chunk[j + 1][0] != chunk[j][0] + 1 for j in range(len(chunk) - 1)):
                                continue                    # 연속한 칸이어야 함
                            covered = [sid for _, sid in chunk]
                            if not frozen and sd["block"] & set(covered):
                                continue                    # 절대 불가 칸
                            if not frozen and c["chapel"] & set(covered):
                                continue                    # 그 학년 채플 칸에는 전공필수를 놓지 않음
                            if not frozen and k >= 2 and slot_info[covered[0]][2] > LONG_LAST_START:
                                continue                    # 18:00 이후 시작 연강 금지
                            if use_cond:                    # 조율 쪽이 넘긴 조건
                                if allowed_days is not None and day not in allowed_days:
                                    continue
                                cs_, ce_ = _minutes(slot_info[covered[0]][2]), _minutes(slot_info[covered[-1]][3])
                                if window and not (window[0] <= cs_ and ce_ <= window[1]):
                                    continue
                                if by_day_win and (day not in by_day_win or not any(a <= cs_ and ce_ <= b for a, b in by_day_win[day])):
                                    continue                # 요일별 시간대: 적힌 요일만, 그 요일의 시간대 안에서만
                                if day in end_before and ce_ > end_before[day]:
                                    continue
                                if cond_slots is not None and not set(covered) <= cond_slots:
                                    continue
                            for cl in classes:
                                if frozen:
                                    if not (covered[0] == fslot and cl["id"] == fclass):
                                        continue
                                else:
                                    if cl["cap"] is not None and sd["enroll"] and cl["cap"] < sd["enroll"]:
                                        continue            # 분반 수강 인원 > 강의실 정원: 후보에서 뺌 (하드)
                                    if sd["lab"] == "MUST" and not cl["lab"]:
                                        continue
                                    if cl["dept"] is not None and cl["dept"] != c["dept"]:
                                        continue
                                var = m.NewBoolVar(f"x{skey}{covered[0]}_{cl['id']}")
                                x[(skey, covered[0], cl["id"])] = var
                                if frozen:
                                    fixed.add(var.Index())
                                day_terms[skey].append(day_idx[day] * var)     # 이 회차의 요일 번호
                                per_terms[skey].append(chunk[0][0] * var)      # 이 회차의 교시 번호
                                feasible.append(var)
                                if use_cond and cond_single_day == day:
                                    cond_day_vars.append(var)
                                w = 0                       # 고정된 세션은 상수라 0
                                if not frozen:
                                    w -= W["prefer"] * len(sd["prefer"] & set(covered))
                                    if bp is not None and cl["bld"] != bp:
                                        w += W["building_other"]     # 희망 건물이 아니면 벌점
                                    if cl["lab"] and sd["lab"] == "NONE":
                                        w += W["lab_waste"]          # 미회신(None)에는 가정하지 않음
                                    if hroom and hroom & set(cl["rooms"]):
                                        w -= W["history_room"]
                                    if any(slot_info[sid][2] == LATE_START for sid in covered):
                                        w += W["late"]               # 19:30 교시는 다른 방법이 없을 때만
                                same = (key in prev and prevk.get(key) == k and prev[key][0] == covered[0]
                                        and room2class[prev[key][1]] == cl["id"])
                                if same and not frozen:
                                    w -= W["keep"]
                                if prev:
                                    m.AddHint(var, 1 if same else 0)     # 이전 해를 출발점으로 알려 줌
                                tb = 0 if frozen else sum(tie.get((cid, sec, sid), 0) for sid in sd["prefer"] & set(covered))
                                cost[var.Index()] = (var, w, tb)
                                if c["cat"] and str(c["cat"]).startswith(MAJOR_PREFIX) and c["year"]:
                                    ck = (c["dept"], str(c["year"]), day)
                                    flow_end[ck + (chunk[-1][0], cl["bld"])][cid].append(var)
                                    flow_start[ck + (chunk[0][0], cl["bld"])][cid].append(var)
                                for sid in covered:
                                    occ_room[(cl["id"], sid)].append(var)
                                    occ_prof[(sd["prof"], sid)].append(var)
                                    if c["cat"] in (MAJOR_REQUIRED, GENERAL_REQUIRED) and c["year"]:
                                        occ_req[(c["dept"], str(c["year"]), sid)][c["cat"]].append(var)
                                        if c["cat"] == MAJOR_REQUIRED:
                                            maj_sec[(c["dept"], str(c["year"]))][cid][(sec, sid)].append(var)
                                day_use[(cid, sec, day)].append(var)
                    un = m.NewBoolVar(f"un{skey}")
                    unplaced[skey] = un
                    m.Add(sum(feasible) + un == act)
                    if frozen or (must_sections and (cid, sec) in must_sections):
                        m.Add(un == 0)                       # 고정된 수업·반드시 놓을 수업은 빠질 수 없다

    nfix = lambda vs: sum(1 for v in vs if v.Index() in fixed)
    cap_of = {cl["id"]: len(cl["rooms"]) for cl in classes}
    for (clid, sid), vs in occ_room.items():
        if len(vs) > cap_of[clid]:
            m.Add(sum(vs) <= max(cap_of[clid], nfix(vs)))   # 같은 칸에 그 묶음의 방 수보다 많이 못 씀 (고정끼리 넘친 것은 그대로)
    for vs in occ_prof.values():
        if len(vs) > 1: m.Add(sum(vs) <= max(1, nfix(vs)))  # 같은 교수 동시 수업 불가 (고정끼리 겹친 것은 그대로)
    for vs in day_use.values():
        if len(vs) > 1: m.Add(sum(vs) <= 1)              # 같은 분반은 하루 한 번
    def _any(vs, name):                          # vs 중 하나라도 1이면 1 (겹침 금지 제약에만 쓰므로 한 방향이면 충분)
        b = m.NewBoolVar(name)
        for v in vs:
            m.AddImplication(v, b)
        return b
    for (dept, yr, sid), by_cat in occ_req.items():   # 같은 학과·학년 교양필수 ↔ 전공필수 불가
        maj, gen = by_cat.get(MAJOR_REQUIRED), by_cat.get(GENERAL_REQUIRED)
        if maj and gen:
            if nfix(gen) and nfix(maj):                  # 고정끼리 이미 겹침 → 그 칸에는 다른 수업을 더 넣지 않음
                for v in gen + maj:
                    if v.Index() not in fixed:
                        m.Add(v == 0)
            else:
                m.Add(_any(gen, f"gen{dept}_{yr}_{sid}") + _any(maj, f"maj{dept}_{yr}_{sid}") <= 1)
    for (dept, yr), by_course in maj_sec.items():     # 같은 학과·학년의 서로 다른 전공필수 과목
        ids = sorted(by_course)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                na, nb = courses[a]["sections"], courses[b]["sections"]
                ov = {}                                  # (A 분반, B 분반) -> 겹침(1이면 겹칠 수 있음)
                for sa in range(1, na + 1):
                    for sb in range(1, nb + 1):
                        ov[(sa, sb)] = o = m.NewBoolVar(f"ov{a}_{sa}_{b}_{sb}")
                        for (s1, sid), va in by_course[a].items():
                            vb = by_course[b].get((sb, sid)) if s1 == sa else None
                            if vb:                       # 한 분반은 한 칸에 많아야 한 번 → 합이 0/1
                                m.Add(sum(va) + sum(vb) - 1 <= o)
                fa = {sa: (a, sa) in frozen_secs for sa in range(1, na + 1)}   # 고정끼리의 위반은 그대로 둔다
                fb = {sb: (b, sb) in frozen_secs for sb in range(1, nb + 1)}
                if na == 1 or nb == 1:                   # 한쪽이라도 분반 하나 → 전혀 겹치지 않음
                    for (sa, sb), o in ov.items():
                        if not (fa[sa] and fb[sb]):
                            m.Add(o == 0)
                else:                                    # 분반마다 안 겹치는 상대 분반이 하나 이상
                    for sa in range(1, na + 1):
                        if not (fa[sa] and all(fb.values())):
                            m.Add(sum(ov[(sa, sb)] for sb in range(1, nb + 1)) <= nb - 1)
                    for sb in range(1, nb + 1):
                        if not (fb[sb] and all(fa.values())):
                            m.Add(sum(ov[(sa, sb)] for sa in range(1, na + 1)) <= na - 1)
    if cond_single_day is not None:
        if cond_day_vars:
            m.Add(sum(cond_day_vars) >= 1)               # 요일이 하나면 그 요일이 들어간 안
        else:
            m.Add(0 >= 1)                                # 후보가 없음 → 불가능

    # 한 교수의 분반 연강/교차 (pair_request). 교수가 적은 순서의 앞 두 분반만 붙인다
    for c, (mine, mode) in [(c, pr) for c in courses.values() for pr in c["pairs"]]:
        if len(mine) < 2 or c["k"] != 1:
            unsupported.append((c["id"], "분반 연강·교차는 그 교수가 맡은 분반이 둘 이상이고 1회 수업이 한 칸일 때만 지원"))
            continue
        if len(mine) > 2:
            unsupported.append((c["id"], f"분반 연강·교차는 교수가 적은 순서의 앞 두 분반({mine[0]}·{mine[1]})만 붙입니다. "
                                         f"나머지 분반({', '.join(map(str, mine[2:]))})은 조교가 수동 배치·고정하세요"))
        sa, sb = mine[:2]
        S = c["sessions"]
        K = lambda sec, ss: (c["id"], sec, ss, 1)
        if any(K(sa, ss) not in unplaced or K(sb, ss) not in unplaced for ss in range(1, S + 1)):
            continue
        for ss in range(1, S + 1):
            A, B = K(sa, ss), K(sb, ss)
            lits = [unplaced[A].Not(), unplaced[B].Not()]
            dA, dB = sum(day_terms[A]), sum(day_terms[B])
            pA, pB = sum(per_terms[A]), sum(per_terms[B])
            m.Add(dA == dB).OnlyEnforceIf(lits)                    # 같은 요일
            up = m.NewBoolVar(f"adj{c['id']}_{ss}")                # 가반이 먼저(1) 또는 나반이 먼저
            m.Add(pB - pA == 1).OnlyEnforceIf(lits + [up])         # 바로 붙은 교시
            m.Add(pA - pB == 1).OnlyEnforceIf(lits + [up.Not()])
        if mode == "CROSS" and S == 2:
            A1, A2, B1, B2 = K(sa, 1), K(sa, 2), K(sb, 1), K(sb, 2)
            lits = [unplaced[k].Not() for k in (A1, A2, B1, B2)]
            m.Add(sum(per_terms[A1]) == sum(per_terms[B2])).OnlyEnforceIf(lits)   # 가1 = 나2 교시
            m.Add(sum(per_terms[A2]) == sum(per_terms[B1])).OnlyEnforceIf(lits)   # 가2 = 나1 교시
        elif mode == "CROSS":
            unsupported.append((c["id"], "교차 배정은 주 2회 수업일 때만 지원"))

    # 대안끼리 달라지게: 이미 나온 대안과 같은 시작 칸을 쓰는 회차 수를 제한.
    # 회차 번호가 아니라 분반 단위 시작 칸 집합으로 본다 (회차 순서만 바꾼 같은 안이 다시 나오지 않게).
    for mapping, max_same in (forbid or []):
        starts = defaultdict(set)                        # (과목, 분반) -> 그 안의 시작 칸들
        for key, start in mapping.items():
            starts[key[:2]].add(start)
        same_terms = [v for (sk, st, cl), v in x.items() if st in starts.get(sk[:2], ())]
        if same_terms:
            m.Add(sum(same_terms) <= max_same)

    flow_vars = []
    if W.get("flow"):
        for (dept, yr, day, per, bld), ends in flow_end.items():
            starts = flow_start.get((dept, yr, day, per + 1, bld))
            if not starts or len(set(ends) | set(starts)) < 2:
                continue                                 # 서로 다른 두 과목이 있어야 함
            e = {cid: _any_pos(m, vs, f"fe{dept}_{yr}_{day}_{per}_{bld}_{cid}") for cid, vs in ends.items()}
            st = {cid: _any_pos(m, vs, f"fs{dept}_{yr}_{day}_{per}_{bld}_{cid}") for cid, vs in starts.items()}
            z = m.NewBoolVar(f"flow{dept}_{yr}_{day}_{per}_{bld}")
            ws = []
            for cid, ev in e.items():                    # 과목 cid 가 끝나고 다른 과목이 바로 이어서 시작
                others = [sv for c2, sv in st.items() if c2 != cid]
                if not others:
                    continue
                wv = m.NewBoolVar(f"fw{dept}_{yr}_{day}_{per}_{bld}_{cid}")
                m.Add(wv <= ev)
                m.Add(wv <= sum(others))
                ws.append(wv)
            if not ws:
                continue
            m.Add(z <= sum(ws))
            flow_vars.append(z)
    main_terms = [(v, w) for v, w, _ in cost.values() if w] + [(u, W["unplaced"]) for u in unplaced.values()]
    tie_terms = [(v, tb) for v, _, tb in cost.values() if tb]
    main_expr = sum(w * v for v, w in main_terms)                # 원래 점수 (희망·건물·유지·못 놓음 …)
    tie_expr = sum(tb * v for v, tb in tie_terms)                # 동점 순위 보너스 (TIE_SCALE 미만)

    def run(limit):
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = limit
        sv.parameters.num_workers = workers
        sv.parameters.random_seed = seed
        return sv, sv.Solve(m)

    # 1단계: 동선 없이 원래 점수(+ 동점 순위)로 푼다
    m.Minimize(main_expr * TIE_SCALE - tie_expr)
    s, status = run(time_limit)
    status_name = s.StatusName(status)
    flow_status, seconds = None, s.WallTime()
    # 2단계: 1단계 원래 점수보다 나빠지지 않게 묶고, 동선(같은 학년 전공 연강 같은 건물)을 늘린다. 그다음 동점 순위
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and flow_vars and W.get("flow"):
        main1 = sum(w * s.Value(v) for v, w in main_terms)
        m.Add(main_expr <= main1)
        m.ClearHints()
        for v in list(x.values()) + list(unplaced.values()):
            m.AddHint(v, s.Value(v))                         # 1단계 해에서 출발
        m.Minimize(-TIE_SCALE * sum(flow_vars) - tie_expr)
        s2, st2 = run(flow_time_limit or min(time_limit, FLOW_TIME_LIMIT))
        flow_status = s2.StatusName(st2)
        seconds += s2.WallTime()
        if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            s = s2
    out = dict(status=status_name, unsupported=unsupported, courses=courses, secs=secs, rooms=rooms,
               classes=classes, room2class=room2class, by_day=by_day, hist_room=hist_room,
               locked={k for k in (locked or ()) if k in frozen_secs}, slot_info=slot_info)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out.update(placements=None, ks=None, unplaced=[], objective=None, objective_raw=None, tie_bonus=None,
                   flow_pairs=None, flow_status=None, seconds=seconds)
        return out

    # ----- 묶음 안에서 실제 호실 배정 -----
    chosen = defaultdict(list)                  # 묶음 -> [(세션키, 시작칸, 점유 칸들, 칸 수)]
    slot_idx = {sid: (d, i) for d, pl in sorted_days.items() for i, (_, sid) in enumerate(pl)}
    for (skey, start, clid), var in x.items():
        if s.Value(var):
            d, i = slot_idx[start]
            covered = [sid for _, sid in sorted_days[d][i:i + skey[3]]]
            chosen[clid].append((skey[:3], start, covered, skey[3]))
    placements, ks = {}, {}
    for clid, items in chosen.items():
        placements.update(_assign_rooms(items, classes[clid]["rooms"], prev, prevk, secs, courses,
                                        hist_room, frozen_secs))
        for key, _, _, k in items:
            ks[key] = k
    left = [sk[:3] for sk, v in unplaced.items() if s.Value(v)]
    main = sum(w * s.Value(v) for v, w in main_terms)    # 원래 점수 (동선·동점 순위 제외)
    tie_b = sum(tb * s.Value(v) for v, tb in tie_terms)
    flows = sum(s.Value(z) for z in flow_vars)
    out.update(placements=placements, ks=ks, unplaced=left, objective=main, objective_raw=main * TIE_SCALE - tie_b,
               tie_bonus=tie_b, flow_pairs=flows, flow_status=flow_status, seconds=seconds)
    return out


def _assign_rooms(items, room_ids, prev, prevk, secs, courses, hist_room, frozen_secs):
    """한 묶음 안에서 겹치지 않게 실제 호실을 정한다. 고정된 과목과 전년 강의실을 최대한 살린다."""
    if len(room_ids) == 1:
        return {key: (start, room_ids[0]) for key, start, _, _ in items}
    m = cp_model.CpModel()
    y = {}
    by_room_slot = defaultdict(list)
    obj = []
    for idx, (key, start, covered, k) in enumerate(items):
        sd = secs[(key[0], key[1])]
        c = courses[key[0]]
        frozen = (key[0], key[1]) in frozen_secs
        hr = hist_room.get((sd["prof"], c["name"]), set()) if not sd["responded"] else set()
        for r in room_ids:
            v = m.NewBoolVar(f"y{idx}_{r}")
            y[(idx, r)] = v
            for sid in covered:
                by_room_slot[(r, sid)].append(v)
            if frozen and prev[key][1] == r:
                obj.append(1000 * v)                       # 고정된 과목은 원래 방 그대로
            elif key in prev and prevk.get(key) == k and prev[key][0] == start and prev[key][1] == r:
                obj.append(10 * v)                         # 이전과 같은 칸이면 같은 방
            elif r in hr:
                obj.append(5 * v)                          # 전년에 쓴 방
        m.Add(sum(y[(idx, r)] for r in room_ids) == 1)
    for vs in by_room_slot.values():
        if len(vs) > 1: m.Add(sum(vs) <= 1)
    m.Maximize(sum(obj))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 10
    s.parameters.num_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("강의실 묶음 안에서 호실을 정하지 못했습니다(묶음 용량 제약과 모순)")
    res = {}
    for idx, (key, start, _, _) in enumerate(items):
        for r in room_ids:
            if s.Value(y[(idx, r)]):
                res[key] = (start, r)
    return res


# ---------------------------------------------------------------- 저장
def _persist(con, out, term_id, round_id, W, time_limit, previous_timetable_id, created_by):
    cur = con.execute("INSERT INTO solver_run(round_id, started_at, finished_at, status, objective_value, time_limit_sec, weights_json) "
                      "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?)",
                      (round_id, out["status"], out["objective"], time_limit, json.dumps(W)))
    run_id = cur.lastrowid
    if out["placements"] is None:
        con.commit()
        return run_id, None
    tt = con.execute("INSERT INTO timetable(term_id, round_id, kind, solver_run_id, parent_id, created_by) "
                     "VALUES (?,?, 'DRAFT', ?, ?, ?)", (term_id, round_id, run_id, previous_timetable_id, created_by)).lastrowid
    courses, by_day = out["courses"], out["by_day"]
    for c in courses.values():
        n = c["sections"]
        for sec in range(1, n + 1):
            lk = (c["id"], sec) in out.get("locked", ())          # 고정된 분반은 새 시간표에서도 고정(MANUAL)
            con.execute("INSERT INTO timetable_section(timetable_id, course_id, section_no, planned_enrollment, status, locked) "
                        "VALUES (?,?,?,?,?,?)",
                        (tt, c["id"], sec, out["secs"][(c["id"], sec)]["enroll"], "MANUAL" if lk else "DONE", int(lk)))
    sorted_days = {d: sorted(p) for d, p in by_day.items()}
    for key, (start, room_id) in out["placements"].items():
        for sid in _covered(start, out["ks"][key], sorted_days):
            con.execute("INSERT INTO assignment VALUES (?,?,?,?,?,?)", (tt, key[0], key[1], key[2], sid, room_id))
    con.commit()
    return run_id, tt


def load_locked(con, timetable_id):
    """그 시간표에서 고정된 (과목, 분반) 집합."""
    if not timetable_id:
        return set()
    return {(c, s) for c, s in con.execute(
        "SELECT course_id, section_no FROM timetable_section WHERE timetable_id=? AND locked=1", (timetable_id,))}


def _covered(start, k, sorted_days):
    for d, pl in sorted_days.items():
        ids = [sid for _, sid in pl]
        if start in ids:
            i = ids.index(start)
            return ids[i:i + k]
    return [start]


# ---------------------------------------------------------------- 공개 함수
def solve(con, term_id, round_id, weights=None, time_limit=30, workers=8,
          previous_timetable_id=None, free_courses=None, created_by=None, seed=0, flow_time_limit=None):
    """전체 풀이. previous_timetable_id를 주면 그 시간표를 출발점·유지 보너스로 쓴다.
    free_courses(과목 id 또는 (과목 id, 분반) 집합)까지 주면 그것만 다시 풀고 나머지는 이전 시간표 그대로 고정한다."""
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    prev, prevk = load_assignment(con, previous_timetable_id) if previous_timetable_id else ({}, {})
    if free_courses is not None and not prev:
        raise ValueError("free_courses는 previous_timetable_id와 함께 써야 합니다")
    out = _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk,
                       set(free_courses) if free_courses is not None else None, seed,
                       locked=load_locked(con, previous_timetable_id), flow_time_limit=flow_time_limit)
    run_id, tt = _persist(con, out, term_id, round_id, W, time_limit, previous_timetable_id, created_by)
    return dict(status=out["status"], run_id=run_id, timetable_id=tt, unplaced=out["unplaced"],
                objective=out["objective"], seconds=out["seconds"], unsupported=out["unsupported"],
                flow_pairs=out["flow_pairs"], flow_status=out["flow_status"])


def alternatives(con, term_id, round_id, timetable_id, course_id, section_no=None, condition=None,
                 n=3, time_limit=15, weights=None, workers=8, exclude_sent=True):
    """못 놓은(또는 바꿔야 할) 과목·분반의 대안 n개.
    section_no를 주면 그 분반만, 안 주면 과목의 모든 분반을 새로 놓는다.
    condition(조율 쪽에서 넘기는 모양, 모두 선택 사항):
      {"days": [0,2],                    되는 요일 (0=월…4=금). 하나면 그 요일이 들어간 안, 둘 이상이면 그 요일들 안에서만
       "window": ["13:30","17:45"],      되는 시간대 (시작, 끝). 모든 요일에 같은 범위
       "by_day": {"0": ["13:30","14:45"], "2": ["15:00","16:15"]},
                                         요일별 시간대. 적힌 요일에서만, 그 요일의 시간대 안에서만. 한 요일에 여러 개면 [[시작,끝],[시작,끝]]
       "end_before": [{"day":2,"time":"17:00"}],   요일별로 끝나야 하는 시각
       "slot_ids": [..],                 칸 번호 목록으로 줘도 됨
       "day_slots": {"0": ["13:30","15:00"], "2": []}
                                         요일(0~4) -> 그 요일에 되는 교시의 시작 시각. 빈 목록 = 그 요일 아무 교시나.
                                         요일이 둘 이상이면 그 요일들 안에서만, 하나면 그 요일이 들어가야 함(다른 날은 자유).
                                         연강(2칸)은 두 교시가 모두 들어 있어야 함. 비어 있으면({}) 요일·교시 조건 없음.
                                         안에서 days/slot_ids로 바뀐다. end_before는 그대로 쓴다.}
    1단계: 다른 수업은 그대로 두고 대상만 새로 놓는다.
    2단계(모자라면): 같은 교수의 다른 수업과, 대상과 겹칠 수 없는 같은 학년 필수과목(교필↔전필, 분반 하나인 전필↔전필)까지 움직일 수 있게 하고, 움직인 수업을 함께 알려 준다.
    같은 분반 칸 집합이 같은 안(회차 순서만 다른 안, 강의실만 다른 안)은 하나로 본다.
    exclude_sent: 그 분반에 이미 보낸 대안(이전 차수 포함, 답 기다림 이후 상태의 안건)과 같은 안은 다시 내지 않는다(11/25).
    반환: [dict(stage, placements{(분반,회차):(시작칸,강의실)}, ks{(분반,회차):칸 수}, moves[(키,이전,이후)], objective)]"""
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    prev, prevk = load_assignment(con, timetable_id)
    _, courses, secs, _, _, slot_info = load_input(con, term_id, round_id)
    if condition and condition.get("day_slots") is not None:
        condition = _apply_day_slots(condition, slot_info)
    t_secs, expanded = _targets(courses, secs, course_id, section_no)
    locked = load_locked(con, timetable_id)
    if t_secs & locked:
        raise ValueError(f"고정된 분반은 대안을 만들지 않습니다: {sorted(t_secs & locked)}. 고정을 먼저 푸세요(db.set_lock)")
    stages = [("다른 수업은 그대로", t_secs),
              ("같은 교수·같은 학년 필수과목 일부 이동", expanded)]
    results = []
    forbid = []
    cur = {k: v[0] for k, v in prev.items() if (k[0], k[1]) in t_secs}
    if cur:
        forbid.append((cur, 0))                              # 현재 배정과 같은 안은 대안이 아니다
    if exclude_sent:
        forbid += [(m, 0) for m in _sent_mappings(con, term_id, course_id, t_secs)]   # 이미 보낸 대안도 아니다
    for stage_name, free in stages:
        if len(results) >= n:
            break
        if stage_name != stages[0][0] and free == t_secs:
            continue
        must = {(k[0], k[1]) for k in prev if (k[0], k[1]) in free} | t_secs
        while len(results) < n:
            out = None
            for max_same in (0, None):                     # 먼저 전부 다른 칸, 안 되면 하나라도 다르게
                fb = [(f, 0 if max_same == 0 else max(len(f) - 1, 0)) for f, _ in forbid]
                out = _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk, free,
                                   seed=len(results), forbid=fb, must_sections=must,
                                   cond=condition, cond_sections=t_secs, locked=locked)
                if out["placements"] is not None or not forbid:
                    break
            if out is None or out["placements"] is None:
                break
            pl = out["placements"]
            mapping = {k: v[0] for k, v in pl.items() if (k[0], k[1]) in t_secs}
            if not mapping:
                break
            sig = _signature(mapping)
            if sig == _signature(cur) or any(_signature(f) == sig for f, _ in forbid):
                break                                        # 이미 나온 안(회차 순서만 다름)이면 더 찾지 않는다
            moves = [(k, prev[k], pl[k]) for k in pl
                     if k in prev and (k[0], k[1]) not in t_secs and pl[k] != prev[k]]
            results.append(dict(stage=stage_name,
                                placements={k[1:]: v for k, v in pl.items() if (k[0], k[1]) in t_secs},
                                ks={k[1:]: out["ks"][k] for k in pl if (k[0], k[1]) in t_secs},
                                moves=moves, objective=out["objective"]))
            forbid.append((mapping, 0))
    return results


def _sent_mappings(con, term_id, course_id, t_secs):
    """그 분반들에 이미 보낸 대안(같은 학기, 이전 차수 포함) → forbid 모양 [{(과목, 분반, 회차): 시작칸}].
    보내기 전(OPEN)·조교 선택 대기(HOLD)·대안 없음(NO_OPTION) 안건의 대안은 보내지 않았으므로 빼지 않는다.
    대상 분반을 모두 담은 대안만 비교한다."""
    out = []
    for (oid,) in con.execute("""SELECT o.id FROM proposal_option o JOIN proposal p ON p.id = o.proposal_id
                                 JOIN round r ON r.id = p.round_id
                                 WHERE r.term_id=? AND p.course_id=? AND p.status NOT IN ('OPEN','HOLD','NO_OPTION')""",
                              (term_id, course_id)).fetchall():
        o = load_option(con, oid)
        m = {(course_id, sec, ss): st for (sec, ss), (st, _) in o["placements"].items() if (course_id, sec) in t_secs}
        if m and {(c, s) for c, s, _ in m} == set(t_secs):
            out.append(m)
    return out


def _targets(courses, secs, course_id, section_no):
    """대상 분반 집합과, 2단계에서 함께 움직일 수 있는 분반 집합(같은 교수 + 대상과 겹칠 수 없는 같은 학년 필수과목)."""
    target = courses[course_id]
    t_secs = {(course_id, s) for s in (range(1, target["sections"] + 1) if section_no is None else [section_no])}
    t_profs = {secs[ts]["prof"] for ts in t_secs}
    expanded = set(t_secs)
    req = {MAJOR_REQUIRED: GENERAL_REQUIRED, GENERAL_REQUIRED: MAJOR_REQUIRED}
    for (cid, sec), sd in secs.items():
        c = courses[cid]
        same_cohort = c["dept"] == target["dept"] and c["year"] and str(c["year"]) == str(target["year"]) and cid != course_id
        blocks = (target["cat"] in req and c["cat"] == req[target["cat"]]) or (   # 겹칠 수 없는 같은 학년 교필↔전필
            target["cat"] == c["cat"] == MAJOR_REQUIRED)                          # 다른 전필 과목
        if sd["prof"] in t_profs or (same_cohort and blocks):
            expanded.add((cid, sec))
    return t_secs, expanded


def load_option(con, option_id):
    """저장된 대안(proposal_option) → dict(proposal_id, option_no, placements{(분반,회차):(시작칸,강의실)}, ks{(분반,회차):칸 수}, slots)"""
    row = con.execute("SELECT proposal_id, option_no FROM proposal_option WHERE id=?", (option_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 대안: {option_id}")
    cells = defaultdict(list)
    for sec, ss, sid, room, day, per in con.execute(
            """SELECT os.section_no, os.session_no, os.slot_id, os.room_id, ts.day, ts.period_no
               FROM proposal_option_slot os JOIN time_slot ts ON ts.id = os.slot_id WHERE os.option_id=?""", (option_id,)):
        cells[(sec, ss)].append((DAYS.index(day) if day in DAYS else 9, per, sid, room))
    placements, ks, slots = {}, {}, set()
    for key, cs in cells.items():
        cs.sort()
        placements[key] = (cs[0][2], cs[0][3])
        ks[key] = len(cs)
        slots |= {c[2] for c in cs}
    return dict(proposal_id=row[0], option_no=row[1], placements=placements, ks=ks, slots=slots)


def pick_best(con, term_id, round_id, timetable_id, course_id, section_no=None, option_ids=(), condition=None,
              time_limit=15, weights=None, workers=8, respect_order=False):
    """교수가 고른 대안(option_ids, 여러 개 가능)과 기타 조건(condition, 있으면 그 조건에 맞는 새 안 하나)을
    지금 시간표(timetable_id)에 넣었을 때의 점수로 비교한다. 점수는 엔진 목적함수(낮을수록 좋음), 다른 수업은 그대로.
    고른 안이 지금은 놓을 수 없으면(그사이 다른 수업이 그 칸을 씀) 같은 교수·같은 학년 필수과목을 조금 움직여 보고,
    그래도 안 되면 feasible=False.
    반환: 좋은 순서 [dict(source='A'|'B'|'C'|'ETC', option_id, feasible, objective, stage, placements, ks, moves)]
      source 'ETC' 는 기타 조건으로 만든 새 안(option_id=None, 쓰려면 add_option 으로 저장).
      feasible 인 안이 하나도 없으면 처리안은 '조교가 정함'([수정]·[현재대로 유지]·[따로 연락]).
    respect_order: 교수가 글로 선호 순서를 밝혔을 때(예: "A가 제일 좋고 안 되면 B") True. option_ids 를 그 순서대로 넘기면
      점수와 상관없이 놓을 수 있는 안 중 앞 순서를 먼저 둔다. 기타 조건으로 만든 새 안(ETC)은 밝힌 순서 뒤.
      False(버튼만 누른 경우)면 점수 순."""
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    prev, prevk = load_assignment(con, timetable_id)
    by_day, courses, secs, _, _, slot_info = load_input(con, term_id, round_id)
    sorted_days = {d: sorted(p_) for d, p_ in by_day.items()}
    t_secs, expanded = _targets(courses, secs, course_id, section_no)
    locked = load_locked(con, timetable_id)
    if t_secs & locked:
        raise ValueError(f"고정된 분반입니다: {sorted(t_secs & locked)}")
    cands = []
    for oid in option_ids:
        o = load_option(con, oid)
        cands.append(("ABC"[o["option_no"] - 1] if 1 <= o["option_no"] <= 3 else "ETC", oid, o["slots"]))
    if condition:
        new = alternatives(con, term_id, round_id, timetable_id, course_id, section_no, condition=condition,
                           n=1, time_limit=time_limit, weights=weights, workers=workers, exclude_sent=False)
        if new:
            slots = set()
            for (sec, ss), (start, _) in new[0]["placements"].items():
                slots |= set(_covered(start, new[0]["ks"][(sec, ss)], sorted_days))
            cands.append(("ETC", None, slots))
    out_list = []
    for source, oid, slots in cands:
        best = dict(source=source, option_id=oid, feasible=False, objective=None, stage=None,
                    placements=None, ks=None, moves=[])
        for stage_name, free in (("다른 수업은 그대로", t_secs), ("같은 교수·같은 학년 필수과목 일부 이동", expanded)):
            if stage_name != "다른 수업은 그대로" and free == t_secs:
                continue
            must = {(k[0], k[1]) for k in prev if (k[0], k[1]) in free} | t_secs
            out = _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk, free, seed=0,
                               must_sections=must, cond={"slot_ids": sorted(slots)}, cond_sections=t_secs, locked=locked)
            if out["placements"] is None:
                continue
            pl = out["placements"]
            got = set()
            for k in pl:
                if (k[0], k[1]) in t_secs:
                    got |= set(_covered(pl[k][0], out["ks"][k], sorted_days))
            if got != set(slots):                        # 고른 안의 칸을 모두 그대로 써야 그 안이다
                continue
            best.update(feasible=True, objective=out["objective"], objective_raw=out["objective_raw"], stage=stage_name,
                        placements={k[1:]: v for k, v in pl.items() if (k[0], k[1]) in t_secs},
                        ks={k[1:]: out["ks"][k] for k in pl if (k[0], k[1]) in t_secs},
                        moves=[(k, prev[k], pl[k]) for k in pl
                               if k in prev and (k[0], k[1]) not in t_secs and pl[k] != prev[k]])
            break
        out_list.append(best)
    rank = {oid: i for i, oid in enumerate(option_ids)}
    if respect_order:                                    # 교수가 밝힌 순서 → 놓을 수 있는 안 중 앞 순서, 새 안(ETC)은 맨 뒤
        out_list.sort(key=lambda d: (not d["feasible"], rank.get(d["option_id"], len(rank))))
    else:                                                # 버튼만 누른 경우 → 점수 순
        out_list.sort(key=lambda d: (not d["feasible"], d["stage"] != "다른 수업은 그대로",
                                     d["objective_raw"] if d.get("objective_raw") is not None else 0))
    return out_list


def check_timetable(con, timetable_id):
    """시간표의 하드 규칙 위반 목록 (조교 수동 배치 뒤 경고용). -> [dict(rule, course_id, section_no, detail)]
    교수 겹침, 불가 칸, 정원, 실습실, 채플, 교필↔전필, 전필↔전필(분반 기준), 18:00 이후 시작 연강."""
    q = lambda sql: con.execute(sql, (timetable_id,)).fetchall()
    prof_sql = "COALESCE((SELECT professor_id FROM course_section WHERE course_id=a.course_id AND section_no=a.section_no), c.professor_id)"
    resp_sql = f"""(SELECT id FROM course_response WHERE course_id=a.course_id AND section_no=a.section_no AND professor_id={prof_sql}
                     ORDER BY round_id DESC, id DESC LIMIT 1)"""
    out = []
    for prof, sid, n in q("SELECT professor_id, slot_id, n FROM v_professor_conflict WHERE timetable_id=?"):
        out.append(dict(rule="교수 겹침", course_id=None, section_no=None, detail=f"교수 {prof} 칸 {sid}에 수업 {n}개"))
    for cid, sec, sid in q(f"""SELECT a.course_id, a.section_no, a.slot_id FROM assignment a JOIN course c ON c.id=a.course_id
                               WHERE a.timetable_id=? AND a.slot_id IN (SELECT slot_id FROM response_slot
                                     WHERE response_id={resp_sql} AND kind='BLOCK')"""):
        out.append(dict(rule="불가 칸", course_id=cid, section_no=sec, detail=f"칸 {sid}"))
    for cid, sec, room, enr, cap in q("""SELECT DISTINCT a.course_id, a.section_no, r.id, s.enrollment, r.capacity FROM assignment a
                                         JOIN course_section s ON s.course_id=a.course_id AND s.section_no=a.section_no
                                         JOIN room r ON r.id=a.room_id WHERE a.timetable_id=? AND s.enrollment > r.capacity"""):
        out.append(dict(rule="정원", course_id=cid, section_no=sec, detail=f"인원 {enr} > 강의실 {room} 정원 {cap}"))
    for cid, sec, room in q(f"""SELECT DISTINCT a.course_id, a.section_no, r.id FROM assignment a JOIN course c ON c.id=a.course_id
                               JOIN room r ON r.id=a.room_id JOIN course_response cr ON cr.id={resp_sql}
                               WHERE a.timetable_id=? AND cr.lab_requirement='MUST' AND r.is_lab=0"""):
        out.append(dict(rule="실습실", course_id=cid, section_no=sec, detail=f"실습실이 아닌 강의실 {room}"))
    for cid, sec, sid in q("""SELECT a.course_id, a.section_no, a.slot_id FROM assignment a JOIN course c ON c.id=a.course_id
                              JOIN timetable t ON t.id=a.timetable_id
                              JOIN chapel_slot ch ON ch.term_id=t.term_id AND ch.target_year=c.target_year AND ch.slot_id=a.slot_id
                              WHERE a.timetable_id=? AND c.category='전공필수'"""):
        out.append(dict(rule="채플", course_id=cid, section_no=sec, detail=f"채플 칸 {sid}"))
    for g, j, sid in q("""SELECT DISTINCT a.course_id, b.course_id, a.slot_id FROM assignment a JOIN course g ON g.id=a.course_id AND g.category='교양필수'
                          JOIN assignment b ON b.timetable_id=a.timetable_id AND b.slot_id=a.slot_id
                          JOIN course j ON j.id=b.course_id AND j.category='전공필수'
                          WHERE a.timetable_id=? AND g.target_year=j.target_year AND g.department_id IS j.department_id"""):
        out.append(dict(rule="교필↔전필", course_id=j, section_no=None, detail=f"교필 과목 {g}와 칸 {sid}"))
    slots = defaultdict(set)
    for cid, sec, sid in q("SELECT course_id, section_no, slot_id FROM assignment WHERE timetable_id=?"):
        slots[(cid, sec)].add(sid)
    nsec = dict(con.execute("SELECT course_id, COUNT(*) FROM course_section GROUP BY course_id").fetchall())
    groups = defaultdict(list)
    for cid, dept, yr in con.execute("SELECT id, department_id, target_year FROM course WHERE category='전공필수' AND target_year IS NOT NULL"):
        groups[(dept, yr)].append(cid)
    for ids in groups.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                na, nb = max(nsec.get(a, 1), 1), max(nsec.get(b, 1), 1)
                A = {x: slots.get((a, x), set()) for x in range(1, na + 1)}
                B = {x: slots.get((b, x), set()) for x in range(1, nb + 1)}
                if na == 1 or nb == 1:
                    if any(u & v for u in A.values() for v in B.values()):
                        out.append(dict(rule="전필↔전필", course_id=a, section_no=None, detail=f"분반 하나인 과목과 과목 {b}가 겹침"))
                elif any(all(u & v for v in B.values()) for u in A.values()) or any(all(u & v for u in A.values()) for v in B.values()):
                    out.append(dict(rule="전필↔전필", course_id=a, section_no=None, detail=f"과목 {b}와 피할 분반이 없음"))
    for cid, sec, ss, st in q("""SELECT a.course_id, a.section_no, a.session_no, MIN(ts.start_time) FROM assignment a
                                 JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=?
                                 GROUP BY 1,2,3 HAVING COUNT(*) >= 2 AND MIN(ts.start_time) > '16:30'"""):
        out.append(dict(rule="18:00 이후 연강", course_id=cid, section_no=sec, detail=f"{ss}회차 {st} 시작"))
    return out


def option_rows(con, option_id=None, option=None, timetable_id=None):
    """대안 → db.apply_option 의 rows [(분반, 회차, 칸, 강의실), ...].
    option_id(저장된 대안) 또는 option(alternatives·pick_best 결과 하나, 이때 timetable_id 로 학기의 칸 순서를 찾음)."""
    if option_id is not None:
        return [tuple(r) for r in con.execute("""SELECT section_no, session_no, slot_id, room_id FROM proposal_option_slot
                                                 WHERE option_id=? ORDER BY 1,2,3""", (option_id,))]
    by_day = defaultdict(list)
    for sid, day, per in con.execute("""SELECT ts.id, ts.day, ts.period_no FROM time_slot ts
             JOIN term t ON t.grid_id=ts.grid_id JOIN timetable tt ON tt.term_id=t.id
             WHERE tt.id=? ORDER BY ts.day, ts.period_no""", (timetable_id,)):
        by_day[day].append((per, sid))
    sorted_days = {d: sorted(p_) for d, p_ in by_day.items()}
    return sorted((sec, ss, sid, room) for (sec, ss), (start, room) in option["placements"].items()
                  for sid in _covered(start, option["ks"][(sec, ss)], sorted_days))


def apply_option(con, proposal_id, user_id, rows, reason=None, *, course_id=None, base_timetable_id=None):
    """db.apply_option 에 규칙 검사(check_timetable)를 붙여 부른다: 고른 안을 새 시간표 버전(TA_EDIT)으로 저장하고,
    기준 버전에 없던 하드 규칙 위반이 새로 생기면 저장하지 않고 ValueError. -> 새 시간표 id
    서버(어댑터)는 이 함수를 부른 뒤 새 id 를 '현재 시간표'로 써야 다음 차수 alternatives·solve 가 이 버전을 기준으로 한다."""
    import db as _db                                     # db/db.py (db 와 solver 가 둘 다 sys.path 에 있어야 한다)
    return _db.apply_option(con, proposal_id, user_id, rows, reason, course_id=course_id,
                            base_timetable_id=base_timetable_id, check=check_timetable)


def _signature(mapping):
    """대안 비교용: 분반별 시작 칸 집합 (회차 번호는 보지 않는다)."""
    out = defaultdict(set)
    for key, start in mapping.items():
        out[key[:2]].add(start)
    return {k: frozenset(v) for k, v in out.items()}


make_alternatives = alternatives          # 조율 쪽 이름


def _day_ids(con, timetable_id):
    """그 시간표 학기의 요일 -> [칸 id, 교시 순]"""
    by_day = defaultdict(list)
    for sid, day in con.execute("""SELECT ts.id, ts.day FROM time_slot ts
             JOIN term t ON t.grid_id=ts.grid_id JOIN timetable tt ON tt.term_id=t.id
             WHERE tt.id=? ORDER BY ts.day, ts.period_no""", (timetable_id,)):
        by_day[day].append(sid)
    return by_day


def save_proposal(con, round_id, timetable_id, course_id, options, reason="", section_no=None,
                  target_kind=None, status=None):
    """alternatives() 결과를 proposal 테이블에 저장한다. 조교가 교수에게 보낼 메시지의 근거가 된다.
    target_kind: 조율 대상 종류 UNPLACED / MISMATCH / PARTIAL (coord_targets).
    status: 없으면 OPEN. HOLD(조교 선택 대기)처럼 직접 줄 수 있다.
            대안이 하나도 없으면 무엇을 주든 NO_OPTION (메시지를 보내지 않고 조교가 확인)."""
    if not options:
        status = "NO_OPTION"
    pid = con.execute("INSERT INTO proposal(round_id, timetable_id, course_id, section_no, reason, status, target_kind) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (round_id, timetable_id, course_id, section_no, reason, status or "OPEN", target_kind)).lastrowid
    by_day = _day_ids(con, timetable_id)
    for no, opt in enumerate(options, 1):
        _write_option(con, pid, no, opt, by_day)
    con.commit()
    return pid


def _write_option(con, pid, no, opt, by_day, source="SOLVER"):
    oid = con.execute("INSERT INTO proposal_option(proposal_id, option_no, source) VALUES (?,?,?)",
                      (pid, no, source)).lastrowid
    for (sec, ss), (start, room) in opt["placements"].items():
        for d, ids in by_day.items():
            if start in ids:
                i = ids.index(start)
                for sid in ids[i:i + opt["ks"][(sec, ss)]]:
                    con.execute("INSERT INTO proposal_option_slot VALUES (?,?,?,?,?)", (oid, sec, ss, sid, room))
    return oid


def add_option(con, proposal_id, option, source="SOLVER"):
    """안건에 대안 하나를 더 저장한다 (예: pick_best 가 기타 조건으로 만든 안). 번호는 기존 대안 다음(4, 5, …). -> 새 대안 id"""
    row = con.execute("SELECT timetable_id FROM proposal WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 조율 안건: {proposal_id}")
    by_day = _day_ids(con, row[0])
    no = con.execute("SELECT COALESCE(MAX(option_no), 0) + 1 FROM proposal_option WHERE proposal_id=?", (proposal_id,)).fetchone()[0]
    oid = _write_option(con, proposal_id, no, option, by_day, source)
    con.commit()
    return oid


TARGET_KINDS = {"UNPLACED": "못 놓음", "MISMATCH": "희망에서 어긋남", "PARTIAL": "일부 어긋남"}


def coord_targets(con, term_id, round_id, timetable_id):
    """조율 메시지를 보낼 대상 분반 (11/25).
      UNPLACED 못 놓음         회차가 하나라도 시간표에 없음                          → 대안과 함께 자동으로 보냄
      MISMATCH 희망에서 어긋남  모든 회차가 희망 칸 밖, 또는 모든 회차가 희망 건물 밖  → 대안과 함께 자동으로 보냄
      PARTIAL  일부 어긋남      일부 회차만 희망 칸 밖 또는 희망 건물 밖                → 보내지 않고 조교 화면에 (조교가 골라 보냄)
    - 한 회차가 희망 칸에 맞다 = 그 회차가 차지한 칸이 모두 그 분반 응답의 희망(PREFER) 칸.
      희망 칸을 칠하지 않은 분반(미회신 포함)은 시간으로는 대상이 아니다.
    - 한 회차가 희망 건물에 맞다 = 그 회차 강의실이 담당 교수의 희망 건물(professor_building_pref).
      희망 건물이 없는 교수는 건물로는 대상이 아니다. (미회신 교수의 전년도 건물은 희망이 아니므로 보지 않는다)
    - 고정된 분반(locked)·조교가 정한 분반(MANUAL)은 뺀다.
    -> [dict(course_id, section_no, kind, reason, time_off=[회차], building_off=[회차])], 못 놓음·어긋남·일부 순"""
    _, courses, secs, rooms, pref, slot_info = load_input(con, term_id, round_id)
    skip = {(c, s) for c, s in con.execute(
        "SELECT course_id, section_no FROM timetable_section WHERE timetable_id=? AND (locked=1 OR status='MANUAL')",
        (timetable_id,))}
    cells = defaultdict(lambda: defaultdict(list))       # (과목, 분반) -> 회차 -> [(칸, 강의실)]
    for cid, sec, ss, sid, room in con.execute(
            "SELECT course_id, section_no, session_no, slot_id, room_id FROM assignment WHERE timetable_id=?", (timetable_id,)):
        cells[(cid, sec)][ss].append((sid, room))
    bname = dict(con.execute("SELECT id, name FROM building").fetchall())

    def when(cs):
        d, _, st, _ = slot_info[min(cs, key=lambda x: slot_info[x[0]][1])[0]]
        return f"{d} {st}"
    out = []
    for (cid, sec), sd in sorted(secs.items()):
        if (cid, sec) in skip:
            continue
        c = courses[cid]
        sess = cells.get((cid, sec), {})
        if sum(len(v) for v in sess.values()) < c["sessions"] * c["k"]:
            out.append(dict(course_id=cid, section_no=sec, kind="UNPLACED", reason="시간표에 놓지 못함",
                            time_off=[], building_off=[]))
            continue
        time_off = [ss for ss, cs in sorted(sess.items())
                    if sd["prefer"] and not all(sid in sd["prefer"] for sid, _ in cs)]
        bp = pref.get(sd["prof"])
        bld_off = [ss for ss, cs in sorted(sess.items())
                   if bp is not None and any(rooms[r]["bld"] != bp for _, r in cs)]
        if not time_off and not bld_off:
            continue
        n = len(sess)
        kind = "MISMATCH" if len(time_off) == n or len(bld_off) == n else "PARTIAL"
        why = []
        if time_off:
            why.append("희망 시간 밖: " + ", ".join(when(sess[ss]) for ss in time_off))
        if bld_off:
            why.append(f"희망 건물({bname.get(bp, bp)}) 밖: " + ", ".join(when(sess[ss]) for ss in bld_off))
        out.append(dict(course_id=cid, section_no=sec, kind=kind, reason=" / ".join(why),
                        time_off=time_off, building_off=bld_off))
    order = {"UNPLACED": 0, "MISMATCH": 1, "PARTIAL": 2}
    out.sort(key=lambda t: (order[t["kind"]], t["course_id"], t["section_no"]))
    return out


def open_coord_proposals(con, term_id, round_id, timetable_id, n=3, time_limit=15, weights=None, workers=8,
                         targets=None):
    """조율 대상(coord_targets, 또는 targets 로 준 목록)마다 대안 n개를 만들어 안건으로 저장한다 (11/25).
      UNPLACED·MISMATCH → OPEN       서버가 대안 A·B·C와 함께 자동으로 보낸다
      PARTIAL           → HOLD       보내지 않고 조교 화면에. 조교가 고르면 db.release_hold(send=True) → OPEN → 보냄
      대안이 하나도 없음 → NO_OPTION  종류와 상관없이 메시지를 보내지 않는다. 조교가 db.ack_no_option 으로
                                      '대안이 없어 보내지 못함'을 확인하면 OFFLINE(따로 연락) → db.manual_place
    - 같은 차수에 그 분반의 안건이 이미 있으면 다시 열지 않는다(두 번 불러도 안전).
    - 대안은 그 분반에 이미 보낸 대안과 겹치지 않는다(alternatives exclude_sent).
    -> [dict(proposal_id, course_id, section_no, kind, status, options)]"""
    out = []
    for t in (targets if targets is not None else coord_targets(con, term_id, round_id, timetable_id)):
        cid, sec, kind = t["course_id"], t["section_no"], t["kind"]
        if con.execute("SELECT 1 FROM proposal WHERE round_id=? AND course_id=? AND section_no IS ?",
                       (round_id, cid, sec)).fetchone():
            continue
        opts = alternatives(con, term_id, round_id, timetable_id, cid, sec, n=n, time_limit=time_limit,
                            weights=weights, workers=workers)
        pid = save_proposal(con, round_id, timetable_id, cid, opts, reason=t.get("reason", ""), section_no=sec,
                            target_kind=kind, status="HOLD" if kind == "PARTIAL" else "OPEN")
        st = con.execute("SELECT status FROM proposal WHERE id=?", (pid,)).fetchone()[0]
        out.append(dict(proposal_id=pid, course_id=cid, section_no=sec, kind=kind, status=st, options=len(opts)))
    return out


def fill_options(con, proposal_id, condition=None, n=3, time_limit=15, weights=None, workers=8):
    """다음 차수 안건(db.open_next_proposal 로 연 OPEN 안건, 대안 없음)에 대안 n개를 채운다.
    condition 은 이어받은 조건(db.carried_conditions). 이미 보낸 대안(이전 차수 포함)과 같은 안은 내지 않는다.
    대안이 하나도 없으면 안건을 NO_OPTION(보내지 않음, 조교 확인)으로 바꾼다. -> 채운 대안 수"""
    row = con.execute("""SELECT p.round_id, p.timetable_id, p.course_id, p.section_no, p.status, r.term_id
                         FROM proposal p JOIN round r ON r.id = p.round_id WHERE p.id=?""", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 조율 안건: {proposal_id}")
    round_id, tt, cid, sec, status, term_id = row
    if status != "OPEN":
        raise ValueError(f"보내기 전(OPEN) 안건만 대안을 채웁니다: 안건 {proposal_id} 상태 {status}")
    if con.execute("SELECT 1 FROM proposal_option WHERE proposal_id=?", (proposal_id,)).fetchone():
        raise ValueError(f"이미 대안이 있는 안건입니다: 안건 {proposal_id}")
    opts = alternatives(con, term_id, round_id, tt, cid, sec, condition=condition, n=n, time_limit=time_limit,
                        weights=weights, workers=workers)
    by_day = _day_ids(con, tt)
    for no, opt in enumerate(opts, 1):
        _write_option(con, proposal_id, no, opt, by_day)
    if not opts:
        con.execute("UPDATE proposal SET status='NO_OPTION' WHERE id=?", (proposal_id,))
    con.commit()
    return len(opts)


def finalize(con, timetable_id):
    """이 시간표를 확정(FINAL)한다. 같은 학기의 기존 FINAL은 DRAFT로 되돌린다.
    다음 해에 load_history가 이 시간표에서 건물·강의실 기본값을 읽는다."""
    term_id = con.execute("SELECT term_id FROM timetable WHERE id=?", (timetable_id,)).fetchone()[0]
    con.execute("UPDATE timetable SET kind='DRAFT' WHERE term_id=? AND kind='FINAL'", (term_id,))
    con.execute("UPDATE timetable SET kind='FINAL' WHERE id=?", (timetable_id,))
    con.commit()
