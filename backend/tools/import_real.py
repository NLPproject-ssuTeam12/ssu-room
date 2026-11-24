"""실습 데이터(2026-2학기 AI대학)를 서버가 읽을 JSON으로 바꾼다.

실행:
    python backend/tools/import_real.py --src C:\\Users\\PC\\Desktop\\rusaint_lab\\data

- 원본 폴더는 읽기만 한다. answer_*.csv(실제 배정 정답)는 읽지 않는다.
- 출력은 data/private/real/ (커밋 금지 폴더)에 쓴다.
- 교수 실명은 가명(교수01…)으로 바꾸고, 끝에 출력 파일 전체를 실명으로 검색해 0건인지 확인한다.
- 표준 라이브러리만 쓴다.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "private" / "real"

# 실습실은 필요(MUST) / 필요 없음(NONE) 두 가지 (팀 결정 11/21). 라벨 Y만 MUST, 그 밖(N, ?)은 NONE.
LAB_FROM_LABEL = {"Y": "MUST", "?": "NONE", "N": "NONE"}
LAB_FROM_WISH = {"필수": "MUST", "있으면 좋음": "NONE", "필요 없음": "NONE"}
SINGLE_DAY_DEFAULT = "NONE"   # 주 1회 연강 희망. 가상 희망 파일에 없으므로 기본값(주 2회)
WISH_CELL = {"희망": "PREFER"}


# ---------- 읽기 도우미 ----------

def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def section_key(code: str, division: str) -> str:
    return f"{code}-{division}" if division else code


def find_col(row: dict, prefix: str) -> str:
    """'lab_need(시험용 라벨)'처럼 괄호 설명이 붙은 열을 앞부분 이름으로 찾는다."""
    for k in row:
        if k == prefix or k.startswith(prefix + "("):
            return k
    raise KeyError(prefix)


def to_int(text: str):
    text = (text or "").strip()
    if not text:
        return None
    return int(float(text))


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_year(target: str):
    m = re.search(r"(\d)\s*학년", target or "")
    return int(m.group(1)) if m else None


# ---------- 변환 ----------

def build_alias(src: Path) -> tuple[dict, set]:
    rows = read_csv(src / "professor_alias.csv")
    alias = {r["professor"]: r["alias"] for r in rows if r["professor"]}
    return alias, set(alias)


def build_sections(src: Path, alias: dict, real_names: set, warnings: list) -> list[dict]:
    rows = read_csv(src / "mvp_input_sections.csv")
    assign_rows = read_csv(src / "mvp_input_professor_assignment.csv")

    assigned = {}
    for r in assign_rows:
        name = r["professor"]
        if name:
            real_names.add(name)
        assigned[section_key(r["code"], r["division"])] = name

    out = []
    for r in rows:
        sid = section_key(r["code"], r["division"])
        lab_col = find_col(r, "lab_need")
        label = r[lab_col][:1].upper()
        if label not in LAB_FROM_LABEL:
            warnings.append(f"{sid}: lab_need 값 '{r[lab_col]}'을 알 수 없어 NONE으로 둠")

        real = assigned.get(sid, "")
        if real and real not in alias:
            warnings.append(f"{sid}: 담당 교수가 가명 표에 없어 null로 둠")
        prof = alias.get(real) if real else None

        out.append({
            "id": sid,
            "code": r["code"],
            "name": r["name"],
            "division": r["division"] or None,
            "year": parse_year(r["target"]),
            "category": r["category"],
            "enrollment": to_int(r["expected_students"]),
            "weekly_blocks": to_int(r["total_blocks_75min"]),
            "professor": prof,
            "lab_need": LAB_FROM_LABEL.get(label, "NONE"),
        })
    return out


def build_rooms(src: Path, warnings: list) -> list[dict]:
    rows = read_csv(src / "rooms_to_fill.csv")
    out = []
    for r in rows:
        seats_in = to_int(r[find_col(r, "seats")])
        lab_in = r[find_col(r, "is_lab")].upper()  # 'is_lab(직접입력 Y/N)'
        guess = r["is_lab_guess"]

        estimated = False
        if seats_in is not None:
            capacity = seats_in
        else:
            capacity = to_int(r["max_students_seen"])
            estimated = True

        if lab_in in ("Y", "N"):
            is_lab = lab_in == "Y"
        else:
            is_lab = guess.startswith(("Y", "?"))
            estimated = True

        rid = f"{r['building']} {r['room_no']}"
        if capacity is None:
            warnings.append(f"{rid}: 좌석 수를 알 수 없음")
        out.append({
            "id": rid,
            "building": r["building"],
            "room_no": r["room_no"],
            "capacity": capacity,
            "is_lab": is_lab,
            "estimated": estimated,
        })
    return out


def build_wishes(src: Path, sections: list[dict], warnings: list) -> dict:
    data = read_json(src / "virtual_wishes_보통.json")
    profs = data.get("professors", {})
    wish_secs = data.get("sections", {})
    sec_prof = {s["id"]: s["professor"] for s in sections}

    blocked = {p: list(v.get("unavailable", [])) for p, v in profs.items()}

    items = []
    overlap = 0
    for sid, w in wish_secs.items():
        prof = w.get("professor") or None
        if sid not in sec_prof:
            warnings.append(f"{sid}: 희망은 있는데 분반 목록에 없음")
        elif sec_prof[sid] != prof:
            warnings.append(f"{sid}: 희망 파일 교수({prof})와 담당 교수({sec_prof[sid]})가 다름")

        cells = {}
        for cell, val in (w.get("slots") or {}).items():
            if val in WISH_CELL:
                cells[cell] = WISH_CELL[val]
            else:
                warnings.append(f"{sid}: 칸 값 '{val}'을 알 수 없어 버림")
        # 불가는 교수 단위 → 그 교수의 모든 분반에 넣는다. 희망과 겹치면 불가가 이긴다.
        for cell in blocked.get(prof, []):
            if cells.get(cell) == "PREFER":
                overlap += 1
            cells[cell] = "BLOCK"
        # avoid(피함)는 팀 결정으로 버린다.

        lab_raw = w.get("lab", "")
        if lab_raw not in LAB_FROM_WISH:
            warnings.append(f"{sid}: 실습실 값 '{lab_raw}'을 알 수 없어 NONE으로 둠")

        items.append({
            "section_id": sid,
            "professor": prof,
            "cells": dict(sorted(cells.items())),
            "must": False,
            "lab": LAB_FROM_WISH.get(lab_raw, "NONE"),
            "single_day": SINGLE_DAY_DEFAULT,
            "building": w.get("building") or None,
            "room": None,
            "note": w.get("note", ""),
        })

    if overlap:
        warnings.append(f"희망 칸 {overlap}개가 그 교수의 불가 칸과 겹쳐 BLOCK으로 둠")

    return {
        "wishes": items,
        # 교수별 맡은 분반. 예전 '연강'(consecutive, 맡은 강의 이어서 하기) 값은 팀 결정(11/21)으로 뺐다
        "professors": {p: {"sections": sorted(s["id"] for s in sections if s["professor"] == p)}
                       for p in sorted(profs)},
    }


def build_timetable(src: Path, warnings: list) -> dict:
    draft = read_json(src / "draft_보통.json")
    assignments = []
    for sid, blocks in draft.items():
        # 수업(회차)마다 강의실을 blocks[].room에 둔다. room은 대표 강의실(첫 수업의 강의실)
        out_blocks = []
        for b in blocks:
            length = to_minutes(b["end"]) - to_minutes(b["start"])
            out_blocks.append({
                "day": b["day"],
                "start": b["start"],
                "slots": round((length + 15) / 90),
                "room": b.get("room"),
            })
        assignments.append({
            "section_id": sid,
            "blocks": out_blocks,
            "room": blocks[0].get("room") if blocks else None,
        })
    return {"status": "DRAFT", "assignments": assignments}


CHAPEL_TIME = re.compile(r"([월화수목금토])\s+(\d{2}:\d{2})-(\d{2}:\d{2})")
AI_TARGET = re.compile(r"AI대|AI소프트|정보보호")


def chapel_scope(target: str) -> tuple[str, list[int]]:
    """채플 수강 대상 글 → (범위, 대상 학년).
    범위: "AI대학" = AI소프트웨어학부·정보보호학과 대상 / "전체" = 모든 단과대학이 고르는 채플(대상이 애매)
          / "다른 학과" = 그 밖. 대상 학년 [] = 전체 학년.
    '(수강제한: …)' 뒤는 대상이 아니라 막는 쪽이라 보지 않는다."""
    main = re.split(r"\(수강제한|\(대상외", target)[0]
    main = re.sub(r"\([^)]*수강제한[^)]*\)", "", main)     # '(1학년은 수강제한)'처럼 막는 쪽 설명은 뺀다
    years = sorted({int(y) for y in re.findall(r"(\d)학년", main)})
    if "전체 단과대학" in main or "전체학년 수강가능" in main:
        return "전체", years
    if AI_TARGET.search(main) and "정보보호 제외" not in main:
        return "AI대학", years
    return "다른 학과", years


def build_chapels(src: Path, warnings: list) -> list[dict]:
    """개설 강좌(lectures_2026_2.csv)에서 채플 시간과 수강 대상(범위·학년)을 뽑는다.
    schedule_room의 괄호 부분(강의실·담당자 이름)은 읽어도 출력에 넣지 않는다."""
    out, seen = [], set()
    for r in read_csv(src / "lectures_2026_2.csv"):
        if not r.get("group", "").startswith("채플"):
            continue
        scope, years = chapel_scope(r.get("target", ""))
        times = CHAPEL_TIME.findall(r.get("schedule_room", "").split("(")[0])
        if not times:
            warnings.append(f"채플 {r['code']}: 시간을 읽지 못해 뺌")
        for day, start, end in times:
            key = (day, start, end, scope, tuple(years))
            if key in seen:      # 같은 시간·같은 대상 분반이 여럿이면 한 번만
                continue
            seen.add(key)
            out.append({"kind": "채플", "sub": r["group"].split(":", 1)[-1], "day": day, "start": start,
                        "end": end, "scope": scope, "years": years})
    return out


def build_fixed(src: Path, warnings: list) -> list[dict]:
    """고정 시간. 교양필수는 fixed_blocks.csv 그대로, 채플은 개설 강좌에서 대상까지 읽어 넣는다."""
    rows = read_csv(src / "fixed_blocks.csv")
    out = [{"kind": r["kind"], "day": r["day"], "start": r["start"], "end": r["end"], "scope": None, "years": []}
           for r in rows if r["kind"] != "채플"]
    return out + build_chapels(src, warnings)


# ---------- 검사 ----------

def scan_real_names(paths: list[Path], names: set) -> list[tuple[str, str, int]]:
    hits = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for n in names:
            c = text.count(n)
            if c:
                hits.append((p.name, n, c))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="실습 데이터를 SSU:room JSON으로 변환")
    ap.add_argument("--src", required=True, type=Path, help="rusaint_lab/data 폴더")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="출력 폴더 (기본: data/private/real)")
    args = ap.parse_args()

    src: Path = args.src
    out: Path = args.out
    if not src.is_dir():
        print(f"원본 폴더가 없습니다: {src}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    alias, real_names = build_alias(src)
    sections = build_sections(src, alias, real_names, warnings)
    rooms = build_rooms(src, warnings)
    wishes = build_wishes(src, sections, warnings)
    timetable = build_timetable(src, warnings)
    fixed = build_fixed(src, warnings)

    room_ids = {r["id"] for r in rooms}
    for a in timetable["assignments"]:
        if a["room"] and a["room"] not in room_ids:
            warnings.append(f"{a['section_id']}: 초안 강의실 '{a['room']}'이 강의실 목록에 없음")

    files = {
        "sections.json": sections,
        "rooms.json": rooms,
        "wishes.json": wishes,
        "timetable.json": timetable,
        "fixed_blocks.json": fixed,
    }
    written = []
    for name, data in files.items():
        path = out / name
        write_json(path, data)
        written.append(path)

    print(f"출력 폴더: {out}")
    print("── 요약 ──")
    print(f"분반          {len(sections)}")
    print(f"강의실        {len(rooms)} (추정값 포함 {sum(r['estimated'] for r in rooms)})")
    print(f"희망          {len(wishes['wishes'])} (교수 {len(wishes['professors'])})")
    print(f"배정(초안)    {len(timetable['assignments'])}")
    print(f"담당 없는 분반 {sum(1 for s in sections if s['professor'] is None)}")
    print(f"고정 블록     {len(fixed)}")

    if warnings:
        print(f"── 경고 {len(warnings)}건 ──")
        for w in warnings:
            print(" -", w)

    hits = scan_real_names(written, real_names)
    print("── 실명 검사 ──")
    print(f"실명 {len(real_names)}개로 출력 파일 {len(written)}개 검색: {sum(h[2] for h in hits)}건")
    if hits:
        # 실명 자체는 화면에 찍지 않는다.
        for fname, _, c in hits:
            print(f" - {fname}: {c}건")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
