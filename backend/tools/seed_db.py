"""실제(가명) 데이터 data/private/<DATA_SET>/*.json → 문하윤 DB(db/schema.sql) 시드 + 분반 대응표 (백엔드 ③, 김대원).

사용 (저장소 맨 위에서):
    python backend/tools/seed_db.py                 # → ssuroom.db, data/private/real/section_map.json
    python backend/tools/seed_db.py --db 다른.db --year 2026 --semester 2

하는 일
- 새 DB 파일(이미 있으면 지움) → schema.sql → db/seed_time_slot.py로 칸(월~금 × 8교시) → department, term, round 1(희망 수집)
- user: 교수 가명마다 PROF 한 줄. building/room: rooms.json 그대로(추정치 표시는 대응표에 남김. DB에 칸이 없음)
- course: 과목 코드(끝 두 자리 뺀 것)마다 한 줄. 카테고리 "전필-…" → "전공필수", "교필…" → "교양필수"(솔버가 아는 이름).
  원래 값은 대응표에 남긴다. 학과는 카테고리 뒤쪽(AI소프트웨어/정보보호)
- course_section: 데이터에 있는 분반만. 솔버는 분반을 1..n으로 세므로 원래 번호 순으로 1부터 다시 매긴다.
  (course_id, 새 번호) ↔ 원래 분반 번호·서버 분반 id는 대응표에. 교수별 SECTION_COUNT도 넣는다
- 희망: (과목, 교수)마다 course_response 1개 (팀 결정 11/23: 분반 번호를 DB에 더하지 않는다).
  같은 교수가 여러 분반을 맡아 희망이 다르면 합친다: BLOCK = 합집합, PREFER = 합집합 − BLOCK.
  실습실 = 한 분반이라도 필요하면 1. 주 1회 연강 = 지금 연강(2칸 한 번)인 분반은 MUST, 주 2회는 NONE, 섞이면 PREFER.
  '꼭'(must)은 prefer_only로 옮기지 않는다('꼭'은 하드 규칙이 아니라 가장 큰 가중치. 실제 데이터에는 없음).
  기타 요청(note)은 other_request(PENDING)로. 건물 선호는 교수별 professor_building_pref(많이 고른 건물이 1순위)
- MANUAL 분반(주 2칸이 아니거나 토요일·교시 밖)은 DB에 넣지 않고 대응표에 "MANUAL"로 표시
- 채플·교양필수 고정 시간: 하윤 DB에 표가 없어 넣지 않는다 (fixed_blocks.json 그대로 둠)

대응표(section_map.json)는 서버·어댑터가 읽는다. data/private 아래라 커밋하지 않는다.
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.contracts import DAYS, STARTS, Timetable, parse, section_shape  # noqa: E402

ALIAS = re.compile(r"^교수\d+$")
CATEGORY = (("전필", "전공필수"), ("교필", "교양필수"))   # 솔버 REQUIRED_CATEGORIES와 같은 이름
DEPARTMENTS = {"AI소프트웨어": "AI소프트웨어학부", "정보보호": "정보보호학과"}
COLLEGE = "AI융합대학"   # 가정한 이름 (단과대 이름은 데이터에 없음)


# ---------- 순수 함수 (DB 없이 시험할 수 있게) ----------

def db_category(cat: Optional[str]) -> Optional[str]:
    """'전필-AI소프트웨어' → '전공필수', '교필…' → '교양필수'. 나머지는 원래 값."""
    if not cat:
        return cat
    for prefix, name in CATEGORY:
        if cat.startswith(prefix):
            return name
    return cat


def department_of(cat: Optional[str]) -> str:
    tail = (cat or "").partition("-")[2]
    return DEPARTMENTS.get(tail, tail or DEPARTMENTS["AI소프트웨어"])


def _grid_cell(key: str) -> bool:
    day, _, start = key.partition("-")
    return day in DAYS and start in STARTS


def merge_wishes(wishes: List[dict], shapes: List[str]) -> dict:
    """한 교수가 같은 과목에서 맡은 분반들의 희망 → 응답 하나."""
    block = {k for w in wishes for k, v in w.get("cells", {}).items() if v == "BLOCK" and _grid_cell(k)}
    prefer = {k for w in wishes for k, v in w.get("cells", {}).items() if v == "PREFER" and _grid_cell(k)} - block
    kinds = set(shapes)
    single = "MUST" if kinds == {"ONCE_LONG"} else "NONE" if kinds == {"TWICE"} else "PREFER"
    notes = list(dict.fromkeys(w["note"].strip() for w in wishes if (w.get("note") or "").strip()))
    return {
        "block": sorted(block), "prefer": sorted(prefer),
        "lab": int(any(w.get("lab") == "MUST" for w in wishes)),
        "single_day": single,
        "buildings": [w["building"] for w in wishes if w.get("building")],
        "note": "\n".join(notes),
        "differ": len({json.dumps(w.get("cells", {}), sort_keys=True) for w in wishes}) > 1,
        "mixed_shape": len(kinds) > 1,
    }


def build_plan(sections: List[dict], wishes: List[dict], timetable: dict) -> dict:
    """분반·희망·초안 → DB에 넣을 계획. 과목 id·분반 번호를 여기서 정한다(과목 코드 순, 원래 분반 번호 순)."""
    tt = parse(Timetable, timetable)
    blocks = {a.section_id: a.blocks for a in tt.assignments}
    wish = {w["section_id"]: w for w in wishes}

    shape = {s["id"]: section_shape(s["weekly_blocks"], blocks.get(s["id"], [])) for s in sections}
    manual = sorted(s["id"] for s in sections if shape[s["id"]] == "MANUAL")
    by_course: Dict[str, List[dict]] = defaultdict(list)
    for s in sections:
        if shape[s["id"]] != "MANUAL":
            by_course[s["code"][:-2]].append(s)

    courses, section_rows = [], []
    for cid, base in enumerate(sorted(by_course), start=1):
        secs = sorted(by_course[base], key=lambda s: (s["code"][-2:], s["id"]))
        years = Counter(s["year"] for s in secs if s["year"] is not None)
        cat = secs[0]["category"]
        courses.append({
            "course_id": cid, "code": base, "name": secs[0]["name"],
            "category": db_category(cat), "category_orig": cat, "department": department_of(cat),
            "target_year": str(years.most_common(1)[0][0]) if years else None,
            "expected_enrollment": sum(s["enrollment"] or 0 for s in secs) or None,
            "professor": secs[0]["professor"],
        })
        for no, s in enumerate(secs, start=1):
            section_rows.append({
                "section_id": s["id"], "course_id": cid, "section_no": no,
                "orig_section_no": s["code"][-2:], "division": s["division"], "code": s["code"],
                "name": s["name"], "professor": s["professor"], "shape": shape[s["id"]],
                "enrollment": s["enrollment"], "year": s["year"],
                "category_orig": s["category"], "category": db_category(s["category"]),
            })

    responses = []
    groups: Dict[Tuple[int, str], List[dict]] = defaultdict(list)
    for r in section_rows:
        groups[(r["course_id"], r["professor"])].append(r)
    for (cid, prof), rows in sorted(groups.items()):
        ws = [wish.get(r["section_id"], {}) for r in rows]
        m = merge_wishes(ws, [r["shape"] for r in rows])
        responses.append(dict(m, course_id=cid, professor=prof, n_sections=len(rows),
                              section_ids=[r["section_id"] for r in rows]))

    profs = sorted({s["professor"] for s in sections if s["professor"]} |
                   {r["professor"] for r in responses})
    return {"courses": courses, "sections": section_rows, "responses": responses,
            "manual": manual, "professors": profs}


def building_ranks(responses: List[dict]) -> Dict[str, List[str]]:
    """교수별 건물 선호 순위. 그 교수의 희망에서 많이 고른 건물이 1순위."""
    count: Dict[str, Counter] = defaultdict(Counter)
    for r in responses:
        for b in r["buildings"]:
            count[r["professor"]][b] += 1
    return {p: [b for b, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))] for p, c in count.items()}


def section_map(plan: dict, rooms: List[dict], db: str, term_id: int, round_id: int,
                room_ids: Dict[str, int]) -> dict:
    """서버 분반 id ↔ (course_id, 새 분반 번호). MANUAL은 "MANUAL"."""
    m = {r["section_id"]: {k: r[k] for k in ("course_id", "section_no", "orig_section_no", "division",
                                             "category_orig", "category")}
         for r in plan["sections"]}
    for sid in plan["manual"]:
        m[sid] = "MANUAL"
    return {
        "db": db, "term_id": term_id, "round_id": round_id,
        "sections": m,
        "rooms": {r["id"]: {"room_id": room_ids[r["id"]], "estimated": bool(r.get("estimated"))} for r in rooms},
        "note": "가명 데이터. 채플·교양필수 고정 시간은 DB에 표가 없어 넣지 않음(fixed_blocks.json).",
    }


def section_pairs(mapping: dict) -> Dict[Tuple[int, int], str]:
    """대응표 → 어댑터 SectionMap 입력 {(과목 id, 분반 번호): 서버 분반 id}. MANUAL은 뺀다."""
    return {(v["course_id"], v["section_no"]): sid for sid, v in mapping["sections"].items() if v != "MANUAL"}


# ---------- DB 쓰기 ----------

def load_haeyoon_db():
    sys.path.insert(0, str(REPO_ROOT / "db"))
    import seed_time_slot  # noqa: E402 - 하윤 파일 (고치지 않음)
    return seed_time_slot


def create_db(con, plan: dict, rooms: List[dict], year: int = 2026, semester: str = "2",
              deadline: str = "2026-12-31") -> Tuple[int, int, Dict[str, int]]:
    """스키마·칸부터 응답까지 넣는다. -> (term_id, round_id, 서버 강의실 id → room.id)"""
    con.executescript((REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    grid = load_haeyoon_db().seed(con)
    q = con.execute

    dept = {}
    for name in sorted({c["department"] for c in plan["courses"]} | set(DEPARTMENTS.values())):
        dept[name] = q("INSERT INTO department(name, college) VALUES (?,?)", (name, COLLEGE)).lastrowid
    term = q("INSERT INTO term(year, semester, grid_id) VALUES (?,?,?)", (year, semester, grid)).lastrowid
    rnd = q("INSERT INTO round(term_id, round_no, deadline_at) VALUES (?,?,?)", (term, 1, deadline)).lastrowid

    user = {p: q("INSERT INTO user(role, name, password_hash) VALUES ('PROF', ?, 'x')", (p,)).lastrowid
            for p in plan["professors"]}

    bld = {}
    room_ids = {}
    for r in rooms:
        if r["building"] not in bld:
            bld[r["building"]] = q("INSERT INTO building(name) VALUES (?)", (r["building"],)).lastrowid
        room_ids[r["id"]] = q("INSERT INTO room(building_id, room_no, capacity, is_lab) VALUES (?,?,?,?)",
                              (bld[r["building"]], r["room_no"], r.get("capacity"), int(bool(r.get("is_lab"))))).lastrowid

    for c in plan["courses"]:
        q("""INSERT INTO course(id, term_id, department_id, code, name, professor_id, category, target_year,
                                expected_enrollment, session_count, slots_per_session)
             VALUES (?,?,?,?,?,?,?,?,?,2,1)""",
          (c["course_id"], term, dept[c["department"]], c["code"], c["name"], user[c["professor"]],
           c["category"], c["target_year"], c["expected_enrollment"]))
    for s in plan["sections"]:
        q("INSERT INTO course_section(course_id, section_no, professor_id) VALUES (?,?,?)",
          (s["course_id"], s["section_no"], user[s["professor"]]))

    slot = {(d, st): sid for sid, d, st in q("SELECT id, day, start_time FROM time_slot WHERE grid_id=?", (grid,))}
    invited = set()
    for r in plan["responses"]:
        pid = user[r["professor"]]
        rid = q("""INSERT INTO course_response(round_id, course_id, professor_id, lab_requirement, single_day_pref,
                                               prefer_only, submitted_at) VALUES (?,?,?,?,?,0,datetime('now'))""",
                (rnd, r["course_id"], pid, r["lab"], r["single_day"])).lastrowid
        for kind in ("BLOCK", "PREFER"):
            for cell in r[kind.lower()]:
                d, _, st = cell.partition("-")
                q("INSERT INTO response_slot(response_id, slot_id, kind) VALUES (?,?,?)", (rid, slot[(d, st)], kind))
        q("""INSERT INTO request_item(response_id, type, value_int, source) VALUES (?, 'SECTION_COUNT', ?, 'FORM')""",
          (rid, r["n_sections"]))
        if r["note"]:
            q("INSERT INTO other_request(response_id, body) VALUES (?,?)", (rid, r["note"]))
        if pid not in invited:
            q("INSERT INTO round_invite(round_id, professor_id, status) VALUES (?,?, 'RESPONDED')", (rnd, pid))
            invited.add(pid)
    for p, blds in building_ranks(plan["responses"]).items():
        for rank, b in enumerate(blds, start=1):
            if b in bld:
                q("INSERT INTO professor_building_pref(professor_id, building_id, rank) VALUES (?,?,?)",
                  (user[p], bld[b], rank))
    con.commit()
    return term, rnd, room_ids


def real_name_hits(con) -> List[str]:
    """교수 이름이 가명(교수NN)이 아닌 것, 기타 요청에 'OOO 교수' 꼴 이름이 있는 것."""
    bad = [n for (n,) in con.execute("SELECT name FROM user") if not ALIAS.match(n)]
    for (body,) in con.execute("SELECT body FROM other_request"):
        bad += [m for m in re.findall(r"[가-힣]{2,4}\s*교수", body) if not ALIAS.match(m.replace(" ", ""))]
    return bad


def counts(con, plan: dict) -> List[Tuple[str, int]]:
    one = lambda sql: con.execute(sql).fetchone()[0]   # noqa: E731
    return [
        ("과목", one("SELECT COUNT(*) FROM course")),
        ("분반", one("SELECT COUNT(*) FROM course_section")),
        ("교수", one("SELECT COUNT(*) FROM user WHERE role='PROF'")),
        ("강의실", one("SELECT COUNT(*) FROM room")),
        ("응답", one("SELECT COUNT(*) FROM course_response")),
        ("합친 쌍(분반 2개 이상)", sum(1 for r in plan["responses"] if r["n_sections"] > 1)),
        ("  그중 희망이 달랐던 쌍", sum(1 for r in plan["responses"] if r["differ"])),
        ("  그중 연강·주 2회가 섞여 PREFER", sum(1 for r in plan["responses"] if r["mixed_shape"])),
        ("기타 요청", one("SELECT COUNT(*) FROM other_request")),
        ("MANUAL (DB에 안 넣음)", len(plan["manual"])),
    ]


def seed(data_dir: Path, db_path: Path, map_path: Path, year: int = 2026, semester: str = "2") -> dict:
    load = lambda n: json.loads((data_dir / n).read_text(encoding="utf-8"))   # noqa: E731
    sections, rooms = load("sections.json"), load("rooms.json")
    plan = build_plan(sections, load("wishes.json")["wishes"], load("timetable.json"))
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    term, rnd, room_ids = create_db(con, plan, rooms, year, semester)
    mapping = section_map(plan, rooms, str(db_path), term, rnd, room_ids)
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    out = {"counts": counts(con, plan), "real_names": real_name_hits(con), "term_id": term, "round_id": rnd,
           "estimated_rooms": sum(1 for r in rooms if r.get("estimated"))}
    con.close()
    return out


def main() -> None:
    import os
    ap = argparse.ArgumentParser(description="가명 데이터를 하윤 DB에 넣고 분반 대응표를 만든다")
    data = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
    ap.add_argument("--data", type=Path, default=data)
    ap.add_argument("--db", type=Path, default=REPO_ROOT / "ssuroom.db")
    ap.add_argument("--map", type=Path, default=None, help="기본: <data>/section_map.json")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--semester", default="2")
    a = ap.parse_args()
    out = seed(a.data, a.db, a.map or a.data / "section_map.json", a.year, a.semester)
    print(f"DB: {a.db}  (term {out['term_id']}, round {out['round_id']})")
    print(f"{'항목':<28}개수")
    for k, v in out["counts"]:
        print(f"{k:<28}{v}")
    print(f"강의실 중 정원·실습실이 추정치: {out['estimated_rooms']}")
    print(f"실명 의심: {len(out['real_names'])}건 {out['real_names'] or ''}")
    print("채플·교양필수 고정 시간: 하윤 DB에 표가 없어 넣지 않음 (fixed_blocks.json 그대로)")


if __name__ == "__main__":
    main()
