"""조율 NLP가 주고받는 데이터 모양.

공용 `schemas.py`가 생기면 그쪽으로 옮긴다.
`Conditions`는 배정 엔진(백엔드 1)이 읽는 모양이라 하윤과 맞춰야 하는 임시안이다 (11/21 기준).
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    """교수 답장에서 뽑은 조건. 다음 차수 대안을 만들 때 배정 엔진이 읽는다."""
    days: list[int] = []           # 둘 이상 = 그 요일 안에서만, 하나 = 그 요일을 포함
    slots: list[str] = []          # 되는 교시(시작 시각). 비면 제한 없음. 연강은 두 칸 모두 들어 있어야 맞음
    end_before: list[EndBefore] = []

    @field_validator("slots")
    @classmethod
    def _known_slots(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in SLOTS]
        if bad:
            raise ValueError(f"교시 시작 시각이 아님: {bad}")
        return sorted(set(v), key=SLOTS.index)

    def is_empty(self) -> bool:
        return not self.days and not self.slots and not self.end_before


class ReplyParse(BaseModel):
    """parse_reply 결과."""
    kind: Kind
    picks: list[Key] = []          # 고른 안, 선호 순서
    conditions: Conditions = Conditions()
    note: str = ""                 # 조교가 확인하거나 바꿔야 할 요청 (강의실 변경·장비·정원·교시 조정 희망). 배정 엔진은 읽지 않고 조교가 본다
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False         # 언어 모델이 실패해서 키워드 방식으로 대신 처리했으면 True


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
