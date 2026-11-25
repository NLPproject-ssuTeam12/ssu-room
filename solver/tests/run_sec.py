"""분반 입력 검사: 분반은 course_section 행 그대로 (오프라인 회의에서 정한 수·교수·인원). 가상 데이터.
  python solver/tests/run_sec.py"""
import sys
from test_solver2 import *
c = build()
cid = c.execute("select id from course where id not in (select course_id from course_response) order by id limit 1").fetchone()[0]
pa = c.execute("select professor_id from course where id=?", (cid,)).fetchone()[0]; pb = pa % 30 + 1; pc = pb % 30 + 1
def reset():
    c.execute("DELETE FROM request_item WHERE response_id IN (SELECT id FROM course_response WHERE course_id=?)", (cid,))
    c.execute("DELETE FROM course_response WHERE course_id=?", (cid,)); c.execute("DELETE FROM course_section WHERE course_id=?", (cid,))
def resp(prof, n=None, rid=[8000]):
    rid[0] += 1
    c.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?)", (rid[0],1,cid,prof,'NONE','NONE'))
    if n: c.execute("INSERT INTO request_item(response_id,type,value_int) VALUES (?,?,?)", (rid[0],'SECTION_COUNT',n))
def rows(*spec):
    for s, p, e in spec: c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, s, p, e))
def secs():
    _, courses, sd, *_ = sc.load_input(c, 1, 1)
    return [(sd[(cid, s)]["prof"], sd[(cid, s)]["enroll"]) for s in range(1, courses[cid]["sections"]+1)]
nm = {pa:"가", pb:"나", pc:"다"}
results = []
def check(label, expect):
    got = secs()
    txt = "".join(nm.get(p, str(p)) for p, _ in got) + " " + str([e for _, e in got])
    ok = txt == expect; results.append(ok)
    print(("OK  " if ok else "틀림") + f" {label}: {txt}  (기대 {expect})")
reset(); check("행 없음 → 기본 담당 1분반, 인원 미정", "가 [None]")
reset(); resp(pa, 2); check("가가 분반 2개 요청했지만 행 없음 → 요청은 읽지 않음", "가 [None]")
reset(); rows((1, pa, 40)); check("1분반 40명", "가 [40]")
reset(); rows((1, pa, 40), (2, pb, 35)); check("가 40명·나 35명", "가나 [40, 35]")
reset(); resp(pa, 1); resp(pb, 3); rows((1, pa, 30), (2, pa, 30), (3, pb, 25), (4, pb, None)); check("가가나나 (요청 수와 달라도 행 그대로)", "가가나나 [30, 30, 25, None]")
reset(); rows((2, pa, 30), (1, pb, 20)); check("입력 순서와 상관없이 번호 순", "나가 [20, 30]")
reset(); rows((1, pa, 30), (3, pb, 30))
try:
    secs(); print("틀림 번호 빈틈(1,3)인데 오류 없음"); results.append(False)
except ValueError as e:
    print("OK   번호 빈틈(1,3) → ValueError:", e); results.append(True)
reset(); c.commit()
print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
