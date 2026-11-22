"""메모리 저장소. DB(문하윤 db/)가 오기 전까지 서버 상태를 여기에만 둔다.

나중에 SQLite로 옮길 때는 이 파일의 Store 메서드만 바꾸면 되도록,
main.py는 상태를 직접 만지지 않고 이 메서드들만 부른다.

데이터 묶음: 환경변수 DATA_SET (기본 real) → data/private/<DATA_SET>/
  sections.json, rooms.json, wishes.json, timetable.json, fixed_blocks.json
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .contracts import (
    DAYS, STARTS, Alternative, Assignment, Block, Message, MessageInput, Proposal, ReplyParse, Room,
    Section, Timetable, Wish, block_minutes, dump, parse, section_shape,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGES = ("COLLECT", "DRAFT", "ROUND", "FINAL")
MAX_ROUND = 3


def data_dir() -> Path:
    return REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _grid_cell(key: str) -> bool:
    day, _, start = key.partition("-")
    return day in DAYS and start in STARTS


# 학과 설정 기본값. GET/POST /settings 로 보고 바꾼다. /reset 하면 기본값으로 돌아간다.
DEFAULT_SETTINGS = {
    # 조율 메시지에 겹친 상대 교수 이름 알리기
    # (팀 결정: 상대 교수 이름 공개는 기본 켬, 조교가 설정에서 끌 수 있음)
    "reveal_opponent": True,
}


def course_text(sec: Section) -> str:
    """조율 메시지의 과목·분반 이름. 예: '자료구조 02', '디지털시스템입문 03 (공통-재수강)'."""
    div = (sec.division or "").strip()
    if div and not div.startswith("("):
        div = f"({div})"
    return f"{sec.name} {sec.code[-2:]}" + (f" {div}" if div else "")


def wish_text(wish: Optional[Wish]) -> str:
    """희망(PREFER) 칸을 글로. 같은 시작 시각끼리 요일을 묶는다. 예: '월·수 15:00, 화 10:30'."""
    cells = [k for k, v in (wish.cells if wish else {}).items() if v == "PREFER"]
    if not cells:
        return "희망 칸 없음"
    by_start: Dict[str, List[str]] = {}
    for k in cells:
        day, _, start = k.partition("-")
        by_start.setdefault(start, []).append(day)
    parts = sorted(by_start.items(), key=lambda kv: (min(DAYS.index(d) for d in kv[1]), kv[0]))
    return ", ".join(f"{'·'.join(sorted(ds, key=DAYS.index))} {st}" for st, ds in parts)


def _cell_block(cell: str) -> Block:
    day, _, start = cell.partition("-")
    return Block(day=day, start=start, slots=1)


def _overlap(a: Block, b: Block) -> bool:
    if a.day != b.day:
        return False
    a0, a1 = block_minutes(a)
    b0, b1 = block_minutes(b)
    return a0 < b1 and b0 < a1


def _load(name: str):
    path = data_dir() / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 가 없습니다. 먼저 python backend/tools/import_real.py --src <원본 폴더> 를 실행하세요."
        )
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class Store:
    def __init__(self) -> None:
        self.reset()

    # ---------- 처음 상태 ----------

    def reset(self) -> None:
        tt_file = parse(Timetable, _load("timetable.json"))
        file_blocks = {a.section_id: a for a in tt_file.assignments}

        self.sections: Dict[str, Section] = {}
        for raw in _load("sections.json"):
            a = file_blocks.get(raw["id"])
            raw = dict(raw, shape=section_shape(raw["weekly_blocks"], a.blocks if a else []))
            self.sections[raw["id"]] = parse(Section, raw)

        # MANUAL 분반은 파일의 자리를 그대로 시간표에 보인다.
        self.manual_assignments: Dict[str, Assignment] = {
            sid: Assignment(section_id=sid, blocks=a.blocks, room=a.room, status="MANUAL",
                            reason="조교 직접 배정 분반 (수업 모양이 주 2회·주 1회 연강이 아님)")
            for sid, a in file_blocks.items()
            if sid in self.sections and self.sections[sid].shape == "MANUAL"
        }

        self.load_warnings: List[str] = []
        self.rooms: Dict[str, Room] = {r["id"]: parse(Room, r) for r in _load("rooms.json")}
        wishes_raw = _load("wishes.json")
        self.wishes: Dict[str, Wish] = {}
        for w in wishes_raw.get("wishes", []):
            # 파일에는 토요일·8칸 밖 시각(예: 수-17:00) 칸이 있다. Wish 형식(월~금 × 8칸)에 맞는 칸만 남긴다.
            cells = {k: v for k, v in w.get("cells", {}).items() if _grid_cell(k)}
            dropped = sorted(set(w.get("cells", {})) - set(cells))
            if dropped:
                self.load_warnings.append(f"{w['section_id']}: 희망 칸 {len(dropped)}개 버림 {dropped}")
            self.wishes[w["section_id"]] = parse(Wish, dict(w, cells=cells))
        self.professors: Dict[str, dict] = wishes_raw.get("professors", {})
        self.fixed_blocks: List[dict] = _load("fixed_blocks.json")

        self.settings: Dict[str, object] = dict(DEFAULT_SETTINGS)   # 학과 설정
        self.stage: str = "COLLECT"
        self.round_no: int = 0            # 0 = 조율 시작 전, 1~3 = 차수
        self.timetable: Optional[Timetable] = None
        self.coord: Dict[str, dict] = {}  # 조율 목록: 분반 id → 조율 상태
        self.messages: List[dict] = []    # 보낸(또는 막힌) 조율 메시지 기록
        self.replies: List[dict] = []     # 교수 답장과 해석 기록
        self.decisions: List[dict] = []   # 조교 결정(확인·수정·유지) 기록, 사유 포함

    # ---------- 기본 자료 ----------

    def list_sections(self) -> List[Section]:
        return list(self.sections.values())

    def get_section(self, sid: str) -> Optional[Section]:
        return self.sections.get(sid)

    def list_rooms(self) -> List[Room]:
        return list(self.rooms.values())

    def list_wishes(self) -> List[Wish]:
        return list(self.wishes.values())

    def get_wish(self, sid: str) -> Optional[Wish]:
        return self.wishes.get(sid)

    def save_wish(self, wish: Wish) -> None:
        self.wishes[wish.section_id] = wish

    # ---------- 단계·시간표 ----------

    def set_stage(self, stage: str, round_no: Optional[int] = None) -> None:
        assert stage in STAGES
        self.stage = stage
        if round_no is not None:
            self.round_no = round_no
        if self.timetable is not None:
            self.timetable.status = "DRAFT" if stage in ("COLLECT", "DRAFT") else stage

    def set_timetable(self, tt: Timetable) -> None:
        self.timetable = tt

    # ---------- 조율 목록 ----------

    def open_coord(self, sid: str, reason: Optional[str], alternatives: List[Alternative]) -> None:
        self.coord[sid] = {
            "section_id": sid,
            "reason": reason,
            "round_no": self.round_no or None,
            "state": "OPEN",             # OPEN → SENT → PROPOSED → RESOLVED | KEPT | NEXT
            "alternatives": alternatives,
            "message": None,
            "proposal": None,
            "last_parse": None,
            "next_conditions": None,     # 조교가 [확인]한 조건 (처리안 next). 다음 차수 대안에 이것만 쓴다
            "prev_conditions": None,     # 지난 차수에서 넘어온 (확인된) 조건. 조율 메시지에 쓴다
        }

    def get_coord(self, sid: str) -> Optional[dict]:
        return self.coord.get(sid)

    def list_coord(self) -> List[dict]:
        return list(self.coord.values())

    def update_coord(self, sid: str, **fields) -> dict:
        self.coord[sid].update(fields)
        return self.coord[sid]

    # ---------- 학과 설정 ----------

    def get_settings(self) -> Dict[str, object]:
        return dict(self.settings)

    def update_settings(self, **fields) -> Dict[str, object]:
        unknown = set(fields) - set(DEFAULT_SETTINGS)
        if unknown:
            raise KeyError(", ".join(sorted(unknown)))
        self.settings.update(fields)
        return self.get_settings()

    # ---------- 조율 메시지 입력 ----------

    def blocker(self, sid: str) -> Optional[str]:
        """희망 칸을 막고 있는 다른 분반 id (추정). 같은 강의실 → 같은 교수 순으로 찾는다.
        배정 엔진이 '누구와 겹쳤는지'를 알려 주게 되면 그 값으로 바꾼다."""
        if self.timetable is None:
            return None
        me = next((a for a in self.timetable.assignments if a.section_id == sid), None)
        sec, wish = self.sections.get(sid), self.wishes.get(sid)
        if me is None or sec is None or wish is None:
            return None
        cells = [_cell_block(k) for k, v in sorted(wish.cells.items()) if v == "PREFER"]
        others = [a for a in self.timetable.assignments if a.section_id != sid]

        def same_prof(a: Assignment) -> bool:
            o = self.sections.get(a.section_id)
            return bool(o and sec.professor and o.professor == sec.professor)

        for test in (lambda a: me.room is not None and a.room == me.room, same_prof):
            for c in cells:
                hit = next((a for a in others if test(a) and any(_overlap(b, c) for b in a.blocks)), None)
                if hit is not None:
                    return hit.section_id
        return None

    def message_input(self, sid: str) -> MessageInput:
        """write_message·check_message에 넣을 값. 분반·희망·대안·차수·겹친 상대로 채운다.
        - 상대 교수 이름은 학과 설정 reveal_opponent(기본 켬)를 따른다. 끄면 메시지에 쓰지 않는다.
          그래도 blocker_prof는 넣는다: check_message가 이름이 새지 않았는지 검사하는 데 쓴다.
        - 연차·임용일·우선순위는 MessageInput에 칸이 없고, 넣지 않는다.
        - hidden: 상대 교수가 적은 기타 요청(Wish.note). 메시지에 나오면 안 되므로 검사에만 쓴다."""
        sec = self.sections[sid]
        item = self.coord[sid]
        other_id = self.blocker(sid)
        other = self.sections.get(other_id) if other_id else None
        other_wish = self.wishes.get(other_id) if other_id else None
        prev = item.get("prev_conditions") if self.round_no >= 2 else None   # 지난 차수에 조교가 확인한 조건
        fields = dict(
            professor=sec.professor or "담당",
            course=course_text(sec),
            round=max(1, min(self.round_no, MAX_ROUND)),
            wish=wish_text(self.wishes.get(sid)),
            alternatives=item["alternatives"],
            blocker_prof=other.professor if other else None,
            blocker_course=course_text(other) if other else None,
            reveal=bool(self.settings["reveal_opponent"]),
            prev_conditions=prev if prev is not None and not prev.is_empty() else None,
            hidden=[other_wish.note.strip()] if other_wish and other_wish.note.strip() else [],
        )
        if os.environ.get("COORD_TERM"):
            fields["term"] = os.environ["COORD_TERM"]
        return MessageInput(**fields)

    # ---------- 기록 ----------

    def add_message(self, sid: str, msg: Message, issues: List[str], sent: bool) -> dict:
        """msg = write_message 결과, issues = check_message 결과 (빈 목록이면 보냄)."""
        rec = {"section_id": sid, "round_no": self.round_no, "text": msg.text, "method": msg.method,
               "fallback": msg.fallback, "problems": list(msg.problems),
               "issues": issues, "sent": sent, "at": _now()}
        self.messages.append(rec)
        return rec

    def add_reply(self, sid: str, text: str, choice: Optional[str], method: str, parsed: ReplyParse,
                  proposal: Proposal, unavailable: List[str]) -> dict:
        rec = {"section_id": sid, "round_no": self.round_no, "text": text, "choice": choice, "method": method,
               "parse": dump(parsed), "proposal": dump(proposal),
               # 교수 요청(조교 확인용). 화면에 처리안과 함께 보여 줄 뿐, 배정·다음 차수 조건에는 쓰지 않는다
               "note": getattr(parsed, "note", ""),
               "unavailable": unavailable, "at": _now()}
        self.replies.append(rec)
        return rec

    def add_decision(self, sid: str, action: str, reason: Optional[str], applied: Optional[dict]) -> dict:
        rec = {"section_id": sid, "round_no": self.round_no, "action": action,
               "reason": reason, "applied": applied, "at": _now()}
        self.decisions.append(rec)
        return rec


store = Store()
