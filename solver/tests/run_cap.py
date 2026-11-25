"""분반 수강 인원·강의실 정원(하드), 희망 건물 하나(벌점) 검사. 가상 데이터.
  python solver/tests/run_cap.py"""
import sys
from test_solver2 import *

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")

c = build()
caps = sorted({cap for cap, in c.execute("SELECT capacity FROM room")})
print("강의실 정원 종류:", caps)
# 대상: 응답이 있고 분반 1개, 분반 연강·교차 요청 없는 과목
cid = c.execute("""SELECT s.course_id FROM course_section s JOIN course_response r ON r.course_id=s.course_id
                   GROUP BY s.course_id HAVING COUNT(*)=1 ORDER BY s.course_id LIMIT 1""").fetchone()[0]
c.execute("UPDATE course_response SET lab_requirement='NONE' WHERE course_id=?", (cid,))     # 실습실 조건은 빼고 정원만 본다

# 1) 인원 95명 → 정원 100 강의실에만
c.execute("UPDATE course_section SET enrollment=95 WHERE course_id=?", (cid,)); c.commit()
_, _, secs, *_ = sc.load_input(c, 1, 1)
report("load_input 이 분반 인원을 읽음", secs[(cid, 1)]["enroll"] == 95, f"(과목{cid} 1분반 {secs[(cid, 1)]['enroll']}명)")
r = sc.solve(c, 1, 1, time_limit=30); tt = r["timetable_id"]
got = c.execute("SELECT DISTINCT r.capacity FROM assignment a JOIN room r ON r.id=a.room_id WHERE a.timetable_id=? AND a.course_id=?", (tt, cid)).fetchall()
placed = (cid, 1, 1) not in r["unplaced"] and (cid, 1, 2) not in r["unplaced"]
report("인원 95명 → 정원 100 강의실만", placed and got and all(x >= 95 for x, in got), f"(배정된 정원 {[x for x, in got]})")
pe = c.execute("SELECT planned_enrollment FROM timetable_section WHERE timetable_id=? AND course_id=?", (tt, cid)).fetchone()[0]
report("timetable_section.planned_enrollment = 분반 인원", pe == 95, f"({pe})")
report("전체 검증 위반 없음", verify(c, tt))

# 2) 인원 150명 → 들어갈 강의실이 없어 못 놓음
c.execute("UPDATE course_section SET enrollment=150 WHERE course_id=?", (cid,)); c.commit()
r2 = sc.solve(c, 1, 1, time_limit=30); tt2 = r2["timetable_id"]
n2 = c.execute("SELECT COUNT(*) FROM assignment WHERE timetable_id=? AND course_id=?", (tt2, cid)).fetchone()[0]
miss = [k for k in r2["unplaced"] if k[0] == cid]
report("인원 150명(최대 정원 100) → 못 놓음", n2 == 0 and len(miss) == 2, f"(배정 {n2}칸, 못 놓은 회차 {miss})")
c.execute("UPDATE course_section SET enrollment=NULL WHERE course_id=?", (cid,)); c.commit()
_, _, secs, *_ = sc.load_input(c, 1, 1)
report("인원 미정(NULL)이면 정원 검사 안 함", secs[(cid, 1)]["enroll"] is None)

# 3) 희망 건물 하나: 벌점을 켜면 희망 건물 비율이 오른다
c.execute("UPDATE course_section SET enrollment=40 WHERE course_id=?", (cid,)); c.commit()
*_, pref, _ = sc.load_input(c, 1, 1)
report("load_input 희망 건물 = 교수당 하나", all(isinstance(b, int) for b in pref.values()) and len(pref) == 30, f"(예: {dict(list(pref.items())[:3])})")
def share(tt):
    n, inb = c.execute("""SELECT COUNT(*), SUM(r.building_id = p.building_id) FROM v_schedule v
                          JOIN room r ON r.id=v.room_id JOIN professor_building_pref p ON p.professor_id=v.professor_id
                          WHERE v.timetable_id=?""", (tt,)).fetchone()
    return (inb or 0) / n if n else 0
r_on = sc.solve(c, 1, 1, time_limit=30)
r_off = sc.solve(c, 1, 1, time_limit=30, weights={"building_other": 0})
on, off = share(r_on["timetable_id"]), share(r_off["timetable_id"])
report("희망 건물 벌점 켬 > 끔", on > off, f"(희망 건물에 놓인 회차 비율: 켬 {on:.0%}, 끔 {off:.0%})")
report("벌점 켠 풀이 검증 위반 없음", verify(c, r_on["timetable_id"]))

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
