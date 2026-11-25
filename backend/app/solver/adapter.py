"""문하윤 솔버(solver/solver_core.py)와 DB(db/db.py)를 서버 모양으로 잇는 어댑터 (백엔드 ③, 김대원).

- 하윤 코드는 복사하지 않고 sys.path로 불러온다. 하윤 파일은 고치지 않는다.
- SolverAdapter가 DB 연결, term_id, round_id, 지금 시간표 id, (과목 id, 분반 번호) ↔ 서버 분반 id 대응표를 들고
  하윤 함수(solve, make_alternatives, save_proposal, finalize, load_assignment)를 부른다.
- 아래 모듈 함수(make_draft, make_alternatives, reassign)는 engine.py가 쓰는 서버 모양이다.
  engine.py는 환경변수 SSUROOM_ENGINE=solver일 때만 이 패키지를 본다. 기본은 가짜(stubs.py).
  check_rules·what_if는 솔버에 없어서 여기 두지 않는다 (engine이 함수마다 가짜를 쓴다).
- 모듈 함수를 쓰기 전에 configure(SolverAdapter(...))로 어댑터를 정한다. 정하지 않았으면 처음 쓸 때
  시드 스크립트(backend/tools/seed_db.py)가 만든 DB와 분반 대응표(section_map.json)를 읽어 스스로 정한다
  (from_files. 경로는 환경변수 SSUROOM_DB, SSUROOM_SECTION_MAP 또는 기본값).
"""

import inspect
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

from ..contracts import (
    DAYS, Alternative, Assignment, Block, Conditions, Meeting, Room, Section, Timetable, Wish, conditions_json, dump,
    parse, set_place,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
KEYS = ("A", "B", "C")
DRAFT_TIME_LIMIT = 30        # 초안 풀이 시간 한도(초). 하윤 문서는 60~90초 권장 — 시연 전에는 미리 풀어 둔다
ALT_TIME_LIMIT = 15          # 대안 한 개 풀이 시간 한도(초)
SectionKey = Tuple[int, int]  # (과목 id, 분반 번호)


def load_haeyoon():
    """하윤의 db.py, solver_core.py를 불러온다 (저장소 맨 위의 db/, solver/)."""
    for sub in ("solver", "db"):
        p = str(REPO_ROOT / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    import db as hdb                 # noqa: E402  (db/db.py)
    import solver_core as sc         # noqa: E402  (solver/solver_core.py)
    if not hasattr(hdb, "connect"):
        raise ImportError(f"db 모듈이 하윤 db/db.py가 아님: {getattr(hdb, '__file__', hdb)}")
    return hdb, sc


def _call(fn, *args, **kwargs):
    """함수에 없는 키워드 인자는 빼고 부른다 (하윤이 나중에 wish_round_id 같은 인자를 더할 수 있다)."""
    params = inspect.signature(fn).parameters
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return fn(*args, **kwargs)


# ---------- 칸·강의실 번호 ↔ 서버 모양 ----------

class SlotIndex:
    """time_slot id ↔ (요일, 시작). 한 학기의 시간 격자."""

    def __init__(self, con, term_id: int):
        rows = con.execute("""SELECT ts.id, ts.day, ts.period_no, ts.start_time, ts.end_time FROM time_slot ts
                              JOIN term t ON t.grid_id = ts.grid_id WHERE t.id = ?
                              ORDER BY ts.day, ts.period_no""", (term_id,)).fetchall()
        self.info: Dict[int, Tuple[str, int, str, str]] = {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}
        self.by_day: Dict[str, List[int]] = {}
        for sid, (day, _p, _s, _e) in sorted(self.info.items(), key=lambda kv: (kv[1][0], kv[1][1])):
            self.by_day.setdefault(day, []).append(sid)
        self.id_of: Dict[Tuple[str, str], int] = {(d, s): sid for sid, (d, _p, s, _e) in self.info.items()}

    def covered(self, start_id: int, k: int) -> List[int]:
        """시작 칸부터 같은 요일로 이어진 k칸."""
        day = self.info[start_id][0]
        ids = self.by_day[day]
        i = ids.index(start_id)
        return ids[i:i + k]

    def block(self, start_id: int, k: int) -> Block:
        day, _p, start, _e = self.info[start_id]
        return Block(day=day, start=start, slots=k)

    def end(self, start_id: int, k: int) -> str:
        return self.info[self.covered(start_id, k)[-1]][3]


class RoomIndex:
    """room id ↔ 서버 강의실 이름 "건물 호수"."""

    def __init__(self, con):
        rows = con.execute("""SELECT r.id, b.name, r.room_no FROM room r JOIN building b ON b.id = r.building_id""")
        self.name_of: Dict[int, str] = {rid: f"{b} {no}" for rid, b, no in rows}
        self.id_of: Dict[str, int] = {v: k for k, v in self.name_of.items()}


class SectionMap:
    """(과목 id, 분반 번호) ↔ 서버 분반 id. 대응표는 시드 스크립트가 만든다."""

    def __init__(self, pairs: Dict[SectionKey, str]):
        self.sid_of: Dict[SectionKey, str] = dict(pairs)
        self.key_of: Dict[str, SectionKey] = {v: k for k, v in self.sid_of.items()}
        if len(self.key_of) != len(self.sid_of):
            raise ValueError("분반 대응표에 같은 서버 분반 id가 두 번 나옴")

    def key(self, sid: str) -> SectionKey:
        if sid not in self.key_of:
            raise KeyError(f"DB에 대응하는 분반이 없음: {sid}")
        return self.key_of[sid]


# ---------- 변환 ----------

def assignments_from_db(start: Dict[Tuple[int, int, int], Tuple[int, int]], ks: Dict[Tuple[int, int, int], int],
                        slots: SlotIndex, rooms: RoomIndex, sections: SectionMap) -> Dict[str, Assignment]:
    """솔버 배정 {(과목, 분반, 회차): (시작 칸, 강의실)} + {키: 칸 수} → 서버 분반 id별 Assignment.
    회차마다 강의실은 Block.room에 그대로 넣는다 (Assignment.room = 첫 회차(요일 순)의 강의실, 대표 강의실).
    대응표에 없는 분반은 건너뛴다."""
    per: Dict[str, List[Tuple[Block, str]]] = {}
    for (cid, sec, _ss), (sid_slot, room_id) in start.items():
        sid = sections.sid_of.get((cid, sec))
        if sid is None:
            continue
        b = slots.block(sid_slot, ks[(cid, sec, _ss)])
        per.setdefault(sid, []).append(b.model_copy(update={"room": rooms.name_of[room_id]}))
    out = {}
    for sid, blocks in per.items():
        blocks.sort(key=lambda b: (DAYS.index(b.day), b.start))
        out[sid] = Assignment(section_id=sid, blocks=blocks, room=blocks[0].room, status="DONE")
    return out


def option_to_alternative(key: str, option: dict, course_id: int, slots: SlotIndex, rooms: RoomIndex) -> Alternative:
    """솔버 대안 하나 {placements: {(분반, 회차): (시작 칸, 강의실)}, ks: {...}} → 재성 Alternative."""
    meetings = []
    for (sec, ss), (start_id, room_id) in option["placements"].items():
        k = option["ks"][(sec, ss)]
        day, _p, start, _e = slots.info[start_id]
        meetings.append(Meeting(day=DAYS.index(day), start=start, end=slots.end(start_id, k),
                                room=rooms.name_of[room_id]))
    meetings.sort(key=lambda m: (m.day, m.start))
    return Alternative(key=key, meetings=meetings)


def unique_options(options: List[dict], course_id: int, slots: SlotIndex, rooms: RoomIndex) -> List[dict]:
    """서버에서 보면 같은 자리인 대안을 뺀다. 솔버는 회차 번호만 바꾼 안(1회차 월·2회차 수 ↔ 1회차 수·2회차 월)을
    다른 안으로 내지만, 요일·시각·강의실이 같으므로 교수에게는 같은 안이다."""
    out, seen = [], set()
    for o in options:
        key = tuple((m.day, m.start, m.end, m.room)
                    for m in option_to_alternative("A", o, course_id, slots, rooms).meetings)
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def options_to_alternatives(options: List[dict], course_id: int, slots: SlotIndex,
                            rooms: RoomIndex) -> List[Alternative]:
    """솔버 대안 목록(순서대로) → A·B·C."""
    return [option_to_alternative(k, o, course_id, slots, rooms) for k, o in zip(KEYS, options)]


def solver_condition(cond) -> Optional[dict]:
    """서버·재성 조건 → 솔버 condition. 요일별 교시(day_slots) 모양 그대로 넘긴다. 비면 None."""
    if cond is None:
        return None
    c = conditions_json(cond)
    return c if (c["day_slots"] or c["end_before"]) else None


# ---------- 어댑터 ----------

class SolverAdapter:
    def __init__(self, con, term_id: int, round_id: int, sections: Union[SectionMap, Dict[SectionKey, str]],
                 timetable_id: Optional[int] = None, wish_round_id: Optional[int] = None,
                 draft_time_limit: int = DRAFT_TIME_LIMIT, alt_time_limit: int = ALT_TIME_LIMIT):
        self.hdb, self.sc = load_haeyoon()
        self.con = con
        self.term_id, self.round_id = term_id, round_id
        self.wish_round_id = wish_round_id if wish_round_id is not None else round_id
        self.timetable_id = timetable_id
        self.sections = sections if isinstance(sections, SectionMap) else SectionMap(sections)
        self.slots = SlotIndex(con, term_id)
        self.rooms = RoomIndex(con)
        self.draft_time_limit, self.alt_time_limit = draft_time_limit, alt_time_limit
        self.last_options: Dict[str, List[dict]] = {}     # 분반 id → 마지막으로 만든 솔버 대안 (save_proposal용)
        self.last_solve: Optional[dict] = None

    # --- 하윤 함수 부르기 ---

    def solve(self, previous_timetable_id: Optional[int] = None, free: Optional[Iterable[str]] = None) -> dict:
        free_courses = None if free is None else {self.sections.key(s) for s in free}
        r = _call(self.sc.solve, self.con, self.term_id, self.round_id, time_limit=self.draft_time_limit,
                  previous_timetable_id=previous_timetable_id, free_courses=free_courses,
                  wish_round_id=self.wish_round_id)
        self.last_solve = r
        if r.get("timetable_id") is not None:
            self.timetable_id = r["timetable_id"]
        return r

    def options(self, section_id: str, conditions=None, n: int = 3) -> List[dict]:
        if self.timetable_id is None:
            raise RuntimeError("시간표가 없습니다. 먼저 solve()로 초안을 만드세요.")
        cid, sec = self.sections.key(section_id)
        opts = _call(self.sc.make_alternatives, self.con, self.term_id, self.round_id, self.timetable_id, cid,
                     section_no=sec, condition=solver_condition(conditions), n=n,
                     time_limit=self.alt_time_limit, wish_round_id=self.wish_round_id)
        opts = unique_options(opts, cid, self.slots, self.rooms)   # 회차 번호만 바뀐 같은 안은 하나로
        self.last_options[section_id] = opts
        return opts

    def save_proposal(self, section_id: str, reason: str = "") -> int:
        """마지막으로 만든 대안을 proposal 테이블에 저장한다."""
        cid, sec = self.sections.key(section_id)
        return self.sc.save_proposal(self.con, self.round_id, self.timetable_id, cid,
                                     self.last_options.get(section_id, []), reason, section_no=sec)

    def finalize(self) -> None:
        self.sc.finalize(self.con, self.timetable_id)

    def assignments(self, timetable_id: Optional[int] = None) -> Dict[str, Assignment]:
        start, ks = self.sc.load_assignment(self.con, timetable_id or self.timetable_id)
        return assignments_from_db(start, ks, self.slots, self.rooms, self.sections)

    # --- 서버 모양 ---

    def make_draft(self) -> Tuple[Timetable, List[str]]:
        r = self.solve()
        if r.get("timetable_id") is None:
            raise RuntimeError(f"솔버가 초안을 만들지 못했습니다 (status={r.get('status')})")
        placed = self.assignments()
        unplaced = {(c, s) for c, s, *_ in r.get("unplaced", [])}
        delayed = []
        for key, sid in self.sections.sid_of.items():
            if key in unplaced:
                placed[sid] = Assignment(section_id=sid, blocks=[], room=None, status="COORD",
                                         reason="솔버가 하드 규칙을 지키며 놓을 자리를 찾지 못함")
                delayed.append(sid)
        tt = Timetable(status="DRAFT", assignments=list(placed.values()))
        return tt, delayed

    def make_alternatives(self, section_id: str, conditions=None) -> List[Alternative]:
        cid, _ = self.sections.key(section_id)
        return options_to_alternatives(self.options(section_id, conditions), cid, self.slots, self.rooms)

    def reassign(self, timetable: Timetable, section_id: str, choice) -> Timetable:
        """고른 안(Alternative) 또는 조건 → 그 분반만 바꾼 새 시간표. DB에는 아직 쓰지 않는다."""
        tt = parse(Timetable, dump(timetable))
        if not isinstance(choice, Alternative):
            alts = self.make_alternatives(section_id, choice)
            if not alts:
                return tt
            choice = alts[0]
        blocks = []
        for m in choice.meetings:
            sid = self.slots.id_of[(DAYS[m.day], m.start)]
            k = next(n for n in range(1, 4) if self.slots.end(sid, n) == m.end)
            blocks.append(Block(day=DAYS[m.day], start=m.start, slots=k, room=m.room))   # 수업마다 강의실 유지
        for a in tt.assignments:
            if a.section_id == section_id:
                set_place(a, blocks)
                a.status, a.reason = "DONE", None
        return tt


# ---------- engine.py가 부르는 모듈 함수 (서버 모양) ----------

_ADAPTER: Optional[SolverAdapter] = None


def configure(adapter: Optional[SolverAdapter]) -> None:
    global _ADAPTER
    _ADAPTER = adapter


def default_paths() -> Tuple[Path, Path]:
    """(DB 파일, 분반 대응표). 기본: 저장소 맨 위 ssuroom.db, data/private/<DATA_SET>/section_map.json."""
    data = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
    return (Path(os.environ.get("SSUROOM_DB") or REPO_ROOT / "ssuroom.db"),
            Path(os.environ.get("SSUROOM_SECTION_MAP") or data / "section_map.json"))


def from_files(db_path: Optional[Path] = None, map_path: Optional[Path] = None) -> SolverAdapter:
    """시드 스크립트가 만든 DB와 대응표로 어댑터를 만든다. MANUAL 분반은 대응표에만 있고 DB에는 없다."""
    d, m = default_paths()
    db_path, map_path = Path(db_path or d), Path(map_path or m)
    for f, how in ((db_path, "DB"), (map_path, "분반 대응표")):
        if not f.exists():
            raise RuntimeError(f"{how} 파일이 없습니다: {f}. 먼저 python backend/tools/seed_db.py 를 실행하세요.")
    mp = json.loads(map_path.read_text(encoding="utf-8"))
    pairs = {(v["course_id"], v["section_no"]): sid for sid, v in mp["sections"].items()
             if isinstance(v, dict) and not v.get("manual")}
    # 서버(FastAPI)는 요청을 다른 스레드에서 처리하므로 check_same_thread=False로 연다.
    # (하윤 db.connect와 같이 외래키 검사를 켠다. db.connect에 이 인자가 생기면 그걸 쓴다)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    return SolverAdapter(con, mp["term_id"], mp["round_id"], pairs)


def current() -> SolverAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        try:
            _ADAPTER = from_files()
        except RuntimeError as e:
            raise RuntimeError(f"솔버 어댑터가 정해지지 않았습니다. configure(...)를 부르거나 시드를 만드세요. ({e})") from e
    return _ADAPTER


def make_draft(sections: List[Section], wishes: List[Wish], rooms: List[Room]) -> Tuple[Timetable, List[str]]:
    """분반·희망·강의실은 DB에서 읽으므로 인자는 쓰지 않는다 (서버 모양을 맞추려고 받기만 한다)."""
    return current().make_draft()


def make_alternatives(section_id: str, conditions: Optional[Conditions] = None) -> List[Alternative]:
    return current().make_alternatives(section_id, conditions)


def reassign(timetable: Timetable, section_id: str, choice: Union[Alternative, Conditions]) -> Timetable:
    return current().reassign(timetable, section_id, choice)
