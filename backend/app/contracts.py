# 임시 데이터 모양. 문하윤 schemas.py가 오면 그걸로 바꿀 것.
# (구현 계획서 3절 요약을 옮긴 것. 이름이 달라지면 이 파일을 지우고 import만 바꾼다.)
#
# Pydantic 1.x / 2.x 둘 다에서 돌도록 validator, parse(), dump()만 쓴다.

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

DAYS = ("월", "화", "수", "목", "금")
STARTS = ("09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30")

Day = Literal["월", "화", "수", "목", "금"]
# 실제 초안에 토요일 블록(Co-op 등 MANUAL 분반)이 있어 Block만 토요일을 받는다.
# 자동 배정·희망·조건은 월~금(Day)만 쓴다.
BlockDay = Literal["월", "화", "수", "목", "금", "토"]
LabNeed = Literal["MUST", "PREFER", "NONE"]
Shape = Literal["TWICE", "ONCE_LONG", "MANUAL"]
Label = Literal["A", "B", "C"]

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


class Alternative(BaseModel):
    label: Label
    blocks: List[Block]
    room: Optional[str] = None


# ---------- 조율 ----------

class TimeRange(BaseModel):
    start: str
    end: str

    _hhmm = validator("start", "end", allow_reuse=True)(_check_hhmm)


class Conditions(BaseModel):
    days: List[Day] = []                     # 가능한 요일 (빈 목록 = 제한 없음)
    time_ranges: List[TimeRange] = []        # 가능한 시간대 (빈 목록 = 제한 없음)
    end_before: Dict[Day, str] = {}          # 요일별 종료 시각. {"수": "17:00"}

    @validator("end_before")
    def _end_before(cls, v):
        for t in v.values():
            _check_hhmm(t)
        return v


class ReplyParse(BaseModel):
    decision: Literal["수용", "조건부", "거절", "확인필요"]
    chosen: List[Label] = []
    conditions: Conditions = Conditions()


class Proposal(BaseModel):
    """처리안. match_conditions가 만들고 조교가 [확인]해야 반영된다."""
    action: Literal["MOVE", "KEEP", "ASK"]
    alternative: Optional[Alternative] = None
    summary: str
    rejected: List[str] = []                 # 조건과 안 맞아 뺀 안과 이유


class Violation(BaseModel):
    rule: str                                # "강의실 겹침" 등
    section_ids: List[str]
    detail: str


class MessageIssue(BaseModel):
    kind: Literal["금지 내용", "필수 내용 빠짐"]
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
