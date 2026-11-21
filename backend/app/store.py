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
    DAYS, STARTS, Alternative, Assignment, Proposal, ReplyParse, Room, Section, Timetable, Wish,
    dump, parse, section_shape,
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
            "state": "OPEN",             # OPEN → SENT → PROPOSED → RESOLVED | KEPT
            "alternatives": alternatives,
            "message": None,
            "proposal": None,
            "last_parse": None,
        }

    def get_coord(self, sid: str) -> Optional[dict]:
        return self.coord.get(sid)

    def list_coord(self) -> List[dict]:
        return list(self.coord.values())

    def update_coord(self, sid: str, **fields) -> dict:
        self.coord[sid].update(fields)
        return self.coord[sid]

    # ---------- 기록 ----------

    def add_message(self, sid: str, text: str, issues: List[dict], sent: bool) -> dict:
        rec = {"section_id": sid, "round_no": self.round_no, "text": text,
               "issues": issues, "sent": sent, "at": _now()}
        self.messages.append(rec)
        return rec

    def add_reply(self, sid: str, text: str, method: str, parsed: ReplyParse, proposal: Proposal) -> dict:
        rec = {"section_id": sid, "round_no": self.round_no, "text": text, "method": method,
               "parse": dump(parsed), "proposal": dump(proposal), "at": _now()}
        self.replies.append(rec)
        return rec

    def add_decision(self, sid: str, action: str, reason: Optional[str], applied: Optional[dict]) -> dict:
        rec = {"section_id": sid, "round_no": self.round_no, "action": action,
               "reason": reason, "applied": applied, "at": _now()}
        self.decisions.append(rec)
        return rec


store = Store()
