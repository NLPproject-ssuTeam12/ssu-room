"""강의정보 엑셀(2026-2) → 문하윤 DB(db/schema.sql) 시드 + 분반 대응표 (백엔드 ③, 김대원).

사용 (저장소 맨 위에서):
    python backend/tools/seed_db.py                          # 기본 엑셀 → ssuroom.db, data/private/real/section_map.json
    python backend/tools/seed_db.py --xlsx 다른.xlsx --db 다른.db

엑셀 열: 이수구분(주전공)·과목번호·과목명·분반·교수명·시간/학점·수강인원·강의시간(강의실)·수강대상.

- 교수 실명은 가명(교수01…)으로 바꾼다. 대응은 data/private/alias_map.json 에만 둔다(출력하지 않음).
  강의시간(강의실) 칸의 '-이름' 부분도 버린다. 끝에 DB·대응표·출력 전체를 실명으로 검색해 0건인지 본다.
- 과목 = 과목번호 끝 두 자리를 뺀 것. 분반 = 그 과목의 행들(1부터 다시 번호, 원래 번호·분반 표기는 대응표에).
  분반 인원 = 수강인원. 학년 = 수강대상의 'N학년'(없으면 비움). 이수구분 '전필-…' → '전공필수'(엔진 MAJOR_REQUIRED),
  '교필…' → '교양필수', 전기·전선은 원래 값 그대로(엔진은 필수과목만 이름으로 본다).
- 강의시간에서 회차·칸 수를 읽는다: 75분 수업 두 번(다른 요일) = 주 2회, 같은 날 이어진 두 칸 = 주 1회 연강.
  토요일·교시 밖·강의시간 없음·교수 여러 명·그 밖의 모양은 MANUAL(DB에 넣지 않고 대응표에 표시).
- 강의실: 강의시간의 건물·호수. 정원은 data/private/real/rooms.json, 없으면 그 방을 쓰는 분반 인원 최댓값(추정, 대응표에 표시).
  실습실은 11/24 회의에서 정한 8개(LABS).
- 희망(가상, 분반마다): 실제 강의 칸을 PREFER, 실습실을 쓰면 실습실 MUST, 하루 두 칸 이어서면 주 1회 연강 MUST.
  분반 연강·교차는 없음. 교수 희망 건물 = 그 교수가 가장 많이 쓴 건물 하나.
- 채플: data/private/real/fixed_blocks.json 의 채플(AI대학 대상) 칸 → 학년별 chapel_slot. 교양필수 고정 시간은 넣지 않는다.
- 조교 계정 하나(user role TA, 이름 '조교')를 만든다(조교 결정 함수가 조교만 받음).
- 전 학기(2026-1) 기록은 넣지 않는다: 엔진 load_history 는 전년도 같은 학기만 읽는다.
- 수강 인원(11/27 팀 결정): 화면은 5명 단위로 받으므로 엑셀 수강인원을 가장 가까운 5의 배수로 반올림해 넣는다
  (22→20, 23→25, 28→30, 최소 5). 엑셀 원래 값은 대응표에 enrollment_orig 로 남긴다. 추정 정원도 반올림한 인원 기준.
- --blank-prof (기본 꺼짐, 11/27 팀 결정): 희망 수집 시연용으로 교수 한 명의 희망을 비워 둔다. 그 교수가 시연에서
  화면으로 직접 입력한다. 값 없이 주면 자동으로 고르고(같은 과목 분반 둘 이상·MANUAL 분반 없음·--demo 가 바꾼
  분반 없음, 가명 순 첫째), 가명을 주면 그 교수. 빼는 것: 분반 희망 응답·칠한 칸(실습실·주 1회 연강 포함)·희망 건물·
  분반 인원(NULL). 남기는 것: 과목·분반·담당 교수(course_section)와 그 밖의 DB. --demo 다음에 적용한다.
- 희망 넓히기(11/27 팀 결정, 기본 켬): 가상 희망이 실제 수업 칸만이면 엔진이 고를 게 없어서, 분반마다 고정 난수로
  실제 칸만(exact) / 같은 요일 앞뒤 칸까지(adjacent) / 다른 요일 쌍의 같은 시각도(other_days) / 넓게 + 하루 불가
  (wide_block) 중 하나를 칠한다. 실제 칸은 늘 희망, 19:30·채플(그 학년 전공필수)·18:00 이후 시작 연강 칸은 칠하지 않는다.
  --demo 가 바꾼 분반과 --blank-prof 분반은 넓히지 않는다. --narrow 면 예전처럼 실제 칸만. 대응표 wish_kind.
- 가상 임용 연도(재성 #37 리뷰, 팀 결정): 교수마다 user.hire_year 를 1995~2024 사이로 넣는다(하윤 db.set_hire_year).
  가명과 고정 시드로 정해서 처리 순서와 상관없이 같은 엑셀이면 같은 값. 조교는 넣지 않고, --blank-prof 교수도 넣는다
  (희망만 비움). 배정 엔진은 동점일 때 먼저 임용된 교수를 앞에 둔다. --no-hire-year 면 예전처럼 비운다. 대응표 hire_years.
- --demo (기본 꺼짐): 시연용으로 일부 분반의 **가상 희망만** 서로 겹치게 바꾼다 (과목·분반·강의실·인원은 그대로).
  고정 난수 시드로 늘 같은 분반을 고른다. 바꾼 분반은 출력하고 대응표에 "demo_changed"(무엇을 바꿨는지)로 남긴다.
    겹침(MISMATCH → OPEN)  같은 교수의 다른 분반이 그 칸만 되게 막고, 이 분반은 그 칸만 희망 → 희망 칸을 하나도 못 받음
    일부 겹침(PARTIAL → HOLD) 희망 두 칸 중 한 칸을 같은 교수 다른 분반(그 칸만 됨)의 칸으로 → 한 회차만 어긋남
    대안 없음(NO_OPTION)    모든 칸을 불가로 → 못 놓고 대안도 없음
대응표(section_map.json)는 서버·어댑터가 읽는다. data/private 아래라 커밋하지 않는다.
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE = REPO_ROOT / "data" / "private"
DEFAULT_XLSX = PRIVATE / "timetable" / "2026-2_강의정보.xlsx"

STARTS = ("09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30")
DAYS = ("월", "화", "수", "목", "금")
# 11/24 회의: 실습실 8개 (21206·21306은 엑셀에 표기가 없지만 실습실)
LABS = {"정보과학관 21101", "정보과학관 21206", "정보과학관 21305", "정보과학관 21306",
        "문화관 03407", "문화관 03408", "문화관 03411", "전산관 19328"}
CATEGORY = (("전필", "전공필수"), ("교필", "교양필수"))
DEPARTMENTS = {"AI소프트웨어": "AI소프트웨어학부", "정보보호": "정보보호학과"}
COLLEGE = "AI융합대학"   # 가정한 이름
TA_NAME = "조교"
LINE = re.compile(r"^([월화수목금토일](?: [월화수목금토일])*) (\d\d:\d\d)-(\d\d:\d\d) \((.*)\)$")
COLUMNS = ("이수구분(주전공)", "과목번호", "과목명", "분반", "교수명", "수강인원", "강의시간(강의실)", "수강대상")


# ---------- 엑셀 읽기 (실명이 들어 있으므로 결과를 출력하지 않는다) ----------

def _mins(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _hhmm(x: int) -> str:
    return f"{x // 60:02d}:{x % 60:02d}"


def room_of(raw: str) -> Optional[str]:
    """'정보과학관 21305 (이철희실습실)-이름' → '정보과학관 21305'. 이름 부분은 버린다."""
    body = raw.rsplit("-", 1)[0].strip()
    m = re.match(r"(\S+)\s+(\d{5})", body)
    return f"{m.group(1)} {m.group(2)}" if m else None


def read_excel(path: Path) -> List[dict]:
    """엑셀 행 → [dict(code, name, division, category, prof_real, enrollment, year, meets[(요일, 시작분, 끝분, 강의실)])]."""
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h).strip() if h is not None else "" for h in rows[0]]
    missing = [c for c in COLUMNS if c not in head]
    if missing:
        raise ValueError(f"엑셀에 열이 없습니다: {missing}")
    out = []
    for r in rows[1:]:
        d = dict(zip(head, r))
        if not d.get("과목번호"):
            continue
        meets = []
        for line in str(d.get("강의시간(강의실)") or "").split("\n"):
            m = LINE.match(line.strip())
            if not m:
                continue
            for day in m.group(1).split():
                meets.append((day, _mins(m.group(2)), _mins(m.group(3)), room_of(m.group(4))))
        grade = re.match(r"\s*(\d)학년", str(d.get("수강대상") or ""))
        out.append(dict(
            code=str(d["과목번호"]).strip(), name=str(d["과목명"]).strip(),
            division=(str(d.get("분반") or "").strip() or None),
            category=(str(d.get("이수구분(주전공)") or "").strip() or None),
            prof_real=str(d.get("교수명") or "").strip(),
            enrollment=int(d["수강인원"]) if d.get("수강인원") else None,
            year=int(grade.group(1)) if grade else None,
            meets=meets,
        ))
    return out


# ---------- 순수 함수 ----------

def db_category(cat: Optional[str]) -> Optional[str]:
    if not cat:
        return cat
    for prefix, name in CATEGORY:
        if cat.startswith(prefix):
            return name
    return cat


def department_of(cat: Optional[str]) -> str:
    tail = (cat or "").partition("-")[2]
    return DEPARTMENTS.get(tail, DEPARTMENTS["AI소프트웨어"])


def section_id(row: dict) -> str:
    """서버 분반 id: 과목번호, 공통 분반이면 '과목번호-(공통-재수강)' (기존 모양과 같게)."""
    return row["code"] + (f"-{row['division']}" if row["division"] else "")


def shape_of(row: dict) -> Tuple[str, List[dict], str]:
    """-> (TWICE | ONCE_LONG | MANUAL, 수업 칸 [{day, start, slots, room}], MANUAL 이유)."""
    ms = sorted(row["meets"], key=lambda m: (("월화수목금토일").index(m[0]), m[1]))
    raw = [dict(day=d, start=_hhmm(s), slots=max(1, round((e - s + 15) / 90)), room=r) for d, s, e, r in ms]
    if not ms:
        return "MANUAL", raw, "강의시간 없음"
    if not row["prof_real"]:
        return "MANUAL", raw, "담당 교수 없음"
    if "\n" in row["prof_real"] or "," in row["prof_real"]:
        return "MANUAL", raw, "교수 여러 명"
    if any(m[0] not in DAYS for m in ms):
        return "MANUAL", raw, "토·일요일 수업"
    if any(m[3] is None for m in ms):
        return "MANUAL", raw, "강의실 없음"
    if not all(m[2] - m[1] == 75 and _hhmm(m[1]) in STARTS for m in ms):
        return "MANUAL", raw, "교시 밖 시각"
    if len(ms) == 2 and ms[0][0] != ms[1][0]:
        return "TWICE", [dict(day=d, start=_hhmm(s), slots=1, room=r) for d, s, e, r in ms], ""
    if len(ms) == 2 and ms[0][0] == ms[1][0] and ms[1][1] - ms[0][2] == 15:
        if ms[0][3] != ms[1][3]:
            return "MANUAL", raw, "연강 두 칸의 강의실이 다름"
        if ms[0][1] >= _mins("18:00"):
            return "MANUAL", raw, "18:00 이후 시작 연강"
        d, s, _, r = ms[0]
        return "ONCE_LONG", [dict(day=d, start=_hhmm(s), slots=2, room=r)], ""
    return "MANUAL", raw, f"주 2칸 모양이 아님 (수업 {len(ms)}번)"


def round5(n: Optional[int]) -> Optional[int]:
    """수강 인원 → 가장 가까운 5의 배수 (2.5 이상 올림), 최소 5. 22→20, 23→25, 28→30, 3→5. 없으면 None."""
    if n is None:
        return None
    return max(5, int(n / 5 + 0.5) * 5)


def make_aliases(rows: List[dict], old: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """실명 → 가명(교수01…). 이미 있는 대응은 그대로 두고 새 이름만 다음 번호로."""
    alias = dict(old or {})
    n = max([int(a[2:]) for a in alias.values() if re.fullmatch(r"교수\d+", a)] or [0])
    for r in rows:
        name = r["prof_real"]
        if name and name not in alias:
            n += 1
            alias[name] = f"교수{n:02d}"
    return alias


def cells_of(blocks: List[dict]) -> List[str]:
    """수업 칸 → 희망 칸 이름 ['월-09:00', ...] (연강은 두 칸)."""
    out = []
    for b in blocks:
        i = STARTS.index(b["start"])
        out += [f"{b['day']}-{STARTS[j]}" for j in range(i, i + b["slots"])]
    return out


def build_plan(rows: List[dict], alias: Dict[str, str], rooms_info: Dict[str, dict], fixed: List[dict]) -> dict:
    """엑셀 행 → DB에 넣을 계획. 교수는 가명만 담는다."""
    sections = []
    for r in rows:
        shape, blocks, why = shape_of(r)
        sections.append(dict(
            section_id=section_id(r), code=r["code"], name=r["name"], division=r["division"],
            category_orig=r["category"], category=db_category(r["category"]), department=department_of(r["category"]),
            professor=alias.get(r["prof_real"]) if r["prof_real"] else None,
            enrollment=round5(r["enrollment"]), enrollment_orig=r["enrollment"],   # 5명 단위로 반올림 (11/27)
            year=r["year"], shape=shape, blocks=blocks, manual_reason=why or None,
        ))
    ids = Counter(s["section_id"] for s in sections)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise ValueError(f"서버 분반 id가 겹칩니다: {dup}")

    by_course: Dict[str, List[dict]] = defaultdict(list)
    for s in sections:
        if s["shape"] != "MANUAL":
            by_course[s["code"][:-2]].append(s)
    courses = []
    for cid, base in enumerate(sorted(by_course), start=1):
        secs = sorted(by_course[base], key=lambda s: (s["code"][-2:], s["section_id"]))
        years = Counter(s["year"] for s in secs if s["year"] is not None)
        courses.append(dict(course_id=cid, code=base, name=secs[0]["name"], category=secs[0]["category"],
                            category_orig=secs[0]["category_orig"], department=secs[0]["department"],
                            target_year=str(years.most_common(1)[0][0]) if years else None,
                            professor=secs[0]["professor"]))
        for no, s in enumerate(secs, start=1):
            s.update(course_id=cid, section_no=no, orig_section_no=s["code"][-2:])

    # 강의실: 엑셀에 나온 호수 (MANUAL 분반 포함). 추정 정원은 반올림한 인원 기준 (반올림 때문에 원래 그 방을
    # 쓰던 분반이 정원 초과가 되지 않게)
    used: Dict[str, List[int]] = defaultdict(list)
    for s in sections:
        for b in s["blocks"]:
            if b["room"]:
                used[b["room"]].append(s["enrollment"] or 0)
    rooms = []
    for rid in sorted(used):
        info = rooms_info.get(rid)
        cap = info["capacity"] if info and info.get("capacity") else None
        est = cap is None or bool(info and info.get("estimated"))
        if cap is None:
            cap = max(5 * -(-max(used[rid]) // 5), 5)
        elif est:
            # rooms.json 정원도 추정치면, 그 방을 실제로 쓰는 분반의 (반올림한) 인원보다 작지 않게 (11/27:
            # 반올림 때문에 원래 그 방을 쓰던 분반이 정원 초과가 되지 않게). 추정이 아닌 정원은 그대로 둔다
            cap = max(cap, max(used[rid]))
        b, no = rid.split(" ", 1)
        rooms.append(dict(id=rid, building=b, room_no=no, capacity=cap, is_lab=rid in LABS, estimated=est))

    # 희망 (가상): 실제 칸 = PREFER
    wishes = []
    for s in sections:
        if s["shape"] == "MANUAL":
            continue
        wishes.append(dict(section_id=s["section_id"], course_id=s["course_id"], section_no=s["section_no"],
                           professor=s["professor"], prefer=cells_of(s["blocks"]), block=[],
                           lab="MUST" if any(b["room"] in LABS for b in s["blocks"]) else "NONE",
                           single_day="MUST" if s["shape"] == "ONCE_LONG" else "NONE"))
    bld = defaultdict(Counter)
    for s in sections:
        if s["shape"] != "MANUAL" and s["professor"]:
            for b in s["blocks"]:
                bld[s["professor"]][b["room"].split(" ")[0]] += 1
    building_pref = {p: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for p, c in bld.items()}

    chapel = []
    for f in fixed:
        if f.get("kind") == "채플" and f.get("scope") == "AI대학":
            for y in f.get("years") or []:
                chapel.append(dict(year=str(y), day=f["day"], start=f["start"], end=f["end"]))

    profs = sorted({s["professor"] for s in sections if s["professor"]})
    return dict(sections=sections, courses=courses, rooms=rooms, wishes=wishes, building_pref=building_pref,
                chapel=chapel, professors=profs)


# ---------- DB 쓰기 ----------

def _haeyoon():
    for p in (REPO_ROOT / "db", REPO_ROOT / "solver"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import db as hdb             # noqa: E402 - 하윤 파일 (고치지 않음)
    import seed_time_slot        # noqa: E402
    return hdb, seed_time_slot


def create_db(con, plan: dict, year: int = 2026, semester: str = "2", deadline: str = "2026-12-31") -> dict:
    """스키마·칸·학기·차수 1·교수·조교·강의실·과목·분반·희망·희망 건물·채플. -> ids"""
    _, sts = _haeyoon()
    con.executescript((REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    grid = sts.seed(con)
    q = con.execute
    dept = {n: q("INSERT INTO department(name, college) VALUES (?,?)", (n, COLLEGE)).lastrowid
            for n in sorted(set(DEPARTMENTS.values()) | {c["department"] for c in plan["courses"]})}
    term = q("INSERT INTO term(year, semester, grid_id) VALUES (?,?,?)", (year, semester, grid)).lastrowid
    rnd = q("INSERT INTO round(term_id, round_no, deadline_at) VALUES (?,1,?)", (term, deadline)).lastrowid
    user = {p: q("INSERT INTO user(role, name, password_hash) VALUES ('PROF', ?, 'x')", (p,)).lastrowid
            for p in plan["professors"]}
    ta = q("INSERT INTO user(role, name, password_hash) VALUES ('TA', ?, 'x')", (TA_NAME,)).lastrowid
    bld, room_ids = {}, {}
    for r in plan["rooms"]:
        if r["building"] not in bld:
            bld[r["building"]] = q("INSERT INTO building(name) VALUES (?)", (r["building"],)).lastrowid
        room_ids[r["id"]] = q("INSERT INTO room(building_id, room_no, capacity, is_lab) VALUES (?,?,?,?)",
                              (bld[r["building"]], r["room_no"], r["capacity"], int(r["is_lab"]))).lastrowid
    for c in plan["courses"]:
        q("""INSERT INTO course(id, term_id, department_id, code, name, professor_id, category, target_year,
                                session_count, slots_per_session) VALUES (?,?,?,?,?,?,?,?,2,1)""",
          (c["course_id"], term, dept[c["department"]], c["code"], c["name"], user[c["professor"]],
           c["category"], c["target_year"]))
    for s in plan["sections"]:
        if s["shape"] != "MANUAL":
            q("INSERT INTO course_section(course_id, section_no, professor_id, enrollment) VALUES (?,?,?,?)",
              (s["course_id"], s["section_no"], user[s["professor"]], s["enrollment"] or None))
    slot = {(d, st): sid for sid, d, st in q("SELECT id, day, start_time FROM time_slot WHERE grid_id=?", (grid,))}
    for w in plan["wishes"]:
        rid = q("""INSERT INTO course_response(round_id, course_id, section_no, professor_id, lab_requirement,
                                               single_day_pref, submitted_at) VALUES (?,?,?,?,?,?,datetime('now'))""",
                (rnd, w["course_id"], w["section_no"], user[w["professor"]], w["lab"], w["single_day"])).lastrowid
        for kind in ("BLOCK", "PREFER"):
            for cell in w["block" if kind == "BLOCK" else "prefer"]:
                d, _, st = cell.partition("-")
                q("INSERT OR IGNORE INTO response_slot(response_id, slot_id, kind) VALUES (?,?,?)",
                  (rid, slot[(d, st)], kind))
    for p in sorted({w["professor"] for w in plan["wishes"]}):
        q("INSERT INTO round_invite(round_id, professor_id, status) VALUES (?,?, 'RESPONDED')", (rnd, user[p]))
    if plan.get("blank_prof"):   # 희망을 비운 교수: 희망 입력 요청만 보낸 상태 (아직 응답 없음)
        q("INSERT INTO round_invite(round_id, professor_id, status) VALUES (?,?, 'PENDING')",
          (rnd, user[plan["blank_prof"]["professor"]]))
    for p, b in plan["building_pref"].items():
        q("INSERT INTO professor_building_pref(professor_id, building_id) VALUES (?,?)", (user[p], bld[b]))
    for ch in plan["chapel"]:
        for (d, st), sid in slot.items():
            s0 = _mins(st)
            if d == ch["day"] and s0 < _mins(ch["end"]) and _mins(ch["start"]) < s0 + 75:
                q("INSERT OR IGNORE INTO chapel_slot(term_id, target_year, slot_id) VALUES (?,?,?)", (term, ch["year"], sid))
    con.commit()
    if plan.get("hire_years"):   # 가상 임용 연도 (하윤 db.set_hire_year, 조교는 넣지 않음)
        hdb, _ = _haeyoon()
        for p_, yr in plan["hire_years"].items():
            hdb.set_hire_year(con, user[p_], yr)
    return dict(term_id=term, round_id=rnd, ta_id=ta, users=user, rooms=room_ids, slots=slot)


DEMO_SEED = 20261125
DEMO_COUNTS = dict(mismatch=4, partial=1, no_option=1)   # 실제 엑셀에서 초안 OPEN 4~6·HOLD 1~2·NO_OPTION 1 이 되게 맞춘 값
ALL_CELLS = [f"{d}-{t}" for d in DAYS for t in STARTS]


def apply_demo(plan: dict, seed: int = DEMO_SEED, counts: Optional[dict] = None) -> Dict[str, str]:
    """시연용 겹침: 가상 희망만 바꾼다. -> {서버 분반 id: 바꾼 내용}. 같은 seed 면 늘 같은 결과."""
    import random
    counts = dict(DEMO_COUNTS, **(counts or {}))
    rng = random.Random(seed)
    wish = {w["section_id"]: w for w in plan["wishes"]}
    by_prof: Dict[str, List[str]] = defaultdict(list)
    for sid in sorted(wish):
        by_prof[wish[sid]["professor"]].append(sid)
    profs = sorted(p for p, v in by_prof.items() if len(v) >= 2)
    rng.shuffle(profs)
    used, changed = set(), {}

    def pair():
        """같은 교수의 아직 안 쓴 두 분반 (겹칠 분반, 막는 분반)."""
        for p in profs:
            free = [x for x in by_prof[p] if x not in used]
            if len(free) >= 2:
                a, b = rng.sample(free, 2)
                used.update((a, b))
                return a, b
        return None

    def hold_only(blocker: str) -> None:
        w = wish[blocker]
        w["block"] = [c for c in ALL_CELLS if c not in w["prefer"]]
        changed[blocker] = "막는 분반: 지금 칸 말고 모두 불가"

    for _ in range(counts["mismatch"]):
        got = pair()
        if not got:
            break
        a, b = got
        hold_only(b)
        wish[a]["prefer"] = list(wish[b]["prefer"])
        changed[a] = f"겹침: {b}의 칸만 희망"
    for _ in range(counts["partial"]):
        got = pair()
        if not got:
            break
        a, b = got
        hold_only(b)
        own = [c for c in wish[a]["prefer"] if c not in wish[b]["prefer"]]
        wish[a]["prefer"] = sorted(set(own[:1] + wish[b]["prefer"][:1]))
        wish[a]["single_day"] = "NONE"
        changed[a] = f"일부 겹침: 한 칸은 {b}의 칸"
    rest = [sid for sid in sorted(wish) if sid not in used]
    for sid in rng.sample(rest, min(counts["no_option"], len(rest))):
        wish[sid]["prefer"], wish[sid]["block"] = [], list(ALL_CELLS)
        used.add(sid)
        changed[sid] = "대안 없음: 모든 칸 불가"
    return changed


def pick_blank_prof(plan: dict, given: Optional[str] = None) -> str:
    """희망을 비워 둘 교수 (가명). given 이 있으면 그 교수(있는지 확인), 없으면 자동:
    같은 과목에서 분반을 둘 이상 맡고(분반 연강·교차 시연용), MANUAL 분반이 없고, --demo 가 바꾼 분반(겹침 상대 포함)에
    들어가지 않는 교수 중 가명 순 첫째."""
    profs = {s["professor"] for s in plan["sections"] if s["professor"]}
    if given:
        if given not in profs:
            raise ValueError(f"그런 교수 가명이 없습니다: {given}")
        return given
    changed = set(plan.get("demo_changed", {}))
    cands = []
    for p in sorted(profs):
        mine = [s for s in plan["sections"] if s["professor"] == p]
        if any(s["shape"] == "MANUAL" for s in mine) or any(s["section_id"] in changed for s in mine):
            continue
        per_course = Counter(s["course_id"] for s in mine)
        if per_course and max(per_course.values()) >= 2:
            cands.append(p)
    if not cands:
        raise ValueError("희망을 비워 둘 교수 후보가 없습니다 (같은 과목 분반 둘 이상·MANUAL 없음·--demo 분반 아님)")
    return cands[0]


def apply_blank_prof(plan: dict, prof: str) -> List[str]:
    """그 교수의 희망을 비운다: 분반 응답(칠한 칸·실습실·주 1회 연강) 없음, 희망 건물 없음, 분반 인원 NULL.
    과목·분반·담당 교수는 그대로. -> 비운 분반 id (과목 코드 순)."""
    secs = sorted((s for s in plan["sections"] if s["professor"] == prof and s["shape"] != "MANUAL"),
                  key=lambda s: s["code"])
    ids = {s["section_id"] for s in secs}
    plan["wishes"] = [w for w in plan["wishes"] if w["section_id"] not in ids]
    plan["building_pref"].pop(prof, None)
    for s in secs:
        s["enrollment"] = None
    return [s["section_id"] for s in secs]


WIDEN_SEED = 20261127
# 희망 넓히기 비율 (대략): 실제 칸만 30% · 앞뒤 칸 35% · 다른 요일 쌍 20% · 넓게 + 일부 불가 15%
WIDEN_SHARE = (("exact", 0.30), ("adjacent", 0.35), ("other_days", 0.20), ("wide_block", 0.15))
OTHER_PAIR = {("월", "수"): ("화", "목"), ("화", "목"): ("월", "수"), ("월", "목"): ("화", "금"), ("화", "금"): ("월", "목")}


def _cell(day: str, i: int) -> Optional[str]:
    return f"{day}-{STARTS[i]}" if 0 <= i < len(STARTS) else None


def _no_paint(sec: dict, chapel: List[dict]) -> set:
    """규칙상 안 되거나 피할 칸: 19:30(늦은 교시), 주 1회 연강이면 18:00 이후 시작, 그 학년 전공필수면 채플 칸."""
    out = {f"{d}-19:30" for d in DAYS}
    if sec["shape"] == "ONCE_LONG":
        out |= {f"{d}-18:00" for d in DAYS}
    if sec.get("category") == "전공필수" and sec.get("year") is not None:
        for ch in chapel:
            if ch["year"] == str(sec["year"]):
                for st in STARTS:
                    s0 = _mins(st)
                    if s0 < _mins(ch["end"]) and _mins(ch["start"]) < s0 + 75:
                        out.add(f"{ch['day']}-{st}")
    return out


def widen_wishes(plan: dict, seed: int = WIDEN_SEED, skip: Iterable[str] = ()) -> Dict[str, str]:
    """가상 희망 넓히기. -> {분반 id: wish_kind}. skip(--demo 분반, --blank-prof 분반)은 넓히지 않는다.
    실제 칸은 늘 희망으로 남고, 불가 칸은 실제 칸과 겹치지 않는다. 실습실·주 1회 연강·희망 건물은 그대로."""
    import random
    rng = random.Random(seed)
    sec_of = {x["section_id"]: x for x in plan["sections"]}
    skip = set(skip)
    kinds: Dict[str, str] = {}
    for w in sorted(plan["wishes"], key=lambda w: w["section_id"]):
        sid = w["section_id"]
        r = rng.random()          # 넓히지 않는 분반도 난수를 하나 써서, skip 이 바뀌어도 다른 분반 결과가 같게
        if sid in skip:
            continue
        sec = sec_of[sid]
        actual = cells_of(sec["blocks"])
        acc, kind = 0.0, WIDEN_SHARE[-1][0]
        for k, share in WIDEN_SHARE:
            acc += share
            if r < acc:
                kind = k
                break
        bad = _no_paint(sec, plan.get("chapel", [])) - set(actual)
        days = [b["day"] for b in sec["blocks"]]
        add = set()
        if kind in ("adjacent", "wide_block"):
            for b in sec["blocks"]:
                i = STARTS.index(b["start"])
                add |= {c for c in (_cell(b["day"], i - 1), _cell(b["day"], i + b["slots"])) if c}
        if kind == "other_days":
            key = tuple(sorted(days, key=DAYS.index))
            other = OTHER_PAIR.get(key) or tuple(DAYS[(DAYS.index(d) + 1) % 5] for d in key)
            if set(other) & set(days):
                other = tuple(DAYS[(DAYS.index(d) + 2) % 5] for d in key)
            for b, d in zip(sorted(sec["blocks"], key=lambda b: DAYS.index(b["day"])), other):
                i = STARTS.index(b["start"])
                add |= {c for c in (_cell(d, i + j) for j in range(b["slots"])) if c}
        w["prefer"] = sorted(set(actual) | (add - bad))
        if kind == "wide_block":
            free_days = [d for d in DAYS if d not in days]
            off = rng.choice(free_days) if free_days else None
            w["block"] = sorted(c for c in ALL_CELLS if off and c.startswith(off + "-") and c not in actual)
        kinds[sid] = kind
    return kinds


HIRE_SEED = "ssuroom-hire-20261128"
HIRE_RANGE = (1995, 2024)


def hire_year_of(alias: str, seed: str = HIRE_SEED) -> int:
    """가명 → 가상 임용 연도 (HIRE_RANGE 안). 가명과 시드만으로 정해서 교수를 어떤 순서로 처리해도 같은 값."""
    import hashlib
    lo, hi = HIRE_RANGE
    h = int(hashlib.sha256(f"{seed}:{alias}".encode("utf-8")).hexdigest(), 16)
    return lo + h % (hi - lo + 1)


def section_map(plan: dict, ids: dict, db_path: str) -> dict:
    """서버 분반 id → 분반 정보. DB에 넣은 분반은 course_id·section_no, MANUAL은 "manual": true 와 칸."""
    secs = {}
    for s in plan["sections"]:
        e = {k: s[k] for k in ("code", "name", "division", "category_orig", "category", "professor", "enrollment",
                               "enrollment_orig", "year", "shape")}
        if s["shape"] == "MANUAL":
            e.update(manual=True, manual_reason=s["manual_reason"], blocks=s["blocks"])
        else:
            if s["section_id"] in plan.get("demo_changed", {}):
                e["demo_changed"] = plan["demo_changed"][s["section_id"]]
            # 희망 넓히기 종류 (exact|adjacent|other_days|wide_block). --demo·--blank-prof 분반은 넓히지 않아 null
            e["wish_kind"] = plan.get("wish_kinds", {}).get(s["section_id"])
            e.update(manual=False, course_id=s["course_id"], section_no=s["section_no"],
                     orig_section_no=s["orig_section_no"])
        secs[s["section_id"]] = e
    return {
        "db": db_path, "term_id": ids["term_id"], "round_id": ids["round_id"], "ta_id": ids["ta_id"],
        "professors": {p: uid for p, uid in ids["users"].items()},
        "sections": secs,
        "rooms": {r["id"]: dict(room_id=ids["rooms"][r["id"]], capacity=r["capacity"], is_lab=r["is_lab"],
                                estimated=r["estimated"]) for r in plan["rooms"]},
        "note": "가명 데이터. 희망은 실제 강의 칸으로 만든 가상 값. 교양필수 고정 시간은 넣지 않음. "
                "수강 인원은 5명 단위로 반올림(원래 값 enrollment_orig).",
        "blank_prof": plan.get("blank_prof"),    # 희망을 비워 둔 교수 {professor, sections} 또는 None
        "hire_years": plan.get("hire_years") or {},   # 가상 임용 연도 {가명: 연도} (--no-hire-year 면 빈 값)
    }


def section_pairs(mapping: dict) -> Dict[Tuple[int, int], str]:
    """대응표 → 어댑터 SectionMap 입력 {(과목 id, 분반 번호): 서버 분반 id}. MANUAL은 뺀다."""
    return {(v["course_id"], v["section_no"]): sid for sid, v in mapping["sections"].items() if not v.get("manual")}


def real_name_hits(names: List[str], con=None, texts: List[str] = ()) -> int:
    """실명이 DB(모든 글 칸)나 글 목록에 몇 번 나오는지. 이름 자체는 돌려주지 않는다."""
    names = [n for n in names if n]
    blobs = list(texts)
    if con is not None:
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
            for row in con.execute(f"SELECT {','.join(cols)} FROM {t}"):
                blobs += [str(v) for v in row if isinstance(v, str)]
    return sum(1 for b in blobs for n in names if n in b)


def counts(con, plan: dict) -> List[Tuple[str, int]]:
    one = lambda sql: con.execute(sql).fetchone()[0]   # noqa: E731
    shapes = Counter(s["shape"] for s in plan["sections"])
    return [
        ("엑셀 행(분반)", len(plan["sections"])),
        ("과목", one("SELECT COUNT(*) FROM course")),
        ("분반(DB)", one("SELECT COUNT(*) FROM course_section")),
        ("  주 2회", shapes["TWICE"]),
        ("  주 1회 연강", shapes["ONCE_LONG"]),
        ("MANUAL (DB에 안 넣음)", shapes["MANUAL"]),
        ("교수(가명)", one("SELECT COUNT(*) FROM user WHERE role='PROF'")),
        ("강의실", one("SELECT COUNT(*) FROM room")),
        ("  실습실", one("SELECT COUNT(*) FROM room WHERE is_lab=1")),
        ("  정원 추정", sum(1 for r in plan["rooms"] if r["estimated"])),
        ("희망 응답(분반마다)", one("SELECT COUNT(*) FROM course_response")),
        ("희망 건물", one("SELECT COUNT(*) FROM professor_building_pref")),
        ("채플 칸", one("SELECT COUNT(*) FROM chapel_slot")),
    ]


def seed(xlsx: Path, db_path: Path, map_path: Path, alias_path: Path, rooms_json: Path, fixed_json: Path,
         year: int = 2026, semester: str = "2", demo: bool = False, blank_prof: Optional[str] = None,
         narrow: bool = False, hire_year: bool = True) -> dict:
    """blank_prof: None = 끔, "" = 자동으로 고름, 가명 = 그 교수. --demo 다음에 적용한다.
    narrow: True 면 희망을 넓히지 않는다(실제 칸만, 예전과 같음). 넓히기는 --demo·--blank-prof 다음."""
    rows = read_excel(xlsx)
    old = json.loads(alias_path.read_text(encoding="utf-8")) if alias_path.exists() else {}
    alias = make_aliases(rows, old)
    rooms_info = {r["id"]: r for r in json.loads(rooms_json.read_text(encoding="utf-8"))} if rooms_json.exists() else {}
    fixed = json.loads(fixed_json.read_text(encoding="utf-8")) if fixed_json.exists() else []
    plan = build_plan(rows, alias, rooms_info, fixed)
    plan["demo_changed"] = apply_demo(plan) if demo else {}
    plan["blank_prof"] = None
    if blank_prof is not None:
        who = pick_blank_prof(plan, blank_prof or None)
        plan["blank_prof"] = dict(professor=who, sections=apply_blank_prof(plan, who))
    skip = set(plan["demo_changed"]) | set((plan["blank_prof"] or {}).get("sections", []))
    plan["wish_kinds"] = ({w["section_id"]: "exact" for w in plan["wishes"] if w["section_id"] not in skip}
                          if narrow else widen_wishes(plan, skip=skip))
    plan["hire_years"] = {p_: hire_year_of(p_) for p_ in plan["professors"]} if hire_year else {}
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    ids = create_db(con, plan, year, semester)
    mapping = section_map(plan, ids, str(db_path))
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.write_text(json.dumps(alias, ensure_ascii=False, indent=2), encoding="utf-8")
    text = json.dumps(mapping, ensure_ascii=False, indent=2)
    map_path.write_text(text, encoding="utf-8")
    table = counts(con, plan)
    out_text = "\n".join(f"{k} {v}" for k, v in table)
    names = {part.strip() for n in alias for part in re.split(r"[\n,]", n) if part.strip()}
    hits = real_name_hits(sorted(names), con, [text, out_text])
    con.close()
    manual = Counter(s["manual_reason"] for s in plan["sections"] if s["shape"] == "MANUAL")
    return dict(counts=table, real_name_hits=hits, manual_reasons=manual, term_id=ids["term_id"],
                demo_changed=plan["demo_changed"], blank_prof=plan["blank_prof"],
                wish_kinds=Counter(plan["wish_kinds"].values()), hire_years=plan["hire_years"],
                rounded=sum(1 for s in plan["sections"] if s["enrollment_orig"] is not None
                            and s["enrollment_orig"] != round5(s["enrollment_orig"])),
                over_capacity=over_capacity(plan),
                round_id=ids["round_id"])


def over_capacity(plan: dict) -> List[str]:
    """반올림한 인원이 지금 쓰는 강의실 정원보다 많은 분반 (엑셀 강의실 기준, MANUAL 제외)."""
    cap = {r["id"]: r["capacity"] for r in plan["rooms"]}
    return sorted(s["section_id"] for s in plan["sections"] if s["shape"] != "MANUAL" and s["enrollment"]
                  and any(b["room"] and cap.get(b["room"]) and s["enrollment"] > cap[b["room"]] for b in s["blocks"]))


def main() -> None:
    ap = argparse.ArgumentParser(description="강의정보 엑셀을 하윤 DB에 넣고 분반 대응표를 만든다 (가명)")
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--db", type=Path, default=REPO_ROOT / "ssuroom.db")
    ap.add_argument("--map", type=Path, default=PRIVATE / "real" / "section_map.json")
    ap.add_argument("--alias", type=Path, default=PRIVATE / "alias_map.json")
    ap.add_argument("--rooms", type=Path, default=PRIVATE / "real" / "rooms.json")
    ap.add_argument("--fixed", type=Path, default=PRIVATE / "real" / "fixed_blocks.json")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--semester", default="2")
    ap.add_argument("--demo", action="store_true", help="시연용: 일부 분반의 가상 희망을 서로 겹치게 (기본 꺼짐)")
    ap.add_argument("--narrow", action="store_true", help="희망을 넓히지 않고 실제 수업 칸만 (예전 시드)")
    ap.add_argument("--no-hire-year", action="store_true", help="가상 임용 연도를 넣지 않음 (예전 시드)")
    ap.add_argument("--blank-prof", nargs="?", const="", default=None, metavar="가명",
                    help="희망 수집 시연용: 교수 한 명의 희망을 비워 둠. 값 없이 주면 자동 선택 (기본 꺼짐)")
    a = ap.parse_args()
    out = seed(a.xlsx, a.db, a.map, a.alias, a.rooms, a.fixed, a.year, a.semester, demo=a.demo,
               blank_prof=a.blank_prof, narrow=a.narrow, hire_year=not a.no_hire_year)
    print(f"DB: {a.db}  (term {out['term_id']}, round {out['round_id']})")
    for k, v in out["counts"]:
        print(f"{k:<24}{v}")
    print("MANUAL 이유:", dict(out["manual_reasons"]))
    if a.demo:
        print(f"시연용 겹침(--demo): 가상 희망을 바꾼 분반 {len(out['demo_changed'])}개 (희망은 실제 값이 아닌 가상)")
        for sid, what in out["demo_changed"].items():
            print(f"  {sid}: {what}")
    print(f"수강 인원 5명 단위 반올림으로 바뀐 분반: {out['rounded']}개 (원래 값은 대응표 enrollment_orig)")
    if out["over_capacity"]:
        print(f"  주의: 반올림한 인원이 엑셀 강의실 정원보다 많은 분반 {len(out['over_capacity'])}개: {out['over_capacity']}")
    hy = out["hire_years"]
    print(f"임용 연도 넣음: {len(hy)}명 (가상, {min(hy.values())}~{max(hy.values())})" if hy
          else "임용 연도 넣음: 0명 (--no-hire-year)")
    print("희망 넓히기" + (" (--narrow: 실제 칸만)" if a.narrow else "") + ": "
          + ", ".join(f"{k} {out['wish_kinds'].get(k, 0)}" for k, _ in WIDEN_SHARE)
          + " (--demo·--blank-prof 분반은 넓히지 않음)")
    if out["blank_prof"]:
        bp = out["blank_prof"]
        print(f"희망 비운 교수: {bp['professor']} ({', '.join(bp['sections'])})")
    print(f"실명 검색(DB·대응표·출력): {out['real_name_hits']}건")
    print("교양필수 고정 시간은 넣지 않음. 전 학기(2026-1)는 엔진이 읽지 않아(전년도 같은 학기만) 넣지 않음.")


if __name__ == "__main__":
    main()
