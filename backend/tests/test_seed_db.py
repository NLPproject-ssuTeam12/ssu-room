"""시드 스크립트(backend/tools/seed_db.py) 검사. 작은 가짜 엑셀로 본다 (실제 엑셀 검사는 없으면 건너뜀).
가짜 엑셀의 교수 이름도 지어낸 것이다."""

import json
import sqlite3
from pathlib import Path

import pytest

from backend.tools import seed_db as sd

REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD = ["계획", "이수구분(주전공)", "이수구분(다전공)", "공학인증", "과목번호", "과목명", "수강유의사항", "강좌유형정보",
        "분반", "교수명", "개설학과", "시간/학점(설계)", "수강인원", "여석", "강의시간(강의실)", "수강대상"]
FAKE_A, FAKE_B, FAKE_C = "가상일", "가상이", "가상삼"   # 지어낸 이름 (실명 검색 대상)


def row(code, name, prof, times, cat="전선-AI소프트웨어", enroll=30, target="2학년 AI소프트웨어학부", division=None):
    return [None, cat, None, None, code, name, None, None, division, prof, "AI소프트웨어학부", "3.0/3.0", enroll, 0,
            times, target]


def fake_xlsx(path: Path) -> Path:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    rows = [
        # 과목 21500001: 분반 02·05 (빈칸) → 1·2, 같은 교수
        row("2150000102", "자료구조", FAKE_A, f"월 09:00-10:15 (정보과학관 21303-{FAKE_A})\n수 09:00-10:15 (정보과학관 21303-{FAKE_A})",
            cat="전필-AI소프트웨어", enroll=45),
        row("2150000105", "자료구조", FAKE_A, f"화 13:30-14:45 (정보과학관 21305 (실습실)-{FAKE_A})\n화 15:00-16:15 (정보과학관 21305 (실습실)-{FAKE_A})",
            cat="전필-AI소프트웨어", enroll=40, division=" (공통-재수강)"),
        # 과목 21500002: 1학년 전필, 다른 교수
        row("2150000201", "글쓰기", FAKE_B, f"목 10:30-11:45 (문화관 03407-{FAKE_B})\n금 10:30-11:45 (문화관 03407-{FAKE_B})",
            cat="전필-AI소프트웨어", target="1학년 AI소프트웨어학부"),
        # MANUAL: 토요일 / 50분 수업 / 강의시간 없음
        row("2150000301", "현장실습", FAKE_C, f"토 09:00-10:15 (전산관 19429-{FAKE_C})\n토 10:30-11:45 (전산관 19429-{FAKE_C})"),
        row("2150000401", "실험", FAKE_C, f"월 15:00-15:50 (정보과학관 21304-{FAKE_C})\n수 15:00-15:50 (정보과학관 21304-{FAKE_C})"),
        row("2150000501", "캡스톤", FAKE_C, None),
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


FIXED = [{"kind": "채플", "day": "목", "start": "10:30", "end": "11:40", "scope": "AI대학", "years": [1]},
         {"kind": "채플", "day": "월", "start": "10:30", "end": "11:20", "scope": "다른 학과", "years": [2]},
         {"kind": "교양필수", "day": "금", "start": "09:00", "end": "10:15", "scope": None, "years": []}]
ROOMS = [{"id": "정보과학관 21303", "building": "정보과학관", "room_no": "21303", "capacity": 51, "is_lab": True,
          "estimated": False}]


@pytest.fixture()
def seeded(tmp_path):
    x = fake_xlsx(tmp_path / "fake.xlsx")
    (tmp_path / "rooms.json").write_text(json.dumps(ROOMS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "fixed.json").write_text(json.dumps(FIXED, ensure_ascii=False), encoding="utf-8")
    out = sd.seed(x, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json", tmp_path / "rooms.json",
                  tmp_path / "fixed.json")
    con = sqlite3.connect(tmp_path / "t.db")
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    yield out, con, mp, tmp_path
    con.close()


def test_sections_renumbered_and_map(seeded):
    _, con, mp, _ = seeded
    s = mp["sections"]
    assert (s["2150000102"]["course_id"], s["2150000102"]["section_no"], s["2150000102"]["orig_section_no"]) == (1, 1, "02")
    sid = "2150000105-(공통-재수강)"                                 # 서버 분반 id 모양은 기존과 같게
    assert (s[sid]["section_no"], s[sid]["orig_section_no"], s[sid]["division"]) == (2, "05", "(공통-재수강)")
    assert sd.section_pairs(mp) == {(1, 1): "2150000102", (1, 2): sid, (2, 1): "2150000201"}
    got = {(c, n): e for c, n, e in con.execute("SELECT course_id, section_no, enrollment FROM course_section")}
    assert got == {(1, 1): 45, (1, 2): 40, (2, 1): 30}             # 분반 인원 = 수강인원
    assert con.execute("SELECT category, target_year FROM course WHERE id=2").fetchone() == ("전공필수", "1")


def test_manual_sections_not_in_db(seeded):
    out, con, mp, _ = seeded
    man = {k: v["manual_reason"] for k, v in mp["sections"].items() if v["manual"]}
    assert man == {"2150000301": "토·일요일 수업", "2150000401": "교시 밖 시각", "2150000501": "강의시간 없음"}
    assert con.execute("SELECT COUNT(*) FROM course").fetchone()[0] == 2
    assert mp["sections"]["2150000301"]["blocks"][0]["day"] == "토"      # MANUAL 칸은 대응표에 남는다
    assert dict(out["counts"])["MANUAL (DB에 안 넣음)"] == 3


def test_wishes_rooms_and_chapel(seeded):
    _, con, mp, _ = seeded
    rows = con.execute("""SELECT r.section_no, r.lab_requirement, r.single_day_pref, COUNT(s.slot_id)
                          FROM course_response r JOIN response_slot s ON s.response_id = r.id
                          WHERE r.course_id = 1 GROUP BY r.id ORDER BY r.section_no""").fetchall()
    assert rows == [(1, "NONE", "NONE", 2), (2, "MUST", "MUST", 2)]  # 분반마다, 실습실 쓰면 MUST, 연강이면 MUST
    assert mp["rooms"]["정보과학관 21303"]["estimated"] is False and mp["rooms"]["정보과학관 21303"]["capacity"] == 51
    assert mp["rooms"]["문화관 03407"]["estimated"] is True and mp["rooms"]["문화관 03407"]["is_lab"] is True
    # 채플: AI대학 1학년 목 10:30 → 1학년 칸 하나. 다른 학과 채플·교양필수는 넣지 않음
    ch = con.execute("""SELECT c.target_year, t.day, t.start_time FROM chapel_slot c JOIN time_slot t ON t.id = c.slot_id""").fetchall()
    assert ch == [("1", "목", "10:30")]
    bp = dict(con.execute("""SELECT u.name, b.name FROM professor_building_pref p JOIN user u ON u.id = p.professor_id
                             JOIN building b ON b.id = p.building_id""").fetchall())
    assert set(bp.values()) <= {"정보과학관", "문화관"}
    assert con.execute("SELECT COUNT(*) FROM user WHERE role='TA'").fetchone()[0] == 1


def test_no_real_names_anywhere(seeded):
    out, con, mp, tmp = seeded
    assert out["real_name_hits"] == 0
    alias = json.loads((tmp / "alias.json").read_text(encoding="utf-8"))
    assert set(alias) == {FAKE_A, FAKE_B, FAKE_C} and all(v.startswith("교수") for v in alias.values())
    blob = (tmp / "map.json").read_text(encoding="utf-8")
    assert not any(n in blob for n in alias)
    assert sd.real_name_hits(list(alias), con) == 0


# ---------- 실제 엑셀 ----------

REAL = sd.DEFAULT_XLSX


@pytest.mark.skipif(not REAL.exists(), reason="실제 강의정보 엑셀이 없음")
def test_real_excel_seed(tmp_path):
    out = sd.seed(REAL, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json",
                  sd.PRIVATE / "real" / "rooms.json", sd.PRIVATE / "real" / "fixed_blocks.json")
    assert out["real_name_hits"] == 0
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    by_course = {}
    for v in mp["sections"].values():
        if not v["manual"]:
            by_course.setdefault(v["course_id"], []).append(v["section_no"])
    assert all(sorted(v) == list(range(1, len(v) + 1)) for v in by_course.values())
    assert dict(out["counts"])["분반(DB)"] == len(sd.section_pairs(mp))
