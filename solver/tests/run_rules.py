"""11/24 규칙 검사 (가상 데이터).
  ① 같은 학년 전공필수는 교수가 다르면 겹쳐도 됨   ② 전공필수는 그 학년 채플 칸에 놓지 않음
  ③ 18:00 이후 시작 연강 금지                       ④ 19:30 교시는 큰 감점
  ⑤ 분반 연강·교차는 교수 응답 칸(section_pair)으로, 그 교수의 두 분반(3·4번이어도)에
  ⑥ 대안에 회차 순서만 바뀐 같은 안이 나오지 않음
기준 시간표를 한 번 풀고, 시험용 과목(가상)만 free_courses 로 다시 푼다.
  python solver/tests/run_rules.py"""
import sys
from test_solver2 import *

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")

c = build()
base = sc.solve(c, 1, 1, time_limit=30); tt = base["timetable_id"]
print("기준:", base["status"], "못놓음", len(base["unplaced"])); report("기준 시간표 검증", verify(c, tt))
SL = {(d, t): i for i, d, t in c.execute("SELECT id, day, start_time FROM time_slot")}
ALL = set(SL.values())
NEXT = [900]

def new_course(cat="전공선택", year="1", sessions=2, sections=((None, 30),), single="NONE", pair="NONE",
               ok_slots=None, prefer=(), lab=0):
    """시험용 과목(가상). sections=((교수 또는 None=새 교수, 인원), ...). 응답은 분반 교수마다 하나.
    ok_slots 를 주면 그 밖의 칸은 모두 불가(BLOCK)."""
    NEXT[0] += 1; cid = NEXT[0]; profs = []
    for sec, (p, enr) in enumerate(sections, 1):
        if p is None:
            NEXT[0] += 1; p = NEXT[0]
            c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (p, "PROF", f"가상교수{p}", 1, "x"))
        profs.append(p)
        if sec == 1:
            c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
                      (cid, 1, 1, f"시험과목{cid}", p, cat, year, sessions, 1))
        c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, sec, p, enr))
    for p in dict.fromkeys(profs):
        NEXT[0] += 1; rid = NEXT[0]
        c.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref,section_pair) VALUES (?,?,?,?,?,?,?)",
                  (rid, 1, cid, p, lab, single, pair))
        for sid in (ALL - set(SL[x] for x in ok_slots)) if ok_slots else ():
            c.execute("INSERT INTO response_slot VALUES (?,?,'BLOCK')", (rid, sid))
        for x in prefer:
            c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'PREFER')", (rid, SL[x]))
    c.commit(); return cid

def resolve(cids, **kw):
    r = sc.solve(c, 1, 1, time_limit=20, previous_timetable_id=tt, free_courses=set(cids), **kw)
    return r, r["timetable_id"]

def cells(t, cid):
    return sorted(c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.start_time FROM assignment a JOIN time_slot ts ON ts.id=a.slot_id
                               WHERE a.timetable_id=? AND a.course_id=? ORDER BY 1,2,4""", (t, cid)).fetchall())

# ① 전공필수 둘(같은 1학년, 교수 다름)이 월·수 09:00 만 됨 → 둘 다 같은 칸에 놓임
two = [("월", "09:00"), ("수", "09:00")]
a = new_course("전공필수", "1", ok_slots=two); b = new_course("전공필수", "1", ok_slots=two)
r, t = resolve([a, b])
ca, cb = cells(t, a), cells(t, b)
report("① 같은 학년 전공필수, 교수가 다르면 겹쳐도 됨", len(ca) == 2 and len(cb) == 2 and {x[2:] for x in ca} == {x[2:] for x in cb},
       f"(과목{a} {[x[2:] for x in ca]}, 과목{b} {[x[2:] for x in cb]})")
report("① 검증 위반 없음", verify(c, t))

# ② 1학년 채플 = 화 12:00 (가상). 화·목 12:00 만 되는 전공필수는 화요일을 못 써서 한 회차 못 놓음, 전공선택은 둘 다 놓임
tw = [("화", "12:00"), ("목", "12:00")]
p = new_course("전공필수", "1", ok_slots=tw); q2 = new_course("전공선택", "1", ok_slots=tw)
r, t = resolve([p, q2])
cp, cq = cells(t, p), cells(t, q2)
report("② 전공필수는 채플 칸(화 12:00)에 놓지 않음", ("화", "12:00") not in [x[2:] for x in cp] and len([k for k in r["unplaced"] if k[0] == p]) == 1,
       f"(전필 {[x[2:] for x in cp]}, 못 놓음 {[k for k in r['unplaced'] if k[0] == p]})")
report("② 전공선택은 채플 칸에 놓여도 됨", len(cq) == 2, f"({[x[2:] for x in cq]})")
report("② 검증 위반 없음", verify(c, t))

# ③ 주 1회 연강 '무조건', 월 16:30·18:00·19:30 만 됨 → 16:30 시작만 가능 (18:00 시작은 금지)
mu = new_course(single="MUST", ok_slots=[("월", "16:30"), ("월", "18:00"), ("월", "19:30")])
r, t = resolve([mu])
cm = cells(t, mu)
report("③ 18:00 시작 연강 금지 → 16:30 시작", [x[3] for x in cm] == ["16:30", "18:00"], f"({[x[2:] for x in cm]})")
mu2 = new_course(single="MUST", ok_slots=[("화", "18:00"), ("화", "19:30")])
r, t = resolve([mu2])
report("③ 18:00·19:30 만 되면 못 놓음", not cells(t, mu2) and len([k for k in r["unplaced"] if k[0] == mu2]) == 1)

# ④ 19:30 을 희망한 수업: 감점이 있으면 다른 시간으로, 감점 0 이면 희망대로 19:30
lt = new_course(prefer=[("월", "19:30"), ("수", "19:30")])
r, t = resolve([lt]); on = [x[3] for x in cells(t, lt)]
r, t = resolve([lt], weights={"late": 0}); off = [x[3] for x in cells(t, lt)]
report("④ 19:30 감점: 켬이면 19:30 안 씀, 끔이면 희망대로 19:30", "19:30" not in on and off == ["19:30", "19:30"], f"(켬 {on}, 끔 {off})")

# ⑤ 4분반 과목: 교수 가 1·2반, 교수 나 3·4반. 나만 '연강' 응답 → 3·4반이 같은 요일 붙은 교시
NEXT[0] += 1; pa = NEXT[0]; NEXT[0] += 1; pb = NEXT[0]
for pp in (pa, pb):
    c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (pp, "PROF", f"가상교수{pp}", 1, "x"))
pc = new_course(sections=((pa, 30), (pa, 30), (pb, 30), (pb, 30)))
c.execute("UPDATE course_response SET section_pair='BACK_TO_BACK' WHERE course_id=? AND professor_id=?", (pc, pb)); c.commit()
_, courses, secs, *_ = sc.load_input(c, 1, 1)
report("⑤ 응답 칸 → 그 교수의 분반 3·4만 짝", courses[pc]["pairs"] == [([3, 4], "BACK_TO_BACK")] and secs[(pc, 3)]["paired"] and not secs[(pc, 1)]["paired"],
       f"({courses[pc]['pairs']})")
r, t = resolve([pc])
pos = {(s, ss): (d, per) for s, ss, d, per in c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.period_no FROM assignment a
        JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? AND a.course_id=?""", (t, pc))}
adj = all(pos[(3, ss)][0] == pos[(4, ss)][0] and abs(pos[(3, ss)][1] - pos[(4, ss)][1]) == 1 for ss in (1, 2)) if len(pos) == 8 else False
report("⑤ 3·4반 같은 요일 바로 붙은 교시", adj, f"({ {k: v for k, v in sorted(pos.items()) if k[0] >= 3} })")

# ⑥ 대안 중복 없음: 주 2회 과목 여러 개에서 대안 3개씩, 분반별 (요일, 시작) 집합이 서로 달라야 함
info = {sid: (d, st) for sid, d, st in c.execute("SELECT id, day, start_time FROM time_slot")}
targets = [cid for cid, in c.execute("""SELECT s.course_id FROM course_section s JOIN course c ON c.id=s.course_id
                                       WHERE c.id < 900 GROUP BY s.course_id HAVING COUNT(*)=1 ORDER BY s.course_id LIMIT 6""")]
dups = 0; total = 0
for cid in targets:
    alts = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10)
    sigs = [frozenset(info[v[0]] for v in a_["placements"].values()) for a_ in alts]
    cur = frozenset(info[s] for s, in c.execute("SELECT MIN(slot_id) FROM assignment WHERE timetable_id=? AND course_id=? GROUP BY session_no", (tt, cid)))
    total += len(alts); dups += len(sigs) - len(set(sigs)) + sum(1 for g in sigs if g == cur)
    print(f"   과목{cid}: 현재 {sorted(cur)} / 대안 {[sorted(g) for g in sigs]}")
report("⑥ 대안끼리·현재 배정과 같은 칸 집합 없음", dups == 0 and total > 0, f"(대안 {total}개, 중복 {dups})")

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
