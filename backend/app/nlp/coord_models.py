"""조율 NLP가 주고받는 데이터 모양.

공용 `schemas.py`가 생기면 그쪽으로 옮긴다.
`Conditions`는 배정 엔진(백엔드 1)이 읽는 모양이다. 11/22 하윤과 요일별 교시(day_slots)로 정함.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DAYN = "월화수목금"          # 요일 번호 0~4 = 월~금
# 교시 시작 시각: 09:00부터 90분 간격 (75분 수업 + 15분 쉬는 시간). 실제 시간표에 19:30 수업도 있다
SLOTS = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30"]
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
    meetings: list[Meeting]


class EndBefore(BaseModel):
    day: int = Field(ge=0, le=4)
    time: str                      # "17:00" 전에 끝나야 함


class Conditions(BaseModel):
    """교수 답장에서 뽑은 조건. 다음 차수 대안을 만들 때 배정 엔진이 읽는다.

    day_slots: 요일(0~4) → 그 요일에 되는 교시 시작 시각. **빈 목록 = 그 요일은 아무 교시나** (11/22, 요일별 교시)
      - "화 오전이나 목 오후"   → {1: ["09:00", "10:30"], 3: ["13:30", "15:00", "16:30"]}
      - "월·수 오후"           → {0: 오후 교시, 2: 오후 교시}
      - "화목이면 돼요"         → {1: [], 3: []}
      - "오후면 아무 요일이나"   → 다섯 요일 모두 오후 교시
      - 비어 있으면 요일·교시 제한 없음
      요일이 둘 이상이면 수업이 그 요일들 안에서만, 하나면 그 요일이 들어가기만 하면 된다 (주 2회의 다른 하루는 자유).
      연강은 두 교시가 모두 들어 있어야 맞다.
    end_before: 요일별로 이 시각 전에 끝나야 함.

    옛 모양 {"days": [...], "slots": [...]}도 받는다 (요일 × 교시로 바꿈). 읽기용 days·slots는 옛 코드용 근사값이다.
    """
    day_slots: dict[int, list[str]] = {}
    end_before: list[EndBefore] = []

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
    def _check_day_slots(cls, v: dict[int, list[str]]) -> dict[int, list[str]]:
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
    def days(self) -> list[int]:
        """다섯 요일이 다 있으면 요일 제한 없음([])으로 본다."""
        return [] if set(self.day_slots) == set(range(5)) else list(self.day_slots)

    @property
    def slots(self) -> list[str]:
        """요일별 교시를 합친 것. 어느 요일이 '아무 교시나'면 교시 제한 없음([])."""
        if not self.day_slots or any(not s for s in self.day_slots.values()):
            return []
        return sorted({s for v in self.day_slots.values() for s in v}, key=SLOTS.index)


class ReplyParse(BaseModel):
    """parse_reply 결과."""
    kind: Kind
    picks: list[Key] = []          # 고른 안, 선호 순서
    ordered: bool = False          # 교수가 글로 선호 순서를 밝혔는가 ("C가 좋고 안 되면 B"). picks가 둘 이상일 때만 True.
                                   # 서버는 배정 엔진 pick_best(respect_order=ordered)에 넘긴다. False면 엔진이 점수 순으로 고른다 (11/25)
    conditions: Conditions = Conditions()
    note: str = ""                 # 조교가 확인하거나 바꿔야 할 요청 (강의실 변경·장비·정원·교시 조정 희망). 배정 엔진은 읽지 않고 조교가 본다
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False         # 언어 모델이 실패해서 키워드 방식으로 대신 처리했으면 True
    fallback_reason: str = ""      # 넘어간 이유: "503 과부하" / "429 요청 제한" / "시간 초과" / "형식 오류" / "키 없음" 등


class MessageInput(BaseModel):
    """write_message·check_message에 넣는 값. 서버가 DB와 배정 결과에서 채운다."""
    professor: str                 # 받는 교수 ("나")
    course: str                    # "객체지향프로그래밍 02"
    term: str = "2027-1학기"
    round: int = Field(ge=1, le=3)
    wish: str                      # 본인 희망 그대로 ("월·수 15:00")
    alternatives: list[Alternative]
    blocker_prof: str | None = None     # 겹친 상대 교수
    blocker_course: str | None = None   # 겹친 상대 강의 ("자료구조 01")
    reveal: bool = True                 # 상대 교수 이름 알리기 (학과 설정)
    prev_conditions: Conditions | None = None   # 지난 차수 답장에서 받은 조건
    hidden: list[str] = []         # 메시지에 나오면 안 되는 글 (상대 교수의 기타 요청 등). 언어 모델에는 주지 않는다


class Message(BaseModel):
    """write_message 결과."""
    text: str
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False
    problems: list[str] = []       # 언어 모델 글이 검사에서 걸린 이유 (fallback일 때)


class PickCheck(BaseModel):
    key: str
    ok: bool
    why: str


class Proposal(BaseModel):
    """match_conditions 결과 = 조교에게 보여 줄 처리안. 조교가 [확인]을 눌러야 실행된다."""
    action: Literal["move", "next", "decide"]   # move = 고른 안으로 옮김, next = 조건 넣어 다음 차수, decide = 조교가 직접
    key: Key | None = None
    conditions: Conditions = Conditions()
    text: str
    checks: list[PickCheck] = []
