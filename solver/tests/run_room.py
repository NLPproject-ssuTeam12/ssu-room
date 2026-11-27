"""학기별 강의실 범위 검사 (작은 가상 DB, 11/27, 012).
  ① 조교가 끈 강의실·건물에는 배정하지 않는다 (켜진 강의실만 후보)
  ② 꺼진 건물을 고른 희망 건물은 무시한다 (벌점 없음 = 희망 건물이 없을 때와 같은 점수)
  ③ 실습실이 모두 꺼지면 실습실이 필요한 분반은 못 놓음
  ④ 고정된 분반은 꺼진 강의실이어도 그대로 두고 check_timetable 이 '꺼진 강의실'로 경고. 다른 분반은 꺼진 방에서 옮겨 간다
  ⑤ 희망 건물은 학기별: 다른 학기에 고른 건물은 이번 학기 풀이에 쓰지 않는다
  python solver/tests/run_room.py"""
import os, sys
from test_data import SCHEMA_PATH          # 경로 설정은 test_data 가 한다
import seed_time_slot as sd, solver_core as sc, db as hdb

results = []
def report(label, ok, detail=""):
    results.append(bool(ok)); print(("OK  " if ok else "틀림") + f" {label} {detail}")


def small(lab_course=False):
    c = hdb.connect(":memory:"); c.executescript(open(SCHEMA_PATH, encoding="utf-8").read()); sd.seed(c)
    c.execute("INSERT INTO department VALUES (1,'가상학과','가상대학')")
    c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (9,'TA','조교',1,'x')")
    c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)")
    c.execute("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
    for b in (1, 2):
        c.execute("INSERT INTO building VALUES (?,?)", (b, f"가상건물{b}"))
        for k in range(2):                       # 건물마다 일반 강의실 1, 실습실 1
            c.execute("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (?,?,?,?,?)", (b * 100 + k, b, f"{b}0{k}", 60, k))
    for cid in (1, 2, 3):
        c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (cid + 10, "PROF", f"가상교수{cid}", 1, "x"))
        c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
                  (cid, 1, 1, f"과목{cid}", cid + 10, "전공선택", "2", 2, 1))
        c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, 1, cid + 10, 30))
        lab = "MUST" if lab_course and cid == 1 else "NONE"
        c.execute("INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?,?)",
                  (cid, 1, cid, 1, cid + 10, lab, "NONE"))
    c.commit(); return c


def blds(c, tt):
    return {r for (r,) in c.execute("SELECT DISTINCT r.building_id FROM assignment a JOIN room r ON r.id=a.room_id WHERE a.timetable_id=?", (tt,))}


def rooms_of(c, tt, cid=None):
    sql = "SELECT DISTINCT room_id FROM assignment WHERE timetable_id=?" + (" AND course_id=?" if cid else "")
    return {r for (r,) in c.execute(sql, (tt, cid) if cid else (tt,))}


# ① 건물 2를 끄면 모두 건물 1
c = small()
hdb.set_building_enabled(c, 9, 1, 2, False)
r = sc.solve(c, 1, 1, time_limit=20)
report("① 끈 건물에는 배정하지 않음", blds(c, r["timetable_id"]) == {1} and not r["unplaced"], f"({blds(c, r['timetable_id'])})")
hdb.set_room_enabled(c, 9, 1, 100, False)
r = sc.solve(c, 1, 1, time_limit=20)
report("① 끈 강의실에도 배정하지 않음 (실습실 101만 남음)", rooms_of(c, r["timetable_id"]) == {101}, f"({rooms_of(c, r['timetable_id'])})")

# ② 꺼진 건물을 고른 희망 건물은 무시 (희망 건물이 없을 때와 점수가 같음)
c = small(); hdb.set_building_enabled(c, 9, 1, 2, False)
base = sc.solve(c, 1, 1, time_limit=20)["objective"]
for p in (11, 12, 13):
    c.execute("INSERT INTO professor_building_pref(term_id,professor_id,building_id) VALUES (1,?,2)", (p,))
c.commit()
r = sc.solve(c, 1, 1, time_limit=20)
report("② 꺼진 건물 희망은 벌점 없음", r["objective"] == base, f"(희망 없음 {base} / 꺼진 건물 희망 {r['objective']})")
report("② 꺼진 건물 희망 목록(조교 화면용)", hdb.stale_building_prefs(c, 1) == [(11, 2), (12, 2), (13, 2)])

# ③ 실습실이 모두 꺼지면 실습실 필요 분반은 못 놓음
c = small(lab_course=True)
for rid in (101, 201):
    hdb.set_room_enabled(c, 9, 1, rid, False)
r = sc.solve(c, 1, 1, time_limit=20)
report("③ 실습실이 꺼지면 실습실 필요 분반은 못 놓음", {u[0] for u in r["unplaced"]} == {1}, f"({r['unplaced']})")

# ④ 고정 분반은 꺼진 방 그대로 + 경고, 다른 분반은 옮겨 감
c = small()
for p in (11, 12, 13):                            # 셋 다 건물 1 을 희망 → 처음에는 건물 1
    c.execute("INSERT INTO professor_building_pref(term_id,professor_id,building_id) VALUES (1,?,1)", (p,))
c.commit()
t1 = sc.solve(c, 1, 1, time_limit=20)["timetable_id"]
used = rooms_of(c, t1)
hdb.set_lock(c, t1, 1, 1, True)
for rid in used:
    hdb.set_room_enabled(c, 9, 1, rid, False)
viol = [v["course_id"] for v in sc.check_timetable(c, t1) if v["rule"] == "꺼진 강의실"]
report("④ 끈 뒤 기존 시간표에 '꺼진 강의실' 경고", sorted(set(viol)) == [1, 2, 3], f"({viol})")
r = sc.solve(c, 1, 1, time_limit=20, previous_timetable_id=t1)
t2 = r["timetable_id"]
kept = rooms_of(c, t2, 1) == rooms_of(c, t1, 1)
moved = not (rooms_of(c, t2, 2) | rooms_of(c, t2, 3)) & used
viol2 = sorted({v["course_id"] for v in sc.check_timetable(c, t2) if v["rule"] == "꺼진 강의실"})
report("④ 고정 분반은 그대로, 다른 분반은 꺼진 방에서 옮김", kept and moved and viol2 == [1] and not r["unplaced"],
       f"(고정 {rooms_of(c, t2, 1)}, 나머지 {rooms_of(c, t2, 2) | rooms_of(c, t2, 3)}, 꺼진 방 {used}, 경고 {viol2})")

# ⑤ 희망 건물은 학기별
c = small()
c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (2,2027,'1',1)")
for p in (11, 12, 13):
    c.execute("INSERT INTO professor_building_pref(term_id,professor_id,building_id) VALUES (2,?,2)", (p,))
c.commit()
_, _, _, _, pref, _ = sc.load_input(c, 1, 1)
report("⑤ 다른 학기에 고른 희망 건물은 이번 학기에 없음", pref == {})
for p in (11, 12, 13):
    hdb.set_building_pref(c, 1, p, 2)
_, _, _, _, pref, _ = sc.load_input(c, 1, 1)
report("⑤ 이번 학기 희망 건물", pref == {11: 2, 12: 2, 13: 2})

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
