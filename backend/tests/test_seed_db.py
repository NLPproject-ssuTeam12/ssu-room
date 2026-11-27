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


# ---------- 시연용 겹침 --demo ----------

def _demo(tmp_path, demo):
    x = fake_xlsx(tmp_path / "fake.xlsx")
    (tmp_path / "rooms.json").write_text(json.dumps(ROOMS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "fixed.json").write_text(json.dumps(FIXED, ensure_ascii=False), encoding="utf-8")
    out = sd.seed(x, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json", tmp_path / "rooms.json",
                  tmp_path / "fixed.json", demo=demo)
    con = sqlite3.connect(tmp_path / "t.db")
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    cells = {}
    for c, n, kind, cnt in con.execute("""SELECT r.course_id, r.section_no, s.kind, COUNT(*) FROM course_response r
                                          JOIN response_slot s ON s.response_id = r.id GROUP BY 1, 2, 3"""):
        cells[(c, n, kind)] = cnt
    prefer = {(c, n): sorted(x for (x,) in con.execute(
        """SELECT t.day || '-' || t.start_time FROM course_response r JOIN response_slot s ON s.response_id = r.id
           JOIN time_slot t ON t.id = s.slot_id WHERE r.course_id=? AND r.section_no=? AND s.kind='PREFER'""", (c, n)))
        for c, n in con.execute("SELECT course_id, section_no FROM course_section")}
    con.close()
    return out, mp, cells, prefer


def test_demo_default_is_unchanged(tmp_path):
    out, mp, cells, _ = _demo(tmp_path, False)
    assert out["demo_changed"] == {} and not any(k[2] == "BLOCK" for k in cells)
    assert not any("demo_changed" in v for v in mp["sections"].values())


def test_demo_makes_overlaps(tmp_path):
    out, mp, cells, prefer = _demo(tmp_path, True)
    ch = out["demo_changed"]
    # 같은 교수의 두 분반(자료구조 02·05): 하나는 막고(지금 칸 말고 모두 불가), 하나는 그 칸만 희망
    block_sid = next(s for s, w in ch.items() if w.startswith("막는"))
    over_sid = next(s for s, w in ch.items() if w.startswith("겹침"))
    b, o = mp["sections"][block_sid], mp["sections"][over_sid]
    assert prefer[(o["course_id"], o["section_no"])] == prefer[(b["course_id"], b["section_no"])]
    assert cells[(b["course_id"], b["section_no"], "BLOCK")] == 40 - 2
    no_opt = next(s for s, w in ch.items() if w.startswith("대안 없음"))
    n = mp["sections"][no_opt]
    assert cells[(n["course_id"], n["section_no"], "BLOCK")] == 40
    assert all(mp["sections"][s]["demo_changed"] == w for s, w in ch.items())
    # 과목·분반·인원은 그대로
    base = _demo(tmp_path / "b", False) if (tmp_path / "b").mkdir() is None else None
    assert {k: (v.get("course_id"), v.get("section_no"), v["enrollment"]) for k, v in mp["sections"].items()} == \
        {k: (v.get("course_id"), v.get("section_no"), v["enrollment"]) for k, v in base[1]["sections"].items()}
    assert out["real_name_hits"] == 0


# ---------- 11/27: 수강 인원 5명 단위 반올림, 희망 비운 교수 ----------

@pytest.mark.parametrize("n,want", [(22, 20), (23, 25), (28, 30), (3, 5), (0, 5), (45, 45), (None, None)])
def test_round5(n, want):
    assert sd.round5(n) == want


def _seed(tmp_path, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    x = fake_xlsx(tmp_path / "fake.xlsx")
    (tmp_path / "rooms.json").write_text(json.dumps(ROOMS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "fixed.json").write_text(json.dumps(FIXED, ensure_ascii=False), encoding="utf-8")
    out = sd.seed(x, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json", tmp_path / "rooms.json",
                  tmp_path / "fixed.json", **kw)
    con = sqlite3.connect(tmp_path / "t.db")
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    alias = json.loads((tmp_path / "alias.json").read_text(encoding="utf-8"))
    return out, con, mp, alias


def test_enrollment_orig_kept(tmp_path):
    out, con, mp, _ = _seed(tmp_path)
    for v in mp["sections"].values():
        assert v["enrollment"] == sd.round5(v["enrollment_orig"])
    assert out["rounded"] == 0 and out["blank_prof"] is None and mp["blank_prof"] is None


def test_blank_prof_auto(tmp_path):
    out, con, mp, alias = _seed(tmp_path, blank_prof="")
    bp = out["blank_prof"]
    assert bp["professor"] == alias[FAKE_A]                       # 같은 과목(자료구조) 분반 둘, MANUAL 없음
    assert mp["blank_prof"] == bp and sorted(bp["sections"]) == ["2150000102", "2150000105-(공통-재수강)"]
    pid = con.execute("SELECT id FROM user WHERE name=?", (bp["professor"],)).fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM course_response WHERE professor_id=?", (pid,)).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM professor_building_pref WHERE professor_id=?", (pid,)).fetchone()[0] == 0
    rows = con.execute("SELECT section_no, enrollment FROM course_section WHERE professor_id=? ORDER BY 1", (pid,)).fetchall()
    assert rows == [(1, None), (2, None)]                         # 분반·담당은 남고 인원만 비움
    assert con.execute("SELECT status FROM round_invite WHERE professor_id=?", (pid,)).fetchone()[0] == "PENDING"
    assert all(mp["sections"][s]["enrollment"] is None for s in bp["sections"])
    # 다른 교수는 그대로
    other = con.execute("SELECT id FROM user WHERE name=?", (alias[FAKE_B],)).fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM course_response WHERE professor_id=?", (other,)).fetchone()[0] == 1
    assert con.execute("SELECT enrollment FROM course_section WHERE professor_id=?", (other,)).fetchone()[0] == 30
    assert out["real_name_hits"] == 0


def test_blank_prof_by_alias_and_errors(tmp_path):
    _, _, _, alias = _seed(tmp_path / "a")
    out, con, mp, _ = _seed(tmp_path / "b", blank_prof=alias[FAKE_B])
    assert out["blank_prof"]["professor"] == alias[FAKE_B] and out["blank_prof"]["sections"] == ["2150000201"]
    with pytest.raises(ValueError, match="가명이 없습니다"):
        _seed(tmp_path / "c", blank_prof="교수99")
    # --demo 가 같은 과목 분반 둘인 유일한 교수를 썼으면 자동 후보가 없다
    with pytest.raises(ValueError, match="후보가 없습니다"):
        _seed(tmp_path / "d", demo=True, blank_prof="")


def test_estimated_capacity_follows_rounded_enrollment(tmp_path):
    """rooms.json 정원이 추정치면 반올림한 인원(43→45)보다 작아지지 않는다. 추정이 아닌 정원은 그대로."""
    x = tmp_path / "x.xlsx"
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    ws.append(row("2150000901", "가상", FAKE_A, f"월 09:00-10:15 (정보과학관 21303-{FAKE_A})\n수 09:00-10:15 (정보과학관 21303-{FAKE_A})", enroll=43))
    ws.append(row("2150000902", "가상2", FAKE_B, f"화 09:00-10:15 (정보과학관 21304-{FAKE_B})\n목 09:00-10:15 (정보과학관 21304-{FAKE_B})", enroll=43))
    wb.save(x)
    rooms = [dict(id="정보과학관 21303", building="정보과학관", room_no="21303", capacity=43, is_lab=False, estimated=True),
             dict(id="정보과학관 21304", building="정보과학관", room_no="21304", capacity=43, is_lab=False, estimated=False)]
    (tmp_path / "rooms.json").write_text(json.dumps(rooms, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "fixed.json").write_text("[]", encoding="utf-8")
    out = sd.seed(x, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json", tmp_path / "rooms.json",
                  tmp_path / "fixed.json")
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    assert mp["rooms"]["정보과학관 21303"]["capacity"] == 45          # 추정치 43 → 반올림 인원 45
    assert mp["rooms"]["정보과학관 21304"]["capacity"] == 43          # 실제 정원은 그대로
    assert out["over_capacity"] == ["2150000902"]                    # 실제 정원보다 커진 분반은 알려 준다


# ---------- 희망 넓히기 (11/27) ----------

def big_xlsx(path: Path) -> Path:
    """과목 12개 × 분반 2개 (분반마다 같은 교수). 요일 쌍과 시각을 돌려 가며. 3학년 전공필수 과목은 채플(목 10:30)이 있다."""
    from openpyxl import Workbook
    pairs = [("월", "수"), ("화", "목"), ("월", "목"), ("화", "금")]
    starts = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30"]
    ends = {"09:00": "10:15", "10:30": "11:45", "12:00": "13:15", "13:30": "14:45", "15:00": "16:15", "16:30": "17:45"}
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for c in range(12):
        prof = f"가상교수{c:02d}"
        for sec in (1, 2):
            d1, d2 = pairs[(c + sec) % 4]
            st = starts[(c * 2 + sec) % 6]
            room = "정보과학관 21303" if sec == 1 else "정보과학관 21304"
            times = f"{d1} {st}-{ends[st]} ({room}-{prof})\n{d2} {st}-{ends[st]} ({room}-{prof})"
            cat = "전필-AI소프트웨어" if c == 0 else "전선-AI소프트웨어"
            ws.append(row(f"21500{c + 10:02d}{sec:02d}", f"과목{c:02d}", prof, times, cat=cat, enroll=30,
                          target="3학년 AI소프트웨어학부" if c == 0 else "2학년 AI소프트웨어학부"))
    wb.save(path)
    return path


def _seed_big(tmp_path, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    x = big_xlsx(tmp_path / "big.xlsx")
    (tmp_path / "rooms.json").write_text(json.dumps(ROOMS, ensure_ascii=False), encoding="utf-8")
    fixed = [{"kind": "채플", "day": "목", "start": "10:30", "end": "11:40", "scope": "AI대학", "years": [3]}]
    (tmp_path / "fixed.json").write_text(json.dumps(fixed, ensure_ascii=False), encoding="utf-8")
    out = sd.seed(x, tmp_path / "t.db", tmp_path / "map.json", tmp_path / "alias.json", tmp_path / "rooms.json",
                  tmp_path / "fixed.json", **kw)
    con = sqlite3.connect(tmp_path / "t.db")
    mp = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    cells = {}
    for c, n, kind, day, st in con.execute(
            """SELECT r.course_id, r.section_no, s.kind, t.day, t.start_time FROM course_response r
               JOIN response_slot s ON s.response_id = r.id JOIN time_slot t ON t.id = s.slot_id"""):
        cells.setdefault((c, n), {}).setdefault(kind, set()).add(f"{day}-{st}")
    return out, mp, cells


def test_widen_kinds_and_actual_cells_kept(tmp_path):
    out, mp, cells = _seed_big(tmp_path)
    _, mp_n, cells_n = _seed_big(tmp_path / "narrow", narrow=True)
    kinds = {sid: v["wish_kind"] for sid, v in mp["sections"].items()}
    assert set(kinds.values()) == {"exact", "adjacent", "other_days", "wide_block"}        # 네 종류 모두
    assert dict(out["wish_kinds"]) == dict(sd.Counter(kinds.values()))
    for sid, v in mp["sections"].items():
        key = (v["course_id"], v["section_no"])
        actual = cells_n[key]["PREFER"]                                  # --narrow = 실제 칸만
        prefer, block = cells[key].get("PREFER", set()), cells[key].get("BLOCK", set())
        assert actual <= prefer and not (actual & block), sid           # 실제 칸은 늘 희망, 불가 아님
        assert not any(c.endswith("19:30") for c in prefer - actual)     # 늦은 교시는 칠하지 않음
        if v["wish_kind"] == "exact":
            assert prefer == actual and not block
        if v["wish_kind"] in ("adjacent", "other_days"):
            assert prefer > actual and not block
        if v["wish_kind"] == "wide_block":
            assert block and len({c.split("-")[0] for c in block}) == 1  # 하루 불가
        if v["category"] == "전공필수":                                  # 3학년 전필: 채플 칸(목 10:30)은 칠하지 않음
            assert "목-10:30" not in prefer - actual
    assert all(v["wish_kind"] == "exact" for v in mp_n["sections"].values())
    assert all(not c.get("BLOCK") for c in cells_n.values())


def test_widen_skips_demo_and_blank(tmp_path):
    out, mp, cells = _seed_big(tmp_path, demo=True, blank_prof="")
    out_n, mp_n, cells_n = _seed_big(tmp_path / "narrow", demo=True, blank_prof="", narrow=True)
    assert out["demo_changed"] == out_n["demo_changed"] and out["blank_prof"] == out_n["blank_prof"]   # 넓히기와 무관
    demo = set(out["demo_changed"])
    blank = set(out["blank_prof"]["sections"])
    assert demo and blank and not (demo & blank)
    for sid in demo | blank:
        assert mp["sections"][sid]["wish_kind"] is None                  # 넓히지 않음
    for sid in demo:                                                      # --demo 결과가 넓히기와 상관없이 같다
        v = mp["sections"][sid]
        assert cells.get((v["course_id"], v["section_no"])) == cells_n.get((v["course_id"], v["section_no"]))
    for sid in blank:                                                     # 희망 비운 교수는 그대로 비어 있음
        v = mp["sections"][sid]
        assert (v["course_id"], v["section_no"]) not in cells
