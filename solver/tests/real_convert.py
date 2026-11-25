"""실제 개설 강좌 표(엑셀) → 엔진 입력용 분반 목록(CSV)으로 바꾼다. 결과 파일은 커밋하지 않는다(data/private/).

  python solver/tests/real_convert.py "엑셀 경로" data/private/real/2026-2_sections.csv

- 이미 배정이 끝난 표라서 "과목마다, 교수마다 분반이 몇 개, 분반마다 인원·실제 시간·강의실" 모양으로 바꾼다.
- 과목번호·수강유의사항·여석·공학인증·다전공 이수구분 등 엔진이 쓰지 않는 칸은 버린다.
- 교수 이름은 P01, P02 … 가명으로 바꾸고 실명·대응표는 어디에도 남기지 않는다.
- 분반 번호 = 과목번호 끝 두 자리. 같은 과목 안에서 1부터 다시 매긴다(엔진은 1부터 빈틈없는 번호를 받는다).
- 학년: 수강대상의 'N학년'(여럿이면 가장 낮은 학년), 없으면 빈칸.
- 시간: '요일들 시작-끝 (건물 호수…)' 줄을 읽어 (요일, 시작, 칸 수)로. 75분 = 1칸, 165분 = 2칸(연강). 그 밖(50분 실습 등)은 격자 밖으로 표시.
  토요일·시간 없는 강좌는 뺀다.
"""
import csv
import pathlib
import re
import sys
from collections import OrderedDict

from openpyxl import load_workbook

GRID = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30"]
LINE = re.compile(r"^([월화수목금토](?: [월화수목금토])*) (\d\d:\d\d)-(\d\d:\d\d)\s*\((\S+)\s+(\d{5})?")
CAT = {"전필": "전공필수", "전선": "전공선택", "전기": "전공기초"}
COLS = ["course", "category", "year", "section", "professor", "enrollment", "times", "room", "room_lab", "in_grid"]


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def main(src, out):
    ws = load_workbook(src, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = {h: i for i, h in enumerate(rows[0])}
    g = lambda r, k: r[head[k]]
    alias = OrderedDict()                       # 실명 → 가명 (메모리에만)
    items, skipped = [], {"시간 없음": 0, "토요일": 0}
    for r in rows[1:]:
        lines = [l.strip() for l in str(g(r, "강의시간(강의실)") or "").split("\n") if l.strip()]
        if not lines:
            skipped["시간 없음"] += 1
            continue
        parsed = [LINE.match(l) for l in lines]
        if any(m and "토" in m.group(1) for m in parsed):
            skipped["토요일"] += 1
            continue
        times, rooms, in_grid = [], [], True
        for m, l in zip(parsed, lines):
            if not m:
                in_grid = False
                continue
            st, en = m.group(2), m.group(3)
            dur = mins(en) - mins(st)
            k = {75: 1, 165: 2}.get(dur)
            if st not in GRID or k is None:
                in_grid = False
            for d in m.group(1).split():
                times.append(f"{d} {st} {k or 0}")
            if m.group(5):
                rooms.append((f"{m.group(4)} {m.group(5)}", "실습실" in l))
        prof = str(g(r, "교수명") or "").strip() or "(미정)"
        if prof not in alias:
            alias[prof] = f"P{len(alias) + 1:02d}"
        yrs = re.findall(r"(\d)학년", str(g(r, "수강대상") or ""))
        room = rooms[0] if rooms else ("", False)
        items.append(dict(course=str(g(r, "과목명")).strip(), category=CAT.get(str(g(r, "이수구분(주전공)") or "").split("-")[0], "기타"),
                          year=min(yrs) if yrs else "", sec_raw=str(g(r, "과목번호"))[-2:], professor=alias[prof],
                          enrollment=int(g(r, "수강인원") or 0), times="; ".join(times), room=room[0], room_lab=int(room[1]),
                          in_grid=int(in_grid)))
    # 과목 안에서 분반 번호를 1부터 다시
    by_course = OrderedDict()
    for it in items:
        by_course.setdefault(it["course"], []).append(it)
    out_rows = []
    for name, its in by_course.items():
        for i, it in enumerate(sorted(its, key=lambda x: x["sec_raw"]), 1):
            it["section"] = i
            out_rows.append({k: it[k] for k in COLS})
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out_rows)
    print(f"분반 {len(out_rows)}개, 과목 {len(by_course)}개, 교수(가명) {len(alias)}명, 뺀 행 {skipped}, 격자 밖 {sum(1 for x in out_rows if not x['in_grid'])}개 → {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("사용법: python solver/tests/real_convert.py 엑셀경로 출력.csv")
    main(sys.argv[1], sys.argv[2])
