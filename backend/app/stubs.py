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
from typing import Dict, List, Optional, Tuple, Union

from .contracts import (
    DAYS, STARTS, Alternative, Assignment, Block, Conditions, MessageIssue, Proposal,
    ReplyParse, Room, Section, Timetable, Violation, WhatIfResult, Wish, dump, parse,
)

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
    배정 전체 → 하드 규칙 위반 목록. 가짜는 '강의실 겹침'만 본다."""
    out = []
    items = [(a, b) for a in timetable.assignments if a.room for b in a.blocks]
    for i, (a1, b1) in enumerate(items):
        for a2, b2 in items[i + 1:]:
            if a1.section_id != a2.section_id and a1.room == a2.room and _overlap(b1, b2):
                out.append(Violation(
                    rule="강의실 겹침",
                    section_ids=[a1.section_id, a2.section_id],
                    detail=f"{a1.room} {_block_text(b1)} / {_block_text(b2)}",
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
                    busy.setdefault((a.room, c), a.section_id)
        picked = {sid for sid, _ in candidates}
        for a in tt.assignments:
            if len(candidates) >= 3:
                break
            s, w = sec.get(a.section_id), wish.get(a.section_id)
            if not s or not w or s.shape == "MANUAL" or a.section_id in picked:
                continue
            used = {c for b in a.blocks for c in _cells(b)}
            for c, v in sorted(w.cells.items()):
                other = busy.get((a.room, c))
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
        out.append(Block(day=b.day, start=STARTS[j], slots=b.slots))
    return out


def _move_day(blocks: List[Block], step: int) -> List[Block]:
    return [Block(day=DAYS[(DAYS.index(b.day) + step) % 5], start=b.start, slots=b.slots) for b in blocks]


def _fits(blocks: List[Block], cond: Optional[Conditions]) -> Tuple[bool, str]:
    if cond is None:
        return True, ""
    for b in blocks:
        s, e = _block_range(b)
        if cond.days and b.day not in cond.days:
            return False, f"{b.day}요일은 가능한 요일이 아님"
        limit = cond.end_before.get(b.day)
        if limit and e > _to_min(limit):
            return False, f"{_block_text(b)} 종료라 '{b.day} {limit} 전 종료'와 안 맞음"
        if cond.time_ranges and not any(_to_min(r.start) <= s and e <= _to_min(r.end) for r in cond.time_ranges):
            return False, f"{_block_text(b)}가 가능한 시간대 밖"
    return True, ""


def make_alternatives(section_id: str, conditions: Optional[Conditions] = None) -> List[Alternative]:
    """STUB: 담당 문하윤
    밀린 분반 (+ 조건) → 대안 A·B·C.
    가짜: 초안 자리에서 같은 강의실로 한 칸·두 칸 뒤, 같은 시간 다른 강의실 순으로 만들고
    조건이 있으면 맞는 것만 남긴다. 초안에서 같은 강의실을 쓰는 다른 분반과 겹치는 자리는 뺀다
    (교수·학년 겹침은 보지 않는다)."""
    d = _data()
    cur = next((a for a in d["timetable"].assignments if a.section_id == section_id), None)
    if cur is None or not cur.blocks:
        return []
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

    add(_shift(cur.blocks, 1), [cur.room])
    add(_shift(cur.blocks, 2), [cur.room])
    add(cur.blocks, other_ids)
    for step in (-1, -2, 3, 4):
        add(_shift(cur.blocks, step), [cur.room])
    for step in (1, 2, -1, -2):
        add(_shift(cur.blocks, step), other_ids)
    for dstep in (1, 2, 3, 4):
        for step in (0, 1, -1):
            add(_shift(_move_day(cur.blocks, dstep), step), [cur.room] + other_ids)

    def room_busy(blocks: List[Block], room: Optional[str]) -> bool:
        return any(a.section_id != section_id and a.room == room and _overlap(b, x)
                   for a in d["timetable"].assignments for b in a.blocks for x in blocks)

    out, seen = [], set()
    for blocks, room in cands:
        key = (tuple((b.day, b.start, b.slots) for b in blocks), room)
        if key in seen or not _fits(blocks, conditions)[0] or room_busy(blocks, room):
            continue
        seen.add(key)
        out.append(Alternative(label="ABC"[len(out)], blocks=blocks, room=room))
        if len(out) == 3:
            break
    return out


def reassign(timetable: Timetable, section_id: str, choice: Union[Alternative, Conditions]) -> Timetable:
    """STUB: 담당 문하윤
    현재 배정 + 고른 안 또는 조건 → 새 배정. 가짜: 그 분반 하나만 바꾼다."""
    tt = parse(Timetable, dump(timetable))
    if isinstance(choice, Conditions):
        alts = make_alternatives(section_id, choice)
        if not alts:
            return tt
        choice = alts[0]
    for a in tt.assignments:
        if a.section_id == section_id:
            a.blocks, a.room, a.status, a.reason = list(choice.blocks), choice.room, "DONE", None
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
        changed = [a.section_id for a in tt.assignments if a.room == change.get("room")]
    elif kind == "free":
        probe = Block(day=change["day"], start=change["start"], slots=1)
        changed = [a.section_id for a in tt.assignments if any(_overlap(b, probe) for b in a.blocks)]
    else:
        sid = change.get("section_id")
        target = next((a for a in tt.assignments if a.section_id == sid), None)
        if target is not None and target.blocks:
            first = target.blocks[0]
            target.blocks[0] = Block(day=change.get("day", first.day), start=change.get("start", first.start),
                                     slots=first.slots)
            if change.get("room"):
                target.room = change["room"]
            changed = [sid] + [a.section_id for a in tt.assignments
                               if a.section_id != sid and a.room == target.room
                               and any(_overlap(b, target.blocks[0]) for b in a.blocks)]
    return dump(WhatIfResult(changed=changed, violations=len(check_rules(tt))))


# ---------- 조율 NLP (최재성) ----------

def write_message(section: Section, wish: Optional[Wish], alternatives: List[Alternative], round_no: int,
                  conflict: Optional[str] = None, method: str = "keyword") -> str:
    """STUB: 담당 최재성
    밀린 분반, 겹친 사정, 본인 희망, 대안, 차수 → 교수에게 보낼 글.
    가짜: 정해진 틀에 값만 채운다. 연차·상대 교수 이름은 넣지 않는다."""
    prefer = sorted(c for c, v in (wish.cells if wish else {}).items() if v == "PREFER")
    div = f" {section.division}" if section.division else ""
    lines = [
        "교수님, 안녕하세요. 학과사무실입니다.",
        f"[{round_no}차 조율] {section.name}{div} 분반의 희망 시간이 다른 강의와 겹쳐 아래 대안을 드립니다.",
        f"- 적어 주신 희망: {', '.join(prefer) if prefer else '(없음)'}",
    ]
    if conflict:
        lines.append(f"- 겹친 사정: {conflict}")
    for alt in alternatives:
        lines.append(f"- {alt.label}안: {' / '.join(_block_text(b) for b in alt.blocks)} · {alt.room or '강의실 미정'}")
    lines.append("괜찮은 안을 골라 주시거나, 안 되는 요일·시간을 알려 주세요. 회신 기한은 1주입니다.")
    return "\n".join(lines)


_FORBIDDEN = ("연차", "선임", "후임", "우선순위", "임용")


def check_message(text: str) -> List[MessageIssue]:
    """STUB: 담당 최재성
    작성한 글 → 문제 목록. 가짜: 금지 단어와 'A안' 유무만 본다."""
    issues = [MessageIssue(kind="금지 내용", detail=f"'{w}' 이(가) 들어 있음") for w in _FORBIDDEN if w in text]
    if "희망" not in text:
        issues.append(MessageIssue(kind="필수 내용 빠짐", detail="본인 희망이 없음"))
    if "A안" not in text:
        issues.append(MessageIssue(kind="필수 내용 빠짐", detail="대안이 없음"))
    return issues


def parse_reply(text: str, method: str = "keyword") -> ReplyParse:
    """STUB: 담당 최재성
    교수 답장 → ReplyParse. 가짜: method와 상관없이 간단한 키워드로 읽는다.
    애매하면 '확인필요'."""
    t = text.strip()
    if not t:
        return ReplyParse(decision="확인필요")
    chosen = sorted(set(re.findall(r"([ABC])\s*(?=안|나|도|,|이|랑|와|과|\s|$)", t)))
    end_before: Dict[str, str] = {}
    for day, hour in re.findall(r"(월|화|수|목|금)요일?은?\s*(\d{1,2})\s*시\s*(?:전|까지|이전)", t):
        end_before[day] = f"{int(hour):02d}:00"
    cond = Conditions(end_before=end_before)
    if re.search(r"안\s*돼|안\s*됩|어렵|불가|힘들", t) and not chosen:
        return ReplyParse(decision="거절", conditions=cond)
    if chosen and end_before:
        return ReplyParse(decision="조건부", chosen=chosen, conditions=cond)
    if chosen:
        return ReplyParse(decision="수용", chosen=chosen)
    return ReplyParse(decision="확인필요", conditions=cond)


def match_conditions(parse_result: ReplyParse, alternatives: List[Alternative]) -> Proposal:
    """STUB: 담당 최재성
    ReplyParse + 대안 → 처리안. 가짜: 고른 안을 순서대로 조건에 대 보고 처음 맞는 안을 고른다."""
    if parse_result.decision == "거절":
        return Proposal(action="ASK", summary="거절: 다음 차수에 새 대안이 필요합니다.")
    if parse_result.decision == "확인필요":
        return Proposal(action="ASK", summary="답장을 확실히 읽지 못했습니다. 조교가 직접 확인해 주세요.")
    pool = [a for a in alternatives if not parse_result.chosen or a.label in parse_result.chosen]
    rejected = []
    for alt in pool:
        ok, why = _fits(alt.blocks, parse_result.conditions)
        if ok:
            head = f"{', '.join(rejected)} → " if rejected else ""
            return Proposal(action="MOVE", alternative=alt, rejected=rejected,
                            summary=f"{head}{alt.label}안으로 옮길까요?")
        rejected.append(f"{alt.label}안은 {why}")
    return Proposal(action="ASK", rejected=rejected,
                    summary="고른 안이 모두 조건과 안 맞습니다. 조건으로 새 대안을 찾을까요?")
