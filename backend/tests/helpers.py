"""DB 모드 테스트 공용 도우미 (test_what_if.py·test_db_mode.py).
CP-SAT가 점수가 같은 다른 초안을 고를 수 있어서, 테스트가 칸·강의실을 고정하지 않고 지금 시간표(store.timetable)에서
그때그때 빈 강의실·담당 교수가 빈 시각을 찾는다 (강의실 겹침·교수 겹침으로 먼저 걸리지 않게)."""

from backend.app.nlp import assistant
from backend.app.store import store

DAYN = "월화수목금"
END = {"09:00": "10:15", "10:30": "11:45", "12:00": "13:15", "13:30": "14:45", "15:00": "16:15", "16:30": "17:45"}


def free_room(cells, skip=None):
    """지금 초안(store.timetable)에서 그 칸들(["월-16:30", ...])에 아무 수업도 없는 강의실 하나.
    CP-SAT가 점수가 같은 다른 초안을 고를 수 있어서 강의실을 고정하지 않고 그때그때 찾는다 (강의실 겹침을 피함)."""
    busy = {(blk.room, c) for a in store.timetable.assignments if a.section_id != skip
            for blk in a.blocks for c in assistant._cells(blk)}
    room = next((r.id for r in store.list_rooms() if not r.is_lab and all((r.id, c) not in busy for c in cells)),
                None)
    assert room, f"그 칸에 빈 강의실이 없음: {cells}"
    return room


def prof_busy(sid):
    """그 분반 담당 교수의 다른 분반이 지금 초안에서 쓰는 칸 (옮길 시각이 교수 겹침을 만들지 않게)."""
    prof = store.get_section(sid).professor
    return {c for a in store.timetable.assignments if a.section_id != sid
            and store.get_section(a.section_id) and store.get_section(a.section_id).professor == prof
            for blk in a.blocks for c in assistant._cells(blk)}


def move_blocks(sid):
    """옮겨 볼 자리: 담당 교수가 비어 있고 빈 강의실이 있는 월·수 또는 화·목 한 교시 (초안마다 다를 수 있어서 찾는다)."""
    busy = prof_busy(sid)
    for days in (("월", "수"), ("화", "목")):
        for start in ("16:30", "15:00", "13:30", "12:00", "10:30"):
            cells = [f"{d}-{start}" for d in days]
            if any(c in busy for c in cells):
                continue
            try:
                room = free_room(cells, skip=sid)
            except AssertionError:
                continue
            return [{"day": d, "start": start, "slots": 1, "room": room} for d in days], room
    raise AssertionError(f"{sid}를 옮겨 볼 빈 자리가 없음")


def free_meetings(sid):
    """그 분반을 직접 놓을(수동 배치) 빈 자리 → POST /coord/{id}/manual 의 meetings 모양."""
    blocks, _ = move_blocks(sid)
    return [{"day": DAYN.index(b["day"]), "start": b["start"], "end": END[b["start"]], "room": b["room"]} for b in blocks]
