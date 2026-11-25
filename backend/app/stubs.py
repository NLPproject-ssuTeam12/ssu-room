"""가짜 배정·조율 함수. 이름과 입출력은 구현 계획서 4절과 같다.

진짜 함수가 backend/app/solver/ 또는 backend/app/nlp/coord.py 에 생기면
engine.py가 자동으로 그쪽을 쓴다. 이 파일은 그때까지 서버와 화면을 돌리기 위한 것이다.
여기 값은 계산 결과가 아니다(시연·연결 확인용).
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from .contracts import (
    DAYN, DAYS, STARTS, Alternative, Assignment, Block, Conditions, EndBefore, Message, MessageInput,
    PickCheck, Proposal, ReplyParse, Room, Section, Timetable, Violation, WhatIfResult, Wish,
    alternative, as_day_slots, block_room, dump, late_penalty, meetings_to_blocks, no_long_at_1800, parse,
    set_place, set_room,
)

Method = Literal["keyword", "llm"]

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- 공용 도우미 (가짜 함수 안에서만 씀) ----------

def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _block_range(b: Block) -> Tuple[int, int]:
    """칸 1개 = 75분, 칸 사이 쉬는 시간 15분. 2칸 = 165분."""
    s = _to_min(b.start)
    return s, s + 75 * b.slots + 15 * (b.slots - 1)


def _block_text(b: Block) -> str:
    s, e = _block_range(b)
    return f"{b.day} {b.start}~{_to_hhmm(e)}"


def _overlap(a: Block, b: Block) -> bool:
    if a.day != b.day:
        return False
    a0, a1 = _block_range(a)
    b0, b1 = _block_range(b)
    return a0 < b1 and b0 < a1


def _cells(b: Block) -> List[str]:
    """블록이 차지하는 희망 칸 이름. 8칸 밖 시각이면 빈 목록."""
    if b.start not in STARTS:
        return []
    i = STARTS.index(b.start)
    return [f"{b.day}-{STARTS[j]}" for j in range(i, min(i + b.slots, len(STARTS)))]


@lru_cache(maxsize=1)
def _data() -> dict:
    """가짜 값을 그럴듯하게 만들려고 실제 데이터 묶음을 읽는다."""
    folder = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")

    def load(name):
        with (folder / name).open(encoding="utf-8") as f:
            return json.load(f)

    return {
        "timetable": parse(Timetable, load("timetable.json")),
        "rooms": [parse(Room, r) for r in load("rooms.json")],
        "sections": {s["id"]: s for s in load("sections.json")},
    }


# ---------- 배정 엔진 (문하윤) ----------

def check_rules(timetable: Timetable) -> List[Violation]:
    """STUB: 담당 문하윤
    배정 전체 → 하드 규칙 위반 목록. 가짜는 '강의실 겹침'만 본다 (수업마다 그 수업의 강의실로)."""
    out = []
    items = [(a, b, block_room(a, b)) for a in timetable.assignments for b in a.blocks]
    items = [x for x in items if x[2]]
    for i, (a1, b1, r1) in enumerate(items):
        for a2, b2, r2 in items[i + 1:]:
            if a1.section_id != a2.section_id and r1 == r2 and _overlap(b1, b2):
                out.append(Violation(
                    rule="강의실 겹침",
                    section_ids=[a1.section_id, a2.section_id],
                    detail=f"{r1} {_block_text(b1)} / {_block_text(b2)}",
                ))
    return out


def make_draft(sections: List[Section], wishes: List[Wish], rooms: List[Room]) -> Tuple[Timetable, List[str]]:
    """STUB: 담당 문하윤
    분반·희망·강의실 → (초안 시간표, 밀린 분반 id 목록).
    가짜: timetable.json을 그대로 쓰고, MANUAL 분반은 MANUAL로 둔다.
    희망 칸 밖에 놓인 분반을 앞에서 3개 COORD로 둔다. 3개가 안 되면
    '희망 칸을 다른 분반이 같은 강의실에서 쓰는' 분반으로 채운다(시연용 가정)."""
    tt = parse(Timetable, dump(_data()["timetable"]))
    tt.status = "DRAFT"
    sec = {s.id: s for s in sections}
    wish = {w.section_id: w for w in wishes}

    candidates: List[Tuple[str, str]] = []
    for a in tt.assignments:
        s = sec.get(a.section_id)
        if s is None:
            continue
        if s.shape == "MANUAL":
            a.status, a.reason = "MANUAL", "조교 직접 배정 분반 (수업 모양이 주 2회·주 1회 연강이 아님)"
            continue
        w = wish.get(a.section_id)
        if w is None:
            continue
        outside = [c for b in a.blocks for c in _cells(b) if w.cells.get(c) != "PREFER"]
        if outside:
            candidates.append((a.section_id, f"희망 칸 밖에 배정됨: {', '.join(outside)}"))

    if len(candidates) < 3:
        # 대체: 희망했지만 못 받은 칸을 같은 강의실의 다른 분반이 쓰고 있는 경우
        busy = {}
        for a in tt.assignments:
            for b in a.blocks:
                for c in _cells(b):
                    busy.setdefault((block_room(a, b), c), a.section_id)
        picked = {sid for sid, _ in candidates}
        for a in tt.assignments:
            if len(candidates) >= 3:
                break
            s, w = sec.get(a.section_id), wish.get(a.section_id)
            if not s or not w or s.shape == "MANUAL" or a.section_id in picked:
                continue
            used = {c for b in a.blocks for c in _cells(b)}
            for c, v in sorted(w.cells.items()):
                other = busy.get((a.room, c))   # 대표 강의실 기준 (가짜 값)
                if v == "PREFER" and c not in used and other and other != a.section_id:
                    other_name = sec[other].name if other in sec else other
                    candidates.append((a.section_id,
                                       f"희망 칸 {c}의 {a.room}을(를) '{other_name}' 분반이 쓰고 있음 (가짜 값)"))
                    break

    delayed = []
    by_id = {a.section_id: a for a in tt.assignments}
    for sid, reason in candidates[:3]:
        by_id[sid].status, by_id[sid].reason = "COORD", reason
        delayed.append(sid)
    return tt, delayed


def _shift(blocks: List[Block], step: int) -> Optional[List[Block]]:
    out = []
    for b in blocks:
        if b.start not in STARTS:
            return None
        j = STARTS.index(b.start) + step
        if j < 0 or j + b.slots > len(STARTS):
            return None
        out.append(Block(day=b.day, start=STARTS[j], slots=b.slots, room=b.room))
    return out


def _move_day(blocks: List[Block], step: int) -> List[Block]:
    moved = [Block(day=DAYS[(DAYS.index(b.day) + step) % 5], start=b.start, slots=b.slots, room=b.room)
             for b in blocks]
    return sorted(moved, key=lambda b: DAYS.index(b.day))   # 요일 순 (월→금)


def _fits(blocks: List[Block], cond: Optional[Conditions]) -> Tuple[bool, str]:
    """조건 읽는 법은 coord_models.Conditions 주석과 같다 (요일별 교시 day_slots, 11/22).
    day_slots가 비면 요일·교시 제한 없음. 요일 키가 둘 이상 = 그 요일들 안에서만(키 없는 요일 불가),
    하나 = 그 요일이 들어가기만 하면 됨(주 2회의 다른 하루는 자유).
    그 요일 목록이 비면 아무 교시나, 있으면 그 교시만 (연강이면 두 교시 모두 들어 있어야 함).
    end_before: 요일별 종료 시각. 옛 모양(days·slots) 조건도 받는다."""
    if cond is None:
        return True, ""
    cond = as_day_slots(cond)
    ds = cond.day_slots
    for b in blocks:
        _, e = _block_range(b)
        for eb in cond.end_before:
            if DAYS.index(b.day) == eb.day and e > _to_min(eb.time):
                return False, f"{_block_text(b)} 종료라 '{b.day} {eb.time} 전 종료'와 안 맞음"
    if not ds:
        return True, ""
    days = [DAYS.index(b.day) for b in blocks]
    if len(ds) >= 2:
        ok, checked = all(d in ds for d in days), blocks
    else:
        (d0,) = ds
        ok, checked = d0 in days, [b for b in blocks if DAYS.index(b.day) == d0]
    if not ok:
        return False, "가능한 요일이 아님"
    for b in checked:
        allowed = ds[DAYS.index(b.day)]
        if allowed and not all(st in allowed for st in _slot_starts(b)):
            return False, f"{_block_text(b)}가 가능한 교시 밖"
    return True, ""


def _slot_starts(b: Block) -> List[str]:
    """블록이 차지하는 교시 시작 시각. 연강(2칸)이면 두 교시. 8교시 밖 시각이면 [b.start] (어느 slots에도 없음)."""
    if b.start not in STARTS:
        return [b.start]
    i = STARTS.index(b.start)
    return list(STARTS[i:i + b.slots]) if i + b.slots <= len(STARTS) else [b.start, "?"]


def make_alternatives(section_id: str, conditions: Optional[Conditions] = None) -> List[Alternative]:
    """STUB: 담당 문하윤
    밀린 분반 (+ 조건) → 대안 A·B·C.
    가짜: 초안 자리에서 같은 강의실(수업마다 지금 강의실)로 한 칸·두 칸 뒤, 같은 시간 다른 강의실 순으로 만들고
    조건이 있으면 맞는 것만 남긴다. 초안에서 같은 강의실을 쓰는 다른 분반과 겹치는 자리는 뺀다
    (교수·학년 겹침은 보지 않는다).
    시간 규칙: 18:00 시작 연강은 만들지 않는다(하드). 19:30 교시는 감점(late_penalty)이라
    19:30을 안 쓰는 안을 먼저 고르고, 모자랄 때만 19:30 안을 넣는다."""
    d = _data()
    cur = next((a for a in d["timetable"].assignments if a.section_id == section_id), None)
    if cur is None or not cur.blocks or any(b.day not in DAYS for b in cur.blocks):
        return []   # 토요일 등 MANUAL 분반은 자동 대안 대상이 아니다
    sec = d["sections"].get(section_id, {})
    need_lab = sec.get("lab_need") == "MUST"
    size = sec.get("enrollment") or 0
    cur_room = next((r for r in d["rooms"] if r.id == cur.room), None)
    other_rooms = [r for r in d["rooms"] if r.id != cur.room and (r.is_lab or not need_lab)
                   and (r.capacity is None or r.capacity >= size)]
    if cur_room:
        other_rooms.sort(key=lambda r: (r.building != cur_room.building, r.id))
    other_ids = [r.id for r in other_rooms]

    # 순서: 같은 강의실 한 칸 뒤 → 두 칸 뒤 → 같은 시간 다른 강의실 → 점점 넓게
    cands: List[Tuple[List[Block], Optional[str]]] = []

    def add(blocks, rooms):
        if blocks:
            cands.extend((blocks, r) for r in rooms)

    same = [None]   # None = 수업마다 지금 강의실 그대로 (Block.room)
    add(_shift(cur.blocks, 1), same)
    add(_shift(cur.blocks, 2), same)
    add(cur.blocks, other_ids)
    for step in (-1, -2, 3, 4):
        add(_shift(cur.blocks, step), same)
    for step in (1, 2, -1, -2):
        add(_shift(cur.blocks, step), other_ids)
    for dstep in (1, 2, 3, 4):
        for step in (0, 1, -1):
            add(_shift(_move_day(cur.blocks, dstep), step), same + other_ids)

    def room_busy(blocks: List[Block], room: Optional[str]) -> bool:
        return any(a.section_id != section_id and block_room(a, b) == (room or x.room) and _overlap(b, x)
                   for a in d["timetable"].assignments for b in a.blocks for x in blocks)

    ok, seen = [], set()
    for blocks, room in cands:
        key = (tuple((b.day, b.start, b.slots, room or b.room) for b in blocks),)
        if key in seen or not no_long_at_1800(blocks):
            continue
        if not _fits(blocks, conditions)[0] or room_busy(blocks, room):
            continue
        seen.add(key)
        ok.append((blocks, room))
    # 감점이 적은 순 (같으면 원래 순서). 19:30 안은 다른 안이 3개가 안 될 때만 들어간다
    ok.sort(key=lambda br: late_penalty(br[0]))
    return [alternative("ABC"[i], blocks, room) for i, (blocks, room) in enumerate(ok[:3])]


def reassign(timetable: Timetable, section_id: str, choice: Union[Alternative, Conditions]) -> Timetable:
    """STUB: 담당 문하윤
    현재 배정 + 고른 안 또는 조건 → 새 배정. 가짜: 그 분반 하나만 바꾼다."""
    tt = parse(Timetable, dump(timetable))
    if not isinstance(choice, Alternative):   # 조건 (옛 모양·새 모양 모두)
        alts = make_alternatives(section_id, choice)
        if not alts:
            return tt
        choice = alts[0]
    blocks, _ = meetings_to_blocks(choice.meetings)
    for a in tt.assignments:
        if a.section_id == section_id:
            set_place(a, blocks)   # 수업마다 강의실 유지
            a.status, a.reason = "DONE", None
    return tt


def what_if(timetable: Timetable, change: dict) -> dict:
    """STUB: 담당 문하윤
    현재 배정 + 바꿔 볼 것 → {changed: [분반 id...], violations: int}. 반영은 안 한다.
    change 모양 (셋 중 하나):
      {"kind": "move", "section_id": ..., "day": "수", "start": "15:00", "room": 선택}
      {"kind": "free", "day": "수", "start": "15:00"}      # 그 시간 비우기
      {"kind": "room_off", "room": "정보과학관 21303"}      # 그 강의실 못 씀
    가짜: 직접 부딪히는 분반만 세고, 위반 수는 강의실 겹침만 센다."""
    tt = parse(Timetable, dump(timetable))
    kind = change.get("kind", "move")
    changed: List[str] = []
    if kind == "room_off":
        changed = [a.section_id for a in tt.assignments
                   if any(block_room(a, b) == change.get("room") for b in a.blocks)]
    elif kind == "free":
        probe = Block(day=change["day"], start=change["start"], slots=1)
        changed = [a.section_id for a in tt.assignments if any(_overlap(b, probe) for b in a.blocks)]
    else:
        sid = change.get("section_id")
        target = next((a for a in tt.assignments if a.section_id == sid), None)
        if target is not None and target.blocks:
            first = target.blocks[0]
            target.blocks[0] = Block(day=change.get("day", first.day), start=change.get("start", first.start),
                                     slots=first.slots, room=first.room)
            if change.get("room"):
                set_room(target, change["room"])
            moved = target.blocks[0]
            changed = [sid] + [a.section_id for a in tt.assignments
                               if a.section_id != sid
                               and any(block_room(a, b) == block_room(target, moved) and _overlap(b, moved)
                                       for b in a.blocks)]
    return dump(WhatIfResult(changed=changed, violations=len(check_rules(tt))))


# ---------- 조율 NLP (최재성) ----------
# 시그니처(인자 이름·순서·키워드 전용·기본값)는 backend/app/nlp/coord.py와 똑같이 둔다.
# engine.py가 inspect.signature로 비교해서 다르면 경고하고 가짜를 쓴다.

def _alt_text(a: Alternative) -> str:
    when = " / ".join(f"{DAYN[m.day]} {m.start}~{m.end}" for m in a.meetings)
    rooms = sorted({m.room for m in a.meetings})
    return f"{when} · {' / '.join(rooms)}"


def write_message(inp: MessageInput, method: Method = "keyword") -> Message:
    """STUB: 담당 최재성
    MessageInput → 교수에게 보낼 글. 가짜: 정해진 틀에 값만 채운다 (method와 상관없이 틀).
    상대 교수 이름은 reveal=True일 때만 쓴다. 연차·우선순위는 쓰지 않는다."""
    other = (f"{inp.blocker_prof} 교수님의 {inp.blocker_course} 분반과"
             if inp.reveal and inp.blocker_prof and inp.blocker_course else "다른 강의와")
    lines = [f"{inp.professor} 교수님, 안녕하세요. 학과사무실입니다.",
             f"{inp.term} {inp.course} 분반 시간표 {inp.round}차 조율 안내드립니다. (가짜 메시지)", "",
             f"희망하신 시간({inp.wish})이 {other} 겹칩니다.", ""]
    lines += [f"{a.key}  {_alt_text(a)}" for a in inp.alternatives]
    lines += ["", "가능한 안을 골라 주시거나, 모두 어려우시면 가능한 시간을 적어 주세요. 회신 기한은 1주입니다."]
    return Message(text="\n".join(lines), method="keyword")


_FORBIDDEN = ("연차", "임용", "우선순위", "경력")


def check_message(text: str, inp: MessageInput) -> List[str]:
    """STUB: 담당 최재성
    글 + MessageInput → 걸린 문제 목록 (빈 목록 = 보내도 됨). 가짜: 금지 단어, 숨길 글, 과목·희망·대안만 본다."""
    p = [f"연차·우선순위 이유를 썼음 ('{w}')" for w in _FORBIDDEN if w in text]
    p += ["상대 교수의 사정(기타 요청)을 썼음" for h in inp.hidden if h.strip() and h.strip() in text]
    if not inp.reveal and inp.blocker_prof and f"{inp.blocker_prof} 교수" in text:
        p.append("상대 교수 이름을 썼음 (학과 설정: 알리지 않음)")
    if inp.course not in text:
        p.append("과목·분반 이름이 빠짐")
    if inp.wish not in text:
        p.append("본인 희망 시간이 빠지거나 바뀜")
    if not inp.alternatives:
        p.append("대안이 없음")
    return p


def parse_reply(text: str, choice: Optional[str] = None, *, choices: Optional[List[str]] = None,
                alternatives: Optional[List[Alternative]] = None, message: str = "",
                method: Method = "keyword", can_keep: bool = False) -> ReplyParse:
    """STUB: 담당 최재성
    교수 답장 + 누른 값 → ReplyParse. 가짜: method와 상관없이 간단한 키워드로 읽는다. 애매하면 '확인 필요'.
    choices = 'A'·'B'·'C'·'ETC'·'KEEP' 중 하나 이상(여러 개). 없으면 예전 choice('A'/'B'/'C'/'none'/None).
    KEEP을 누르거나 can_keep이고 글이 '지금 그대로'면 keep."""
    t = (text or "").strip()
    cond = Conditions(end_before=[
        EndBefore(day=DAYN.index(d), time=f"{(int(h) + 12 if int(h) < 8 else int(h)):02d}:00")
        for d, h in re.findall(r"([월화수목금])요?일?[은는]?\s*(\d{1,2})시\s*(?:전|이전|까지)", t)])
    if choices is not None:
        if "KEEP" in choices:
            return ReplyParse(kind="수용", keep=True, conditions=cond)
        btn = [c for c in ("A", "B", "C") if c in choices]
        none = not btn
    else:
        btn = [choice] if choice in ("A", "B", "C") else []
        none = choice == "none"
    text_picks = list(dict.fromkeys(re.findall(r"(?<![A-Za-z])([ABC])(?![A-Za-z])", t)))
    if btn:
        ordered = [x for x in text_picks if x in btn]
        picks = ordered + [x for x in btn if x not in ordered]
    else:
        picks = [] if none else text_picks
    if can_keep and not picks and re.search(r"지금\s*(자리\s*)?그대로", t):
        return ReplyParse(kind="수용", keep=True, conditions=cond)
    if picks:
        return ReplyParse(kind="조건부" if not cond.is_empty() else "수용", picks=picks,
                          ordered=len(picks) > 1 and len([x for x in text_picks if x in picks]) > 1,
                          conditions=cond)
    if none and not cond.is_empty():
        return ReplyParse(kind="조건부", conditions=cond)
    if none or re.search(r"안\s*[돼되]|어렵|불가|힘들", t):
        return ReplyParse(kind="거절", conditions=cond)
    return ReplyParse(kind="확인 필요", conditions=cond)


def match_conditions(parse: ReplyParse, alternatives: List[Alternative], round: int,
                     unavailable: List[str] = ()) -> Proposal:
    """STUB: 담당 최재성
    ReplyParse + 대안 + 차수 (+ 못 쓰게 된 안) → 처리안. 가짜: 고른 안을 순서대로 조건에 대 보고 처음 맞는 안.
    지금 자리 그대로(keep)면 keep, 고른 안도 조건도 없으면 [따로 연락]을 권하는 decide (진짜와 같은 규칙)."""
    if getattr(parse, "keep", False):
        return Proposal(action="keep", text="교수님이 지금 자리를 그대로 원합니다. [현재대로 유지]를 누르면 끝납니다.")
    if parse.kind == "확인 필요":
        return Proposal(action="decide", text="답장을 확실히 읽지 못했습니다. [수정]으로 정하거나 [따로 연락]해 주세요.")
    if not parse.picks and parse.conditions.is_empty():
        return Proposal(action="decide", text="되는 시간을 말하지 않고 거절했습니다. 교수님과 [따로 연락]해 정해 주세요.")
    checks = []
    for key in parse.picks:
        a = next((x for x in alternatives if x.key == key), None)
        if a is None:
            checks.append(PickCheck(key=key, ok=False, why="없는 안"))
            continue
        ok, why = _fits(meetings_to_blocks(a.meetings)[0], parse.conditions)
        if ok and key in unavailable:
            ok, why = False, "그사이 다른 강의가 들어감"
        checks.append(PickCheck(key=key, ok=ok, why=why or "조건과 맞음"))
        if ok:
            return Proposal(action="move", key=key, conditions=parse.conditions, checks=checks,
                            text=f"{key}안({_alt_text(a)})으로 옮길까요?")
    if round >= 3:
        return Proposal(action="decide", conditions=parse.conditions, checks=checks,
                        text="3차라 더 묻지 않습니다. [수정]이나 [현재대로 유지]로 정해 주세요.")
    return Proposal(action="next", conditions=parse.conditions, checks=checks,
                    text="맞는 안이 없습니다. 조건을 넣어 다음 차수 대안을 만들까요?")
