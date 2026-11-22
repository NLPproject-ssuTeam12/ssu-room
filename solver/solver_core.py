"""SSU:room 솔버 코어 (CP-SAT).

DB(schema.sql)에서 입력을 읽어 초안 시간표를 만들고 같은 DB에 저장한다.

모델
  결정변수 x[세션, 시작칸, 강의실묶음] = 1  → 이 수업 회차가 그 칸에서 시작해 그 묶음의 강의실 하나를 쓴다
  세션 = (과목, 분반번호, 회차번호). 분반 수는 교수들이 요청한 값을 교수별로 더한 것이다(솔버는 바꾸지 않는다).
    예) 가 2개 + 나 2개 요청 → 분반 4개 (1·2=가, 3·4=나). 응답이 없는 교수는 1개. 조교가 course_section 으로 지정한
    번호는 그대로 두고, 남은 개수를 빈 번호에 순서대로 채운다.
  분반마다 담당 교수가 다를 수 있다(course_section). 교수 겹침·응답(불가 시간·실습실·연강)은 분반의 교수 기준.
  강의실묶음 = 건물·정원·실습실 여부·전용 학과가 모두 같은 강의실들. 묶음 안의 방은 서로 구별할 필요가
              없으므로 변수를 줄이고(대칭 제거), 풀이 뒤에 실제 호실을 따로 배정한다.
  못 놓은 세션은 unplaced 변수로 큰 벌점을 주고 남긴다 → "못 맞춘 과목" 목록이 됨(2차 조율의 입력)

  용어 두 가지 (섞어 쓰지 말 것)
    주 1회 연강 = 한 분반이 하루에 2칸을 이어서 수업 (course_response.single_day_pref)
        MUST   하루에 연속 2칸 한 번으로만 배정
        NONE   1칸씩 두 번(이틀)으로만 배정
        PREFER 솔버가 고르되, 하루에 몰면 보너스   ※ 주당 2칸짜리 수업에만 적용
    분반 연강/교차 = 두 분반을 맡을 때 가반 끝나자마자 나반 (request_item SECTION_PAIR: BACK_TO_BACK / CROSS)
  실습실: 1(쓴다 → 실습실만 배정) / 0(안 쓴다 → 실습실 쓰면 약한 벌점). 희망 칸: PREFER(희망)/BLOCK(불가), 칠하지 않으면 상관없음
  선호 시간 외 불가(course_response.prefer_only=1): 그 분반은 '희망' 칸 안에서만 배정. 희망 칸이 없으면 적용하지 않고 지원불가 안내.

공개 함수
  solve(...)          전체 풀이 또는 일부 과목·분반만 다시 풀기(free_courses)
  alternatives(...)   못 놓은 과목(분반)의 대안 N개. 조율 쪽 조건(days/window/end_before 또는 slot_ids)을 받는다
  save_proposal(...)  대안을 proposal 테이블에 저장
  finalize(...)       시간표를 FINAL로 확정 (다음 해의 건물·강의실 기본값이 됨)
"""
import json
import math
from collections import defaultdict

from ortools.sat.python import cp_model

# 학년 겹침을 막을 과목 구분. 실제 학과 규칙에 맞게 바꿀 것.
REQUIRED_CATEGORIES = {"전공필수", "교양필수"}
GROUP_ROOMS = True   # False면 강의실마다 따로 변수를 만든다(비교 실험용)
DAYS = ["월", "화", "수", "목", "금", "토", "일"]   # 조율 쪽 days 번호: 0=월 … 4=금

DEFAULT_WEIGHTS = {
    "unplaced": 100000,   # 못 놓음
    "prefer": 10,         # 교수가 희망한 칸 (보너스)
    "building_rank": 3,   # 희망 건물 순위당 벌점 (1순위 3점, 2순위 6점, 목록 밖은 꼴찌 순위+1)
    "lab_waste": 5,       # 실습실을 안 쓴다고 답한 수업(0)이 실습실 사용
    "single_day_prefer": 12,  # 주 1회 연강 '선호'인데 이틀로 나눴을 때 벌점(= 하루에 몰면 보너스)
    "keep": 30,           # 이전 배정을 그대로 두면 보너스 (최소 변경)
    "history_room": 8,    # 회신 안 한 교수: 전년에 같은 과목을 한 강의실이면 보너스
}


# ---------------------------------------------------------------- 입력
def load_history(con, term_id):
    """전년도 같은 학기의 FINAL 시간표에서 교수별 건물 순위와 (교수, 과목명)별 강의실을 뽑는다.
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
    for prof, cnt in bld_count.items():          # 많이 쓴 건물이 1순위
        order = sorted(cnt, key=lambda b: -cnt[b])
        hist_bld[prof] = {b: i + 1 for i, b in enumerate(order)}
    return hist_bld, dict(hist_room)


def load_input(con, term_id, round_id):
    """-> by_day, courses, secs, rooms, pref, slot_info
    secs[(과목, 분반)] = 그 분반의 담당 교수와 그 교수의 응답(불가·희망 칸, 실습실, 연강)"""
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
    for (cid, name, prof, dept, cat, yr, enr, sc, sps) in q(
            """SELECT id, name, professor_id, department_id, category, target_year,
                      expected_enrollment, session_count, slots_per_session
               FROM course WHERE term_id=?""", (term_id,)):
        courses[cid] = dict(id=cid, name=name, prof=prof, dept=dept, cat=cat, year=yr,
                            enroll=enr or 0, sessions=sc, k=sps, sections=1, pair=None)
    section_prof = {(c, s): p for c, s, p in q("SELECT course_id, section_no, professor_id FROM course_section")
                    if c in courses}
    resp = {}                                   # (과목, 교수) -> 응답
    for rid, cid, prof, lab, single_day, prefer_only in q(
            """SELECT id, course_id, professor_id, lab_requirement, single_day_pref, prefer_only
               FROM course_response WHERE round_id=?""", (round_id,)):
        if cid not in courses:
            continue
        r = dict(lab=lab, single_day=single_day, prefer_only=bool(prefer_only),
                 block=set(), prefer=set(), id=rid)
        for sid, kind in q("SELECT slot_id, kind FROM response_slot WHERE response_id=?", (rid,)):
            r[{"BLOCK": "block", "PREFER": "prefer"}[kind]].add(sid)
        resp[(cid, prof)] = r
    # 분반 수와 분반별 담당 교수
    #   - 각 교수가 요청한 분반 수(SECTION_COUNT, 없으면 조교가 지정한 분반 수, 최소 1)를 교수별로 구해 합산한다.
    #     (가 교수 2개 + 나 교수 2개 = 4개)
    #   - 교수 순서: 기본 담당 교수 → 조교가 지정한 교수(분반 번호 순) → 그 외 응답한 교수(번호 순)
    #   - 조교가 course_section에 적은 분반은 그 번호·그 교수로 먼저 확정하고, 남은 개수를 빈 번호에 순서대로 채운다.
    asked = {}                                   # (과목, 교수) -> 요청한 분반 수
    for cid, prof, n in q("""SELECT r.course_id, r.professor_id, MAX(i.value_int) FROM request_item i
                          JOIN course_response r ON r.id=i.response_id
                          WHERE r.round_id=? AND i.type='SECTION_COUNT' GROUP BY r.course_id, r.professor_id""", (round_id,)):
        if n:
            asked[(cid, prof)] = n
    for c in courses.values():
        cid = c["id"]
        explicit = {sec: p for (cc, sec), p in section_prof.items() if cc == cid}
        involved = [c["prof"]]
        for sec in sorted(explicit):
            if explicit[sec] not in involved:
                involved.append(explicit[sec])
        for (cc, p) in sorted(resp):
            if cc == cid and p not in involved:
                involved.append(p)
        remaining = []                           # 조교가 지정하지 않은 만큼 (요청 분반 수 - 지정한 수)
        for p in involved:
            own = sum(1 for v in explicit.values() if v == p)
            remaining += [p] * max(max(asked.get((cid, p), 0), own, 1) - own, 0)
        n_sec = max(max(explicit, default=0), len(explicit) + len(remaining))
        fill = iter(remaining)                   # 지정 안 된 번호에 순서대로
        c["sections"] = n_sec
        c["section_prof"] = {sec: explicit.get(sec) or next(fill, c["prof"]) for sec in range(1, n_sec + 1)}
    for cid, mode in q("""SELECT r.course_id, i.value_text FROM request_item i
                       JOIN course_response r ON r.id=i.response_id
                       WHERE r.round_id=? AND i.type='SECTION_PAIR'""", (round_id,)):
        if cid in courses:
            courses[cid]["pair"] = mode        # BACK_TO_BACK(분반 연강: 가반 직후 나반) / CROSS(교차)
    secs = {}
    for c in courses.values():
        for sec in range(1, c["sections"] + 1):
            prof = c["section_prof"][sec]
            r = resp.get((c["id"], prof))
            secs[(c["id"], sec)] = dict(
                prof=prof, responded=r is not None,
                lab=r["lab"] if r else None, single_day=r["single_day"] if r else None,
                prefer_only=r["prefer_only"] if r else False,
                block=r["block"] if r else set(), prefer=r["prefer"] if r else set(),
                )
    rooms = {rid: dict(id=rid, bld=b, cap=cap, lab=lab or 0, dept=rd)
             for rid, b, cap, lab, rd in q(
                 "SELECT id, building_id, capacity, is_lab, reserved_department_id FROM room")}
    pref = defaultdict(dict)                   # professor -> {building: rank}
    for p, b, r in q("SELECT professor_id, building_id, rank FROM professor_building_pref"):
        pref[p][b] = r
    return by_day, courses, secs, rooms, pref, slot_info


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
    주당 2칸짜리 수업이고 교수가 연강을 답했을 때만 '연속 2칸 한 번'과 '1칸 두 번'을 오간다."""
    fixed = [(ss, c["k"]) for ss in range(1, c["sessions"] + 1)]
    if c["sessions"] * c["k"] == 2 and sd["single_day"] and not c["pair"]:
        long_, split = [(1, 2)], [(1, 1), (2, 1)]
        return {"MUST": [long_], "NONE": [split], "PREFER": [long_, split]}[sd["single_day"]]
    return [fixed]


# ---------------------------------------------------------------- 모델
def _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk, free,
                 seed, forbid=None, must_sections=None, cond=None, cond_sections=None):
    """모델을 만들어 풀고 결과를 메모리로 돌려준다(DB에는 쓰지 않음).
    prev/prevk: 이전 시간표 {(과목,분반,회차): (시작칸, 강의실)} / {(과목,분반,회차): 칸 수}
    free: None이면 전부 새로 풀고, 집합(과목 id 또는 (과목,분반))이면 그 분반만 풀고 나머지는 prev 그대로 고정
    forbid: [(dict(세션키 -> 시작칸), 허용되는 같은 칸 수)]  대안끼리 달라지게 하는 금지 조건
    must_sections: 모든 회차를 반드시 놓아야 하는 (과목, 분반) 집합
    cond/cond_sections: 조율 쪽 조건(요일·시간대)과 그것이 적용될 (과목, 분반) 집합"""
    by_day, courses, secs, rooms, pref, slot_info = load_input(con, term_id, round_id)
    hist_bld, hist_room = load_history(con, term_id)
    classes, room2class = make_classes(rooms)

    def is_free(cid, sec):
        return free is None or cid in free or (cid, sec) in free

    prev_by_sec = defaultdict(dict)
    for (c, s, ss), v in prev.items():
        prev_by_sec[(c, s)][ss] = v

    m = cp_model.CpModel()
    x, cost = {}, {}
    occ_room, occ_prof = defaultdict(list), defaultdict(list)
    cohort_vars = defaultdict(list)
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
        enroll_per = math.ceil(c["enroll"] / n) if c["enroll"] else 0
        for sec in range(1, n + 1):
            sd = secs[(c["id"], sec)]
            cid = c["id"]
            if c["pair"] and sd["single_day"] in ("MUST", "PREFER"):
                unsupported.append((cid, "주 1회 연강 응답과 분반 연강·교차 요청을 함께 받으면 분반 요청을 우선하고 주 1회 연강 응답은 무시"))
            if sd["prefer_only"] and not sd["prefer"]:
                msg = (cid, "'선호 시간 외 불가'를 골랐는데 희망 칸이 없어 이 제한은 적용하지 않음")
                if msg not in unsupported:
                    unsupported.append(msg)
            structs = _structures(c, sd)
            ps = sorted((ss, prevk[(cid, sec, ss)]) for ss in prev_by_sec.get((cid, sec), {}))
            matched = next((st for st in structs if sorted(st) == ps), None) if ps else None
            frozen = (not is_free(cid, sec)) and matched is not None
            if frozen:
                structs = [matched]
                frozen_secs.add((cid, sec))
            choice = None
            if len(structs) == 2:
                choice = m.NewBoolVar(f"single_day{cid}_{sec}")        # 1이면 하루에 연속 2칸(첫 번째 구성)
                cost[("choice", cid, sec)] = (choice, -W["single_day_prefer"])
                if prev and matched is not None:
                    m.AddHint(choice, 1 if structs.index(matched) == 0 else 0)   # 이전 구성도 출발점으로
            bp = pref.get(sd["prof"]) or (hist_bld.get(sd["prof"]) if not sd["responded"] else None)
            hroom = hist_room.get((sd["prof"], c["name"]), set()) if not sd["responded"] else set()
            use_cond = bool(cond) and (cid, sec) in (cond_sections or ()) and not frozen

            for si, struct in enumerate(structs):
                act = 1 if choice is None else (choice if si == 0 else choice.Not())
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
                            if not frozen and sd["prefer_only"] and sd["prefer"] and not set(covered) <= sd["prefer"]:
                                continue                    # '선호 시간 외에는 어려움': 희망 칸 안에서만
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
                                    if cl["cap"] is not None and enroll_per and cl["cap"] < enroll_per:
                                        continue
                                    if sd["lab"] == 1 and not cl["lab"]:
                                        continue
                                    if cl["dept"] is not None and cl["dept"] != c["dept"]:
                                        continue
                                var = m.NewBoolVar(f"x{skey}{covered[0]}_{cl['id']}")
                                x[(skey, covered[0], cl["id"])] = var
                                day_terms[skey].append(day_idx[day] * var)     # 이 회차의 요일 번호
                                per_terms[skey].append(chunk[0][0] * var)      # 이 회차의 교시 번호
                                feasible.append(var)
                                if use_cond and cond_single_day == day:
                                    cond_day_vars.append(var)
                                w = 0                       # 고정된 세션은 상수라 0
                                if not frozen:
                                    w -= W["prefer"] * len(sd["prefer"] & set(covered))
                                    if bp:
                                        w += W["building_rank"] * (bp[cl["bld"]] if cl["bld"] in bp else max(bp.values()) + 1)
                                    if cl["lab"] and sd["lab"] == 0:
                                        w += W["lab_waste"]          # 미회신(None)에는 가정하지 않음
                                    if hroom and hroom & set(cl["rooms"]):
                                        w -= W["history_room"]
                                same = (key in prev and prevk.get(key) == k and prev[key][0] == covered[0]
                                        and room2class[prev[key][1]] == cl["id"])
                                if same and not frozen:
                                    w -= W["keep"]
                                if prev:
                                    m.AddHint(var, 1 if same else 0)     # 이전 해를 출발점으로 알려 줌
                                cost[var.Index()] = (var, w)
                                for sid in covered:
                                    occ_room[(cl["id"], sid)].append(var)
                                    occ_prof[(sd["prof"], sid)].append(var)
                                    if c["cat"] in REQUIRED_CATEGORIES and c["year"]:
                                        cohort_vars[((c["dept"], c["year"]), cid, sid)].append(var)
                                day_use[(cid, sec, day)].append(var)
                    un = m.NewBoolVar(f"un{skey}")
                    unplaced[skey] = un
                    m.Add(sum(feasible) + un == act)
                    if frozen or (must_sections and (cid, sec) in must_sections):
                        m.Add(un == 0)                       # 고정된 수업·반드시 놓을 수업은 빠질 수 없다

    cap_of = {cl["id"]: len(cl["rooms"]) for cl in classes}
    for (clid, sid), vs in occ_room.items():
        if len(vs) > cap_of[clid]:
            m.Add(sum(vs) <= cap_of[clid])               # 같은 칸에 그 묶음의 방 수보다 많이 못 씀
    for vs in occ_prof.values():
        if len(vs) > 1: m.Add(sum(vs) <= 1)              # 같은 교수 동시 수업 불가
    for vs in day_use.values():
        if len(vs) > 1: m.Add(sum(vs) <= 1)              # 같은 분반은 하루 한 번
    by_cohort_slot = defaultdict(list)
    for (coh, cid, sid), vs in cohort_vars.items():
        b = m.NewBoolVar(f"cohort{coh}{cid}{sid}")
        for v in vs:
            m.AddImplication(v, b)
        by_cohort_slot[(coh, sid)].append(b)
    for bs in by_cohort_slot.values():
        if len(bs) > 1: m.Add(sum(bs) <= 1)              # 같은 학년 필수과목끼리 겹침 불가
    if cond_single_day is not None:
        if cond_day_vars:
            m.Add(sum(cond_day_vars) >= 1)               # 요일이 하나면 그 요일이 들어간 안
        else:
            m.Add(0 >= 1)                                # 후보가 없음 → 불가능

    # 한 교수의 두 분반 연강/교차 (요청한 과목만)
    for c in courses.values():
        if not c["pair"]:
            continue
        if c["sections"] != 2 or c["k"] != 1:
            unsupported.append((c["id"], "분반이 정확히 2개이고 1회 수업이 한 칸일 때만 지원"))
            continue
        S = c["sessions"]
        K = lambda sec, ss: (c["id"], sec, ss, 1)
        if any(K(1, ss) not in unplaced or K(2, ss) not in unplaced for ss in range(1, S + 1)):
            continue
        for ss in range(1, S + 1):
            A, B = K(1, ss), K(2, ss)
            lits = [unplaced[A].Not(), unplaced[B].Not()]
            dA, dB = sum(day_terms[A]), sum(day_terms[B])
            pA, pB = sum(per_terms[A]), sum(per_terms[B])
            m.Add(dA == dB).OnlyEnforceIf(lits)                    # 같은 요일
            up = m.NewBoolVar(f"adj{c['id']}_{ss}")                # 가반이 먼저(1) 또는 나반이 먼저
            m.Add(pB - pA == 1).OnlyEnforceIf(lits + [up])         # 바로 붙은 교시
            m.Add(pA - pB == 1).OnlyEnforceIf(lits + [up.Not()])
        if c["pair"] == "CROSS" and S == 2:
            A1, A2, B1, B2 = K(1, 1), K(1, 2), K(2, 1), K(2, 2)
            lits = [unplaced[k].Not() for k in (A1, A2, B1, B2)]
            m.Add(sum(per_terms[A1]) == sum(per_terms[B2])).OnlyEnforceIf(lits)   # 가1 = 나2 교시
            m.Add(sum(per_terms[A2]) == sum(per_terms[B1])).OnlyEnforceIf(lits)   # 가2 = 나1 교시
        elif c["pair"] == "CROSS":
            unsupported.append((c["id"], "교차 배정은 주 2회 수업일 때만 지원"))

    # 대안끼리 달라지게: 이미 나온 대안과 같은 칸을 쓰는 회차 수를 제한
    for mapping, max_same in (forbid or []):
        same_terms = []
        for key, start in mapping.items():
            same_terms += [v for (sk, st, cl), v in x.items() if sk[:3] == key and st == start]
        if same_terms:
            m.Add(sum(same_terms) <= max_same)

    m.Minimize(sum(w * v for v, w in cost.values()) + W["unplaced"] * sum(unplaced.values()))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = workers
    s.parameters.random_seed = seed
    status = s.Solve(m)
    status_name = s.StatusName(status)
    out = dict(status=status_name, unsupported=unsupported, courses=courses, secs=secs, rooms=rooms,
               classes=classes, room2class=room2class, by_day=by_day, hist_room=hist_room)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out.update(placements=None, ks=None, unplaced=[], objective=None, seconds=s.WallTime())
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
    out.update(placements=placements, ks=ks, unplaced=left, objective=s.ObjectiveValue(), seconds=s.WallTime())
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
            con.execute("INSERT INTO timetable_section VALUES (?,?,?,?)",
                        (tt, c["id"], sec, math.ceil(c["enroll"] / n) if c["enroll"] else None))
    sorted_days = {d: sorted(p) for d, p in by_day.items()}
    for key, (start, room_id) in out["placements"].items():
        for sid in _covered(start, out["ks"][key], sorted_days):
            con.execute("INSERT INTO assignment VALUES (?,?,?,?,?,?)", (tt, key[0], key[1], key[2], sid, room_id))
    con.commit()
    return run_id, tt


def _covered(start, k, sorted_days):
    for d, pl in sorted_days.items():
        ids = [sid for _, sid in pl]
        if start in ids:
            i = ids.index(start)
            return ids[i:i + k]
    return [start]


# ---------------------------------------------------------------- 공개 함수
def solve(con, term_id, round_id, weights=None, time_limit=30, workers=8,
          previous_timetable_id=None, free_courses=None, created_by=None, seed=0):
    """전체 풀이. previous_timetable_id를 주면 그 시간표를 출발점·유지 보너스로 쓴다.
    free_courses(과목 id 또는 (과목 id, 분반) 집합)까지 주면 그것만 다시 풀고 나머지는 이전 시간표 그대로 고정한다."""
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    prev, prevk = load_assignment(con, previous_timetable_id) if previous_timetable_id else ({}, {})
    if free_courses is not None and not prev:
        raise ValueError("free_courses는 previous_timetable_id와 함께 써야 합니다")
    out = _solve_model(con, term_id, round_id, W, time_limit, workers, prev, prevk,
                       set(free_courses) if free_courses is not None else None, seed)
    run_id, tt = _persist(con, out, term_id, round_id, W, time_limit, previous_timetable_id, created_by)
    return dict(status=out["status"], run_id=run_id, timetable_id=tt, unplaced=out["unplaced"],
                objective=out["objective"], seconds=out["seconds"], unsupported=out["unsupported"])


def alternatives(con, term_id, round_id, timetable_id, course_id, section_no=None, condition=None,
                 n=3, time_limit=15, weights=None, workers=8):
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
    2단계(모자라면): 같은 교수의 다른 분반과 같은 학년 필수과목까지 움직일 수 있게 하고, 움직인 수업을 함께 알려 준다.
    반환: [dict(stage, placements{(분반,회차):(시작칸,강의실)}, ks{(분반,회차):칸 수}, moves[(키,이전,이후)], objective)]"""
    W = {**DEFAULT_WEIGHTS, **(weights or {})}
    prev, prevk = load_assignment(con, timetable_id)
    _, courses, secs, _, _, slot_info = load_input(con, term_id, round_id)
    if condition and condition.get("day_slots") is not None:
        condition = _apply_day_slots(condition, slot_info)
    target = courses[course_id]
    t_secs = {(course_id, s) for s in (range(1, target["sections"] + 1) if section_no is None else [section_no])}
    t_profs = {secs[ts]["prof"] for ts in t_secs}
    expanded = set(t_secs)
    for (cid, sec), sd in secs.items():
        c = courses[cid]
        if sd["prof"] in t_profs or (c["cat"] in REQUIRED_CATEGORIES and target["cat"] in REQUIRED_CATEGORIES
                                     and c["dept"] == target["dept"] and c["year"] == target["year"]):
            expanded.add((cid, sec))
    stages = [("다른 수업은 그대로", t_secs),
              ("같은 교수·같은 학년 필수과목 일부 이동", expanded)]
    results = []
    forbid = []
    cur = {k: v[0] for k, v in prev.items() if (k[0], k[1]) in t_secs}
    if cur:
        forbid.append((cur, 0))                              # 현재 배정과 같은 안은 대안이 아니다
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
                                   cond=condition, cond_sections=t_secs)
                if out["placements"] is not None or not forbid:
                    break
            if out is None or out["placements"] is None:
                break
            pl = out["placements"]
            mapping = {k: v[0] for k, v in pl.items() if (k[0], k[1]) in t_secs}
            if not mapping:
                break
            moves = [(k, prev[k], pl[k]) for k in pl
                     if k in prev and (k[0], k[1]) not in t_secs and pl[k] != prev[k]]
            results.append(dict(stage=stage_name,
                                placements={k[1:]: v for k, v in pl.items() if (k[0], k[1]) in t_secs},
                                ks={k[1:]: out["ks"][k] for k in pl if (k[0], k[1]) in t_secs},
                                moves=moves, objective=out["objective"]))
            forbid.append((mapping, 0))
    return results


make_alternatives = alternatives          # 조율 쪽 이름


def save_proposal(con, round_id, timetable_id, course_id, options, reason="", section_no=None):
    """alternatives() 결과를 proposal 테이블에 저장한다. 조교가 교수에게 보낼 메시지의 근거가 된다."""
    pid = con.execute("INSERT INTO proposal(round_id, timetable_id, course_id, section_no, reason) VALUES (?,?,?,?,?)",
                      (round_id, timetable_id, course_id, section_no, reason)).lastrowid
    by_day = defaultdict(list)
    for sid, day in con.execute("""SELECT ts.id, ts.day FROM time_slot ts
             JOIN term t ON t.grid_id=ts.grid_id JOIN timetable tt ON tt.term_id=t.id
             WHERE tt.id=? ORDER BY ts.day, ts.period_no""", (timetable_id,)):
        by_day[day].append(sid)
    for no, opt in enumerate(options, 1):
        oid = con.execute("INSERT INTO proposal_option(proposal_id, option_no, source) VALUES (?,?,?)",
                          (pid, no, "SOLVER")).lastrowid
        for (sec, ss), (start, room) in opt["placements"].items():
            for d, ids in by_day.items():
                if start in ids:
                    i = ids.index(start)
                    for sid in ids[i:i + opt["ks"][(sec, ss)]]:
                        con.execute("INSERT INTO proposal_option_slot VALUES (?,?,?,?,?)", (oid, sec, ss, sid, room))
    con.commit()
    return pid


def finalize(con, timetable_id):
    """이 시간표를 확정(FINAL)한다. 같은 학기의 기존 FINAL은 DRAFT로 되돌린다.
    다음 해에 load_history가 이 시간표에서 건물·강의실 기본값을 읽는다."""
    term_id = con.execute("SELECT term_id FROM timetable WHERE id=?", (timetable_id,)).fetchone()[0]
    con.execute("UPDATE timetable SET kind='DRAFT' WHERE term_id=? AND kind='FINAL'", (term_id,))
    con.execute("UPDATE timetable SET kind='FINAL' WHERE id=?", (timetable_id,))
    con.commit()
