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

LAB_FROM_LABEL = {"Y": "MUST", "?": "PREFER", "N": "NONE"}
LAB_FROM_WISH = {"필수": "MUST", "있으면 좋음": "PREFER", "필요 없음": "NONE"}
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
            "building": w.get("building") or None,
            "room": None,
            "note": w.get("note", ""),
        })

    if overlap:
        warnings.append(f"희망 칸 {overlap}개가 그 교수의 불가 칸과 겹쳐 BLOCK으로 둠")

    return {
        "wishes": items,
        "professors": {p: {"consecutive": v.get("consecutive")} for p, v in profs.items()},
    }


def build_timetable(src: Path, warnings: list) -> dict:
    draft = read_json(src / "draft_보통.json")
    assignments = []
    for sid, blocks in draft.items():
        rooms = {b.get("room") for b in blocks}
        if len(rooms) > 1:
            warnings.append(f"{sid}: 블록마다 강의실이 달라 첫 강의실만 씀 {sorted(map(str, rooms))}")
        out_blocks = []
        for b in blocks:
            length = to_minutes(b["end"]) - to_minutes(b["start"])
            out_blocks.append({
                "day": b["day"],
                "start": b["start"],
                "slots": round((length + 15) / 90),
            })
        assignments.append({
            "section_id": sid,
            "blocks": out_blocks,
            "room": blocks[0].get("room") if blocks else None,
        })
    return {"status": "DRAFT", "assignments": assignments}


def build_fixed(src: Path) -> list[dict]:
    rows = read_csv(src / "fixed_blocks.csv")
    return [{"kind": r["kind"], "day": r["day"], "start": r["start"], "end": r["end"]} for r in rows]


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
    fixed = build_fixed(src)

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
