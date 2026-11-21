# 임시 데이터 모양. 문하윤 schemas.py가 오면 그걸로 바꿀 것.
# (구현 계획서 3절 요약을 옮긴 것. 이름이 달라지면 이 파일을 지우고 import만 바꾼다.)
#
# 조율 모델은 coord_models.py와 같게 유지. 합쳐진 뒤에는 coord_models에서 import.
#   (Meeting, Alternative, EndBefore, Conditions, ReplyParse, MessageInput, Message, PickCheck, Proposal
#    — 최재성 backend/app/nlp/coord_models.py 기준. 필드 이름·타입·값을 바꾸지 않는다.)
# 배정 쪽 모델(Room, Section, Block, Wish, Assignment, Timetable 등)은 이 파일이 기준이다.
#
# validator, parse(), dump()는 Pydantic 1.x 시절 모양을 그대로 둔다.

import re
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, validator

DAYS = ("월", "화", "수", "목", "금")
STARTS = ("09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30")

Day = Literal["월", "화", "수", "목", "금"]
# 실제 초안에 토요일 블록(Co-op 등 MANUAL 분반)이 있어 Block만 토요일을 받는다.
# 자동 배정·희망·조건은 월~금(Day)만 쓴다.
BlockDay = Literal["월", "화", "수", "목", "금", "토"]
LabNeed = Literal["MUST", "PREFER", "NONE"]
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
    lab: LabNeed = "NONE"
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
    """교수 답장에서 뽑은 조건. 다음 차수 대안을 만들 때 배정 엔진이 읽는다."""
    days: List[int] = []           # 둘 이상 = 그 요일 안에서만, 하나 = 그 요일을 포함
    slots: List[str] = []          # 되는 교시(시작 시각). 비면 제한 없음. 연강은 두 칸 모두 들어 있어야 맞음
    end_before: List[EndBefore] = []

    @validator("slots", allow_reuse=True)
    def _known_slots(cls, v):
        bad = [s for s in v if s not in SLOTS]
        if bad:
            raise ValueError(f"교시 시작 시각이 아님: {bad}")
        return sorted(set(v), key=SLOTS.index)

    def is_empty(self) -> bool:
        return not self.days and not self.slots and not self.end_before


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


try:   # 합쳐진 뒤: 진짜 모델을 쓴다 (위 사본과 같은 모양이어야 한다)
    from .nlp.coord_models import (  # type: ignore  # noqa: F811
        Alternative, Conditions, EndBefore, Meeting, Message, MessageInput, PickCheck, Proposal, ReplyParse,
    )
    COORD_MODELS = "real (nlp.coord_models)"
except Exception:   # 없거나 불러오다 실패하면 사본 (실패 경고는 engine이 남긴다)
    COORD_MODELS = "copy (contracts.py)"


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


def parse(cls, data):
    return cls.model_validate(data) if hasattr(cls, "model_validate") else cls.parse_obj(data)


def dump(model) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


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
