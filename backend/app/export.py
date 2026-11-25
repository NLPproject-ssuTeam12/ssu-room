"""확정 시간표 → 엑셀 (백엔드 ③, 김대원).

두 단계로 나눈다. 나중에 DB(하윤 v_schedule)에서 읽도록 바꿀 때는 timetable_rows만 바꾸면 된다.
- timetable_rows: 시간표 + 분반 정보 → 행 목록 (열 이름 COLUMNS)
- write_xlsx: 행 목록 → .xlsx 바이트

SAP 실제 입력 양식은 받지 못했다. 열은 제안 양식이고, 시트 맨 위에 그렇게 적는다.
수업(회차)마다 강의실이 다르면 '요일·시간'과 '강의실'을 같은 순서로 " / "로 이어 짝지어 보인다.
"""

import io
from typing import Dict, Iterable, List

from .contracts import DAYS, Assignment, Section, Timetable, block_room

COLUMNS = ["과목 코드", "과목명", "분반", "교수", "요일·시간", "강의실"]
NOTICE = "가상/가명 데이터, SAP 실제 양식 아님(제안 양식). 교수 이름은 가명이다."
SHEET = "확정 시간표"


def _end(start: str, slots: int) -> str:
    h, m = map(int, start.split(":"))
    e = h * 60 + m + 75 * slots + 15 * (slots - 1)
    return f"{e // 60:02d}:{e % 60:02d}"


def _day_order(day: str) -> int:
    return DAYS.index(day) if day in DAYS else len(DAYS)    # 토요일(MANUAL)은 맨 뒤


def _sorted(blocks):
    return sorted(blocks, key=lambda b: (_day_order(b.day), b.start))


def time_text(blocks) -> str:
    """수업 칸 → "화 10:30~11:45 / 목 10:30~11:45". 칸이 없으면 "미배정"."""
    return " / ".join(f"{b.day} {b.start}~{_end(b.start, b.slots)}" for b in _sorted(blocks)) or "미배정"


def room_text(a: Assignment) -> str:
    """수업마다 같은 강의실이면 하나, 다르면 time_text와 같은 순서로 "문화관 03407 / 정보과학관 21304"."""
    rooms = [block_room(a, b) or "미정" for b in _sorted(a.blocks)]
    if len(set(rooms)) > 1:
        return " / ".join(rooms)
    return rooms[0] if rooms else (a.room or "미정")


def timetable_rows(timetable: Timetable, sections: Iterable[Section]) -> List[Dict[str, str]]:
    """시간표의 분반마다 한 행 (MANUAL 분반 포함). 과목 코드 순."""
    by_id = {s.id: s for s in sections}
    rows = []
    for a in timetable.assignments:
        sec = by_id.get(a.section_id)
        if sec is None:
            continue
        div = (sec.division or "").strip()
        rows.append({
            "과목 코드": sec.code,
            "과목명": sec.name,
            "분반": sec.code[-2:] + (f" {div}" if div else ""),
            "교수": sec.professor or "담당 미정",
            "요일·시간": time_text(a.blocks),
            "강의실": room_text(a),
        })
    rows.sort(key=lambda r: (r["과목 코드"], r["분반"]))
    return rows


def write_xlsx(rows: List[Dict[str, str]]) -> bytes:
    """행 목록 → .xlsx. 1행 = 안내 문구, 2행 = 열 이름, 3행부터 자료."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append([NOTICE])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))
    ws["A1"].font = Font(bold=True, color="C00000")
    ws.append(COLUMNS)
    for c in ws[2]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r[k] for k in COLUMNS])
    for col, width in zip("ABCDEF", (14, 24, 18, 10, 34, 22)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A3"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
