# 임시 데이터 모양. 문하윤 schemas.py가 오면 그걸로 바꿀 것.
# (구현 계획서 3절 요약을 옮긴 것. 이름이 달라지면 이 파일을 지우고 import만 바꾼다.)
#
# 조율 모델은 coord_models.py와 같게 유지. 합쳐진 뒤에는 coord_models에서 import.
#   (Meeting, Alternative, EndBefore, Conditions, ReplyParse, MessageInput, Message, PickCheck, Proposal
#    — 최재성 backend/app/nlp/coord_models.py 기준. 필드 이름·타입·값을 바꾸지 않는다.)
# 배정 쪽 모델(Room, Section, Block, Wish, Assignment, Timetable 등)은 이 파일이 기준이다.
#
# validator, parse()는 Pydantic 1.x 시절 모양을 그대로 둔다. 조율 Conditions는 coord_models와 똑같이 Pydantic 2 모양.

import re
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator, validator

DAYS = ("월", "화", "수", "목", "금")
STARTS = ("09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30")

Day = Literal["월", "화", "수", "목", "금"]
# 실제 초안에 토요일 블록(Co-op 등 MANUAL 분반)이 있어 Block만 토요일을 받는다.
# 자동 배정·희망·조건은 월~금(Day)만 쓴다.
BlockDay = Literal["월", "화", "수", "목", "금", "토"]
# 실습실: 필요 / 필요 없음 두 가지 (팀 결정 11/21). 값 이름은 하윤 DB lab_requirement와 같게 MUST·NONE.
# (DB에는 PREFER도 있지만 서버·화면은 쓰지 않는다)
LabNeed = Literal["MUST", "NONE"]
# 주 1회 연강(하루에 두 교시를 이어서): 무조건 / 선호 / 필요 없음(주 2회). 하윤 DB single_day_pref와 같은 이름 (11/21)
SingleDay = Literal["MUST", "PREFER", "NONE"]
Shape = Literal["TWICE", "ONCE_LONG", "MANUAL"]

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_hhmm(v: str) -> str:
    if not _HHMM.match(v):
        raise ValueError(f"시각은 HH:MM 이어야 함: {v!r}")
    return v


# ---------- 기본 자료 ----------

class Room(BaseModel):
    id: str                      # "정보과학관 21303"
    building: str
    room_no: str
    capacity: Optional[int] = None
    is_lab: bool = False
    estimated: bool = False      # 정원·실습실 여부가 추정값이면 True


class Section(BaseModel):
    id: str                      # 분반키: code 또는 code-division
    code: str
    name: str
    division: Optional[str] = None
    year: Optional[int] = None   # None = 전체 학년
    category: str = ""
    enrollment: Optional[int] = None
    weekly_blocks: int           # 주당 75분 칸 수
    professor: Optional[str] = None   # 가명. None = 담당 미정
    lab_need: LabNeed = "NONE"
    shape: Shape = "TWICE"       # MANUAL = 조교 직접 배정 (자동 배정·조율 대상 아님)


class Block(BaseModel):
    """수업 한 번. start는 8칸 시작 시각이 기본이지만 실제 데이터의 다른 시각도 받는다.
    day는 월~금. 토요일은 MANUAL 분반을 그대로 보이기 위해서만 받는다."""
    day: BlockDay
    start: str
    slots: int = Field(..., ge=1)   # 1 = 75분, 2 = 연강

    _start = validator("start", allow_reuse=True)(_check_hhmm)


class Wish(BaseModel):
    section_id: str
    professor: Optional[str] = None
    cells: Dict[str, Literal["PREFER", "BLOCK"]] = {}   # "월-09:00": "PREFER". 안 칠한 칸 = 가능
    must: bool = False
    lab: LabNeed = "NONE"                        # MUST = 실습실 필요, NONE = 필요 없음
    single_day: SingleDay = "NONE"               # 주 1회 연강. NONE = 주 2회(기본)
    building: Optional[str] = None
    room: Optional[str] = None
    note: str = ""

    @validator("cells")
    def _cells_keys(cls, v):
        for key in v:
            day, _, start = key.partition("-")
            if day not in DAYS or start not in STARTS:
                raise ValueError(f"칸 이름은 '요일-시작'(예: 월-09:00)이어야 함: {key!r}")
        return v


class Assignment(BaseModel):
    section_id: str
    blocks: List[Block] = []
    room: Optional[str] = None
    status: Literal["DONE", "COORD", "MANUAL"] = "DONE"
    reason: Optional[str] = None   # 밀린 이유 (COORD일 때)


class Timetable(BaseModel):
    status: Literal["DRAFT", "ROUND", "FINAL"] = "DRAFT"
    assignments: List[Assignment] = []


# ---------- 조율 (최재성 coord_models.py와 같은 모양) ----------
# 조율 모델은 coord_models.py와 같게 유지. 합쳐진 뒤에는 coord_models에서 import.
# (지금도 backend/app/nlp/coord_models.py가 있으면 아래 사본 대신 그쪽 클래스를 쓴다.
#  진짜 coord 함수와 서버가 같은 클래스를 주고받아야 Pydantic 검사에서 안 걸린다.)
# 요일은 숫자 0=월 … 4=금 (배정 쪽 Block은 "월" 글자). 바꾸려면 blocks_to_meetings / meetings_to_blocks.

DAYN = "월화수목금"
# 교시 시작 시각: 09:00부터 90분 간격 (75분 수업 + 15분 쉬는 시간). 배정 쪽 STARTS와 같다
SLOTS = list(STARTS)
Key = Literal["A", "B", "C"]
Kind = Literal["수용", "조건부", "거절", "확인 필요"]


class Meeting(BaseModel):
    """수업 한 번. 주 2회 수업은 2개, 주 1회 연강은 1개(두 칸 길이)."""
    day: int = Field(ge=0, le=4)
    start: str                     # "15:00"
    end: str                       # "16:15"
    room: str                      # "정보관 305"


class Alternative(BaseModel):
    """조율 메시지에 넣는 대안 하나 (배정 엔진의 make_alternatives가 만든다)."""
    key: Key
    meetings: List[Meeting]


class EndBefore(BaseModel):
    day: int = Field(ge=0, le=4)
    time: str                      # "17:00" 전에 끝나야 함


class Conditions(BaseModel):
    """교수 답장에서 뽑은 조건. 다음 차수 대안을 만들 때 배정 엔진이 읽는다.

    day_slots: 요일(0~4) → 그 요일에 되는 교시 시작 시각. 빈 목록 = 그 요일은 아무 교시나 (11/22, 요일별 교시)
      - "화 오전이나 목 오후" → {1: ["09:00", "10:30"], 3: ["13:30", "15:00", "16:30"]}
      - "화목이면 돼요"       → {1: [], 3: []}
      - 비어 있으면 요일·교시 제한 없음
      요일이 둘 이상이면 수업이 그 요일들 안에서만, 하나면 그 요일이 들어가기만 하면 된다 (주 2회의 다른 하루는 자유).
      연강은 두 교시가 모두 들어 있어야 맞다.
    end_before: 요일별로 이 시각 전에 끝나야 함.

    옛 모양 {"days": [...], "slots": [...]}도 받는다 (요일 × 교시로 바꿈). 읽기용 days·slots는 옛 코드용 근사값이다.
    """
    day_slots: Dict[int, List[str]] = {}
    end_before: List[EndBefore] = []

    @model_validator(mode="before")
    @classmethod
    def _from_old_shape(cls, v):
        if isinstance(v, dict) and "day_slots" not in v and ("days" in v or "slots" in v):
            v = dict(v)
            days, slots = v.pop("days", None) or [], v.pop("slots", None) or []
            v["day_slots"] = {d: list(slots) for d in (days or (range(5) if slots else []))}
        return v

    @field_validator("day_slots")
    @classmethod
    def _check_day_slots(cls, v):
        out = {}
        for d in sorted(v):
            if not 0 <= d <= 4:
                raise ValueError(f"요일은 0~4: {d}")
            bad = [s for s in v[d] if s not in SLOTS]
            if bad:
                raise ValueError(f"교시 시작 시각이 아님: {bad}")
            out[d] = sorted(set(v[d]), key=SLOTS.index)
        return out

    def is_empty(self) -> bool:
        return not self.day_slots and not self.end_before

    # ---- 옛 코드(days·slots를 읽던 곳)용 읽기 전용 근사값. 새 코드는 day_slots를 읽는다 ----
    @property
    def days(self) -> List[int]:
        """다섯 요일이 다 있으면 요일 제한 없음([])으로 본다."""
        return [] if set(self.day_slots) == set(range(5)) else list(self.day_slots)

    @property
    def slots(self) -> List[str]:
        """요일별 교시를 합친 것. 어느 요일이 '아무 교시나'면 교시 제한 없음([])."""
        if not self.day_slots or any(not s for s in self.day_slots.values()):
            return []
        return sorted({s for v in self.day_slots.values() for s in v}, key=SLOTS.index)


class ReplyParse(BaseModel):
    """parse_reply 결과."""
    kind: Kind
    picks: List[Key] = []          # 고른 안, 선호 순서
    conditions: Conditions = Conditions()
    note: str = ""                 # 조교가 확인하거나 바꿔야 할 요청 (강의실 변경·장비·정원·교시 조정 희망). 배정 엔진은 읽지 않고 조교가 본다
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False         # 언어 모델이 실패해서 키워드 방식으로 대신 처리했으면 True


class MessageInput(BaseModel):
    """write_message·check_message에 넣는 값. 서버가 분반·희망·대안·차수·겹친 상대로 채운다."""
    professor: str                 # 받는 교수
    course: str                    # "객체지향프로그래밍 02"
    term: str = "2027-1학기"
    round: int = Field(ge=1, le=3)
    wish: str                      # 본인 희망 그대로 ("월·수 15:00")
    alternatives: List[Alternative]
    blocker_prof: Optional[str] = None     # 겹친 상대 교수
    blocker_course: Optional[str] = None   # 겹친 상대 강의 ("자료구조 01")
    reveal: bool = True                    # 상대 교수 이름 알리기 (학과 설정)
    prev_conditions: Optional[Conditions] = None   # 지난 차수 답장에서 받은 조건
    hidden: List[str] = []         # 메시지에 나오면 안 되는 글 (상대 교수의 기타 요청 등)


class Message(BaseModel):
    """write_message 결과."""
    text: str
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False
    problems: List[str] = []       # 언어 모델 글이 검사에서 걸린 이유 (fallback일 때)


class PickCheck(BaseModel):
    key: str
    ok: bool
    why: str


class Proposal(BaseModel):
    """match_conditions 결과 = 조교에게 보여 줄 처리안. 조교가 [확인]을 눌러야 실행된다."""
    action: Literal["move", "next", "decide"]   # move = 고른 안으로 옮김, next = 조건 넣어 다음 차수, decide = 조교가 직접
    key: Optional[Key] = None
    conditions: Conditions = Conditions()
    text: str
    checks: List[PickCheck] = []


ConditionsCopy = Conditions   # 사본은 진짜 모델을 불러온 뒤에도 남겨 둔다 (옛 모양 → 새 모양 바꾸기에 쓴다)

try:   # 합쳐진 뒤: 진짜 모델을 쓴다 (위 사본과 같은 모양이어야 한다)
    from .nlp.coord_models import (  # type: ignore  # noqa: F811
        Alternative, Conditions, EndBefore, Meeting, Message, MessageInput, PickCheck, Proposal, ReplyParse,
    )
    COORD_MODELS = "real (nlp.coord_models)"
except Exception:   # 없거나 불러오다 실패하면 사본 (실패 경고는 engine이 남긴다)
    COORD_MODELS = "copy (contracts.py)"


def as_day_slots(cond) -> "ConditionsCopy":
    """어떤 모양의 조건이든 요일별 교시(day_slots) 사본으로 바꾼다.
    진짜 coord_models가 아직 옛 모양(days·slots)일 때도 서버는 day_slots로 읽고 내보낸다."""
    if cond is None:
        return ConditionsCopy()
    if isinstance(cond, ConditionsCopy):
        return cond
    data = cond if isinstance(cond, dict) else cond.model_dump()
    return ConditionsCopy.model_validate(data)


def conditions_json(cond) -> dict:
    """API로 내보내는 조건 모양: {"day_slots": {"1": [...]}, "end_before": [...]}. 요일 키는 문자열."""
    c = as_day_slots(cond)
    return {"day_slots": {str(d): list(s) for d, s in c.day_slots.items()},
            "end_before": [{"day": e.day, "time": e.time} for e in c.end_before]}


def _is_conditions_dict(v) -> bool:
    return isinstance(v, dict) and "end_before" in v and set(v) <= {"days", "slots", "day_slots", "end_before"}


# ---------- 배정 결과 확인 ----------

class Violation(BaseModel):
    rule: str                                # "강의실 겹침" 등
    section_ids: List[str]
    detail: str


class WhatIfResult(BaseModel):
    changed: List[str]
    violations: int


# ---------- AI 도우미 ----------

class AssistantCommand(BaseModel):
    intent: Literal["explain", "move", "what_if", "status", "out_of_scope"]
    section_id: Optional[str] = None
    professor: Optional[str] = None
    day: Optional[Day] = None
    start: Optional[str] = None
    room: Optional[str] = None
    ask_back: Optional[str] = None           # 정보가 모자라면 되물을 말


# ---------- 도우미 함수 ----------

def section_shape(weekly_blocks: int, blocks: List[Block]) -> str:
    """주 2회(1칸×2) / 주 1회 연강(2칸×1)만 자동 배정 대상. 나머지는 MANUAL."""
    if weekly_blocks != 2 or any(b.day not in DAYS for b in blocks):
        return "MANUAL"
    slots = sorted(b.slots for b in blocks)
    if slots == [1, 1]:
        return "TWICE"
    if slots == [2]:
        return "ONCE_LONG"
    if not blocks:
        return "TWICE"   # 초안에 없는 2칸 분반은 기본 모양으로 본다
    return "MANUAL"


# ---------- 시간 규칙 (팀 결정 11/21) ----------
# - 수업은 웬만하면 19:15 전에 끝낸다. 19:30 교시는 하드 규칙이 아니라 큰 감점: 다른 안이 없을 때만 쓴다.
# - 18:00 시작 연강(18:00~20:45)은 없다 (하드).
LATE_SLOT = "19:30"
LATE_PENALTY = 100      # 19:30 교시를 쓰는 수업 한 번마다 깎는 점수 (가짜 함수·도우미가 같은 값을 쓴다)


def late_penalty(blocks: List[Block]) -> int:
    """19:30 교시를 쓰는 수업 수 × LATE_PENALTY. 0이면 늦은 교시 없음."""
    n = 0
    for b in blocks:
        if b.start in STARTS and LATE_SLOT in STARTS[STARTS.index(b.start):STARTS.index(b.start) + b.slots]:
            n += 1
    return n * LATE_PENALTY


def no_long_at_1800(blocks: List[Block]) -> bool:
    """18:00 시작 연강이 없으면 True."""
    return not any(b.slots >= 2 and b.start == "18:00" for b in blocks)


def parse(cls, data):
    return cls.model_validate(data) if hasattr(cls, "model_validate") else cls.parse_obj(data)


def dump(model) -> dict:
    """모델 → dict. 안에 든 조건은 모두 요일별 교시 모양(conditions_json)으로 바꾼다."""
    if isinstance(model, ConditionsCopy) or type(model).__name__ == "Conditions":
        return conditions_json(model)
    data = model.model_dump() if hasattr(model, "model_dump") else model.dict()
    return fix_conditions(data)


def fix_conditions(v):
    if _is_conditions_dict(v):
        return conditions_json(v)
    if isinstance(v, dict):
        return {k: fix_conditions(x) for k, x in v.items()}
    if isinstance(v, list):
        return [fix_conditions(x) for x in v]
    return v


# ---------- 배정 칸(Block) ↔ 조율 수업(Meeting) ----------

def block_minutes(b: Block) -> Tuple[int, int]:
    """칸 1개 = 75분, 칸 사이 쉬는 시간 15분. 2칸 = 165분."""
    h, m = b.start.split(":")
    s = int(h) * 60 + int(m)
    return s, s + 75 * b.slots + 15 * (b.slots - 1)


def blocks_to_meetings(blocks: List[Block], room: Optional[str]) -> List[Meeting]:
    out = []
    for b in blocks:
        _, e = block_minutes(b)
        out.append(Meeting(day=DAYS.index(b.day), start=b.start, end=f"{e // 60:02d}:{e % 60:02d}",
                           room=room or "강의실 미정"))
    return out


def meetings_to_blocks(meetings) -> Tuple[List[Block], Optional[str]]:
    """Meeting 목록 → (Block 목록, 강의실). 배정(Assignment)은 강의실이 하나라 첫 수업의 강의실을 쓴다."""
    blocks = []
    for m in meetings:
        h0, m0 = map(int, m.start.split(":"))
        h1, m1 = map(int, m.end.split(":"))
        slots = 1 if (h1 * 60 + m1) - (h0 * 60 + m0) <= 75 else 2
        blocks.append(Block(day=DAYS[m.day], start=m.start, slots=slots))
    room = meetings[0].room if meetings else None
    return blocks, (None if room == "강의실 미정" else room)


def alternative(key: str, blocks: List[Block], room: Optional[str]):
    return Alternative(key=key, meetings=blocks_to_meetings(blocks, room))
