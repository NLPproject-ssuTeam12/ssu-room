"""건물·강의실 입력과 학기별 켜기, 학기별 희망 건물, 교수·과목·분반 지정과 희망 입력 요청 검사 (11/27, 012).
  python db/tests/test_room_invite.py"""
import os, sqlite3, sys
DB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # db/
sys.path.insert(0, DB)
import db as hdb
import seed_time_slot as sd

results = []
def report(label, ok, detail=""):
    results.append(bool(ok)); print(("OK  " if ok else "틀림") + f" {label} {detail}")

def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    return None

def fresh():
    c = hdb.connect(":memory:")
    c.executescript(open(os.path.join(DB, "schema.sql"), encoding="utf-8").read()); sd.seed(c)
    c.execute("INSERT INTO department VALUES (1,'가상학과','가상대학')")
    c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (1,'TA','조교',1,'x')")
    c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)")
    c.execute("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (1,1,1,'2026-12-01')")
    c.commit(); return c

TA = 1
on = lambda c, t: sorted(r["room_id"] for r in hdb.term_rooms(c, t) if r["on"])

# ---------------- 건물·강의실 입력
c = fresh()
b1 = hdb.add_building(c, TA, " 가상관 "); b2 = hdb.add_building(c, TA, "새관")
report("건물 넣기(앞뒤 공백 지움)", c.execute("SELECT name FROM building WHERE id=?", (b1,)).fetchone() == ("가상관",))
report("같은 이름 건물 거부", raises(hdb.add_building, c, TA, "가상관"))
report("조교가 아니면 거부", raises(hdb.add_building, c, 99, "다른관"))
r1 = hdb.add_room(c, TA, b1, "101", 60, False)
r2 = hdb.add_room(c, TA, b1, 102, 40, True)            # 호수를 숫자로 줘도 됨
r3 = hdb.add_room(c, TA, b2, "201", 50, 0)
report("강의실 넣기 (호수 숫자 → 글자)", c.execute("SELECT room_no, is_lab FROM room WHERE id=?", (r2,)).fetchone() == ("102", 1))
for label, args in (("정원 없음", (b1, "103", None, False)), ("정원 0", (b1, "103", 0, False)), ("정원 글자", (b1, "103", "60", False)),
                    ("실습실 여부 없음", (b1, "103", 60, None)), ("실습실 여부 2", (b1, "103", 60, 2)), ("호수 빈칸", (b1, " ", 60, False)),
                    ("없는 건물", (99, "103", 60, False)), ("같은 건물·같은 호수", (b1, "101", 30, False))):
    report(f"필수 입력 검사: {label} 거부", raises(hdb.add_room, c, TA, *args))
report("새 강의실은 지금 학기에 켜짐(트리거)", on(c, 1) == sorted([r1, r2, r3]))
hdb.update_room(c, TA, r1, capacity=80)
report("정원 고치기", c.execute("SELECT capacity, room_no FROM room WHERE id=?", (r1,)).fetchone() == (80, "101"))
report("고칠 때도 같은 호수 거부", raises(hdb.update_room, c, TA, r2, room_no="101"))

# ---------------- 학기별 켜기·끄기와 고를 수 있는 건물
hdb.set_room_enabled(c, TA, 1, r3, False)
report("강의실 끄기", on(c, 1) == sorted([r1, r2]))
report("켜진 강의실이 없는 건물은 고를 수 없음", hdb.selectable_buildings(c, 1) == [(b1, "가상관")])
n = hdb.set_building_enabled(c, TA, 1, b1, False)
report("건물 끄기 = 그 건물 강의실 전부 끄기", n == 2 and on(c, 1) == [] and hdb.selectable_buildings(c, 1) == [])
n = hdb.set_building_enabled(c, TA, 1, b2, True)
report("건물 켜기", n == 1 and on(c, 1) == [r3] and hdb.selectable_buildings(c, 1) == [(b2, "새관")])
hdb.set_building_enabled(c, TA, 1, b1, True)

# ---------------- 학기별 희망 건물
p = hdb.add_professor(c, TA, "가상교수", 1, hire_year=2010)
hdb.set_building_pref(c, 1, p, b1)
report("희망 건물 저장", hdb.building_pref(c, 1, p) == b1)
hdb.set_building_enabled(c, TA, 1, b2, False)
report("꺼진 건물은 희망으로 고를 수 없음", raises(hdb.set_building_pref, c, 1, p, b2) and hdb.building_pref(c, 1, p) == b1)
hdb.set_building_enabled(c, TA, 1, b1, False); hdb.set_building_enabled(c, TA, 1, b2, True)
report("고른 뒤 꺼진 희망 건물 목록", hdb.stale_building_prefs(c, 1) == [(p, b1)])
hdb.set_building_pref(c, 1, p, None)
report("상관없음 = 지움", hdb.building_pref(c, 1, p) is None)
hdb.set_building_enabled(c, TA, 1, b1, True)

# ---------------- 새 학기는 바로 전 학기 설정 이어받기, 확정 학기는 새 방이 켜지지 않음
hdb.set_room_enabled(c, TA, 1, r2, False)               # 2026-2: r1, r3 켜짐
c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (2,2027,'1',1)"); c.commit()
report("새 학기는 바로 전 학기(2026-2)에 켠 강의실 그대로", on(c, 2) == sorted([r1, r3]), f"({on(c, 2)})")
c.execute("UPDATE term SET phase='FINAL' WHERE id=1"); c.commit()
r4 = hdb.add_room(c, TA, b2, "202", 30, False)
report("새 강의실: 확정 전 학기에만 켜짐", r4 in on(c, 2) and r4 not in on(c, 1))
report("확정 학기 강의실은 바꿀 수 없음", raises(hdb.set_room_enabled, c, TA, 1, r4, True))
c2 = fresh()
c2.execute("INSERT INTO building VALUES (1,'가')"); c2.execute("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (1,1,'1',30,0)")
c2.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (2,2025,'2',1)"); c2.commit()
report("전 학기가 없는 학기는 모든 강의실 켜짐", on(c2, 2) == [1])

# ---------------- 지우기
report("쓰이지 않은 강의실 지우기", raises(hdb.delete_room, c, TA, r4) is None and r4 not in on(c, 2))
c.execute("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
c.execute("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
c.execute("INSERT INTO course(id,term_id,name,professor_id) VALUES (50,1,'가상과목',?)", (p,))
c.execute("INSERT INTO timetable_section(timetable_id,course_id,section_no) VALUES (1,50,1)")
c.execute("INSERT INTO assignment VALUES (1,50,1,1,1,?)", (r1,)); c.commit()
report("시간표에 쓰인 강의실은 지울 수 없음(끄기만)", raises(hdb.delete_room, c, TA, r1))
report("강의실이 있는 건물은 지울 수 없음", raises(hdb.delete_building, c, TA, b1))
b3 = hdb.add_building(c, TA, "빈관")
report("빈 건물 지우기", raises(hdb.delete_building, c, TA, b3) is None)

# ---------------- 교수·과목·분반 지정
c = fresh()
for b in (1, 2):
    c.execute("INSERT INTO building VALUES (?,?)", (b, f"관{b}"))
c.commit()
P = [hdb.add_professor(c, TA, f"가상교수{i}", 1) for i in range(1, 5)]
report("교수 계정(비밀번호 비움)", c.execute("SELECT role, password_hash FROM user WHERE id=?", (P[0],)).fetchone() == ("PROF", ""))
report("임용 연도 범위 검사", raises(hdb.add_professor, c, TA, "가상", hire_year=1800))
cid = hdb.add_course(c, TA, 1, "가상자료구조", [(P[0], 40), P[1]], category="전공필수", target_year=2)
report("과목 + 분반 2개(1분반 담당 = 과목 담당)",
       c.execute("SELECT section_no, professor_id, enrollment FROM course_section WHERE course_id=? ORDER BY 1", (cid,)).fetchall()
       == [(1, P[0], 40), (2, P[1], None)] and c.execute("SELECT professor_id, target_year FROM course WHERE id=?", (cid,)).fetchone() == (P[0], "2"))
report("분반 없는 과목 거부", raises(hdb.add_course, c, TA, 1, "가상", []))
report("담당이 교수가 아니면 거부", raises(hdb.add_course, c, TA, 1, "가상", [TA]))
report("인원 0 거부", raises(hdb.add_course, c, TA, 1, "가상", [(P[0], 0)]))
cid2 = hdb.add_course(c, TA, 1, "가상알고리즘", [P[2]])
report("교수 화면: 맡은 분반", hdb.professor_sections(c, 1, P[1]) == [(cid, "가상자료구조", 2, None, "전공필수", "2")])

# ---------------- 희망 입력 요청
new = hdb.send_invites(c, TA, 1)
report("분반을 맡은 교수 전원에게 요청 (분반 없는 교수 4는 빼고)", new == P[:3], f"({new})")
report("요청 기록 PENDING·invited_at", all(s == "PENDING" and t for s, t in c.execute(
    "SELECT status, invited_at FROM round_invite WHERE round_id=1")))
report("두 번 보내도 새로 요청하지 않음", hdb.send_invites(c, TA, 1) == [])
report("분반 없는 교수에게 요청 거부", raises(hdb.send_invites, c, TA, 1, [P[3]]))
c.execute("""INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref)
             VALUES (100,1,?,2,?,'NONE','NONE')""", (cid, P[1]))
c.execute("UPDATE round_invite SET status='RESPONDED', responded_at=datetime('now') WHERE professor_id=?", (P[1],)); c.commit()
report("다시 알림: 응답 안 한 교수만", hdb.remind_invites(c, TA, 1) == [P[0], P[2]])
st = {r["professor_id"]: r for r in hdb.invite_status(c, 1)}
report("현황: 요청·응답·분반 수", st[P[1]]["status"] == "RESPONDED" and st[P[1]]["sections"] == 1 and st[P[1]]["responded_sections"] == 1
       and st[P[0]]["reminded_at"] and st[P[0]]["responded_sections"] == 0 and P[3] not in st)

# ---------------- 분반 다시 정하기
report("희망을 낸 분반의 담당이 바뀌면 거부", raises(hdb.set_sections, c, TA, cid, [P[0], P[2]]))
report("응답 없는 분반은 바꾸기 (분반 3개로)", hdb.set_sections(c, TA, cid, [(P[0], 45), P[1], P[3]]) == []
       and c.execute("SELECT COUNT(*) FROM course_section WHERE course_id=?", (cid,)).fetchone() == (3,))
report("force=True 면 바꾸고 잃은 분반을 알려 줌", hdb.set_sections(c, TA, cid, [P[0]], force=True) == [2])
report("새로 맡은 교수에게만 요청 (교수 4는 분반이 없어져 다시 빠짐)", hdb.send_invites(c, TA, 1) == [])
hdb.set_sections(c, TA, cid2, [P[2], P[3]])
report("분반이 생긴 교수 4에게 요청", hdb.send_invites(c, TA, 1) == [P[3]])
report("희망 입력이 있는 과목은 지울 수 없음", raises(hdb.delete_course, c, TA, cid))
cid3 = hdb.add_course(c, TA, 1, "가상지울과목", [P[0]])
report("빈 과목 지우기", raises(hdb.delete_course, c, TA, cid3) is None)
hdb.set_phase(c, 1, "ROUND1", TA)
report("희망 수집이 끝나면 과목·분반을 바꿀 수 없음", raises(hdb.add_course, c, TA, 1, "가상", [P[0]])
       and raises(hdb.set_sections, c, TA, cid2, [P[2]]))

print("\n결과:", f"{sum(results)}/{len(results)}", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
