"""11/24 규칙 검사 (가상 데이터).
  ① 같은 학년 서로 다른 전공필수는 겹치지 않음. 둘 다 분반이 둘 이상이면 분반마다 안 겹치는 상대 분반이 있으면 일부 겹쳐도 됨.
     같은 과목에서 교수가 다른 분반끼리는 겹쳐도 됨
  ② 전공필수는 그 학년 채플 칸에 놓지 않음
  ③ 18:00 이후 시작 연강 금지                       ④ 19:30 교시는 큰 감점
  ⑤ 분반 연강·교차는 교수 입력(pair_request)으로, 그 교수의 두 분반(3·4번이어도)에
  ⑥ 대안에 회차 순서만 바뀐 같은 안이 나오지 않음
  ⑦ 같은 학년 교양필수↔전공필수는 겹치지 않음, 학년이 다르면(2학년 전필↔1학년 교필) 겹쳐도 됨
기준 시간표를 한 번 풀고, 시험용 과목(가상)만 free_courses 로 다시 푼다.
  python solver/tests/run_rules.py"""
import sys
from test_solver2 import *
import db as hdb

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
               ok_slots=None, prefer=(), lab=0, dept=1, sec_ok=None):
    """시험용 과목(가상). sections=((교수 또는 None=새 교수, 인원), ...). 응답은 분반 교수마다 하나.
    ok_slots 를 주면 그 밖의 칸은 모두 불가(BLOCK). sec_ok 를 주면 분반(=그 분반 교수)마다 되는 칸."""
    NEXT[0] += 1; cid = NEXT[0]; profs = []
    for sec, (p, enr) in enumerate(sections, 1):
        if p is None:
            NEXT[0] += 1; p = NEXT[0]
            c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (p, "PROF", f"가상교수{p}", 1, "x"))
        profs.append(p)
        if sec == 1:
            c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
                      (cid, 1, dept, f"시험과목{cid}", p, cat, year, sessions, 1))
        c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, sec, p, enr))
    order = list(dict.fromkeys(profs))
    for sec, p in enumerate(profs, 1):              # 희망 입력은 분반마다 (11/25). 같은 교수의 분반은 같은 값
        NEXT[0] += 1; rid = NEXT[0]
        ok = sec_ok[order.index(p)] if sec_ok else ok_slots
        c.execute("INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?,?)",
                  (rid, 1, cid, sec, p, {1: "MUST", 0: "NONE"}.get(lab, lab), single))
        for sid in (ALL - set(SL[x] for x in ok)) if ok else ():
            c.execute("INSERT INTO response_slot VALUES (?,?,'BLOCK')", (rid, sid))
        for x in prefer:
            c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'PREFER')", (rid, SL[x]))
    if pair != "NONE":
        for p in order:
            if profs.count(p) >= 2:
                hdb.set_pair_request(c, 1, cid, p, pair)
    c.commit(); return cid

def resolve(cids, **kw):
    r = sc.solve(c, 1, 1, time_limit=20, previous_timetable_id=tt, free_courses=set(cids), **kw)
    return r, r["timetable_id"]

def cells(t, cid):
    return sorted(c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.start_time FROM assignment a JOIN time_slot ts ON ts.id=a.slot_id
                               WHERE a.timetable_id=? AND a.course_id=? ORDER BY 1,2,4""", (t, cid)).fetchall())

# ① 전공필수끼리 (시험 과목은 가상 학과 2, 1학년. 기준 시간표의 학과 1 필수과목과 섞이지 않게. 경우마다 다른 칸)
c.execute("INSERT INTO department VALUES (2,'가상학과','가상대학')"); c.commit()
two = [("월", "09:00"), ("수", "09:00")]
#   ①-1 분반 하나짜리 둘(교수 다름), 두 칸만 됨 → 같은 칸에 함께 못 놓임
a = new_course("전공필수", "1", ok_slots=two, dept=2); b = new_course("전공필수", "1", ok_slots=two, dept=2)
r, t = resolve([a, b])
ca, cb = cells(t, a), cells(t, b)
report("① 분반 하나인 전필 둘은 겹치지 않음", not ({x[2:] for x in ca} & {x[2:] for x in cb}) and len(ca) + len(cb) == 2,
       f"(과목{a} {[x[2:] for x in ca]}, 과목{b} {[x[2:] for x in cb]})")
report("① 검증 위반 없음", verify(c, t))
P1, P2, P3 = [("월", "10:30"), ("수", "10:30")], [("화", "10:30"), ("목", "10:30")], [("수", "16:30"), ("금", "16:30")]
def same(x, y): return bool({k[2:] for k in x} & {k[2:] for k in y})
#   ①-2 분반 둘짜리 두 과목(분반마다 교수 다름). 1반은 둘 다 P1만, 2반은 둘 다 P2만 → A1↔B1, A2↔B2 겹치지만
#       A1↔B2, A2↔B1은 안 겹침 → 분반마다 피할 길이 있어 허용, 모두 놓임
m1 = new_course("전공필수", "1", sections=((None, 30), (None, 30)), sec_ok=[P1, P2], dept=2)
m2 = new_course("전공필수", "1", sections=((None, 30), (None, 30)), sec_ok=[P1, P2], dept=2)
r, t = resolve([m1, m2])
sec = lambda cid, s: [x for x in cells(t, cid) if x[0] == s]
ok12 = (len(cells(t, m1)) == 4 and len(cells(t, m2)) == 4 and same(sec(m1, 1), sec(m2, 1)) and same(sec(m1, 2), sec(m2, 2))
        and not same(sec(m1, 1), sec(m2, 2)) and not same(sec(m1, 2), sec(m2, 1)))
report("① 분반 둘 이상끼리는 분반마다 피할 길이 있으면 일부 겹쳐도 됨", ok12,
       f"(A1 {[x[2:] for x in sec(m1, 1)]}, B1 {[x[2:] for x in sec(m2, 1)]}, A2 {[x[2:] for x in sec(m1, 2)]}, B2 {[x[2:] for x in sec(m2, 2)]})")
report("① 검증 위반 없음 (일부 겹침)", verify(c, t))
#   ①-3 분반 둘짜리 두 과목이 모두 P3만 됨 → 모든 분반이 서로 겹쳐 피할 길이 없음 → 다 놓을 수 없음
m4 = new_course("전공필수", "1", sections=((None, 30), (None, 30)), ok_slots=P3, dept=2)
m5 = new_course("전공필수", "1", sections=((None, 30), (None, 30)), ok_slots=P3, dept=2)
r, t = resolve([m4, m5])
miss = len([k for k in r["unplaced"] if k[0] in (m4, m5)])
report("① 분반마다 피할 길이 없으면 함께 못 놓음", miss > 0, f"(못 놓은 회차 {miss})")
report("① 검증 위반 없음 (피할 길 없음)", verify(c, t))
#   ①-4 분반 하나짜리 + 분반 둘짜리, 둘 다 P2만 → 분반 하나인 쪽은 어떤 분반과도 못 겹침
t14 = [("화", "16:30"), ("목", "16:30")]
s1 = new_course("전공필수", "1", ok_slots=t14, dept=2)
m3 = new_course("전공필수", "1", sections=((None, 30), (None, 30)), ok_slots=t14, dept=2)
r, t = resolve([s1, m3])
cs1, cm3 = cells(t, s1), cells(t, m3)
report("① 분반 하나인 전필은 분반 둘인 전필과도 겹치지 않음", not same(cs1, cm3),
       f"(분반 하나 {[x[2:] for x in cs1]}, 분반 둘 {sorted({x[2:] for x in cm3})}, 못 놓은 회차 {len([k for k in r['unplaced'] if k[0] in (s1, m3)])})")
report("① 검증 위반 없음 (분반 하나·둘)", verify(c, t))
#   ①-5 한 과목, 분반 둘을 교수가 다르게 → 같은 칸이어도 됨
t15 = [("월", "13:30"), ("수", "13:30")]
w = new_course("전공필수", "1", sections=((None, 30), (None, 30)), ok_slots=t15, dept=2)
r, t = resolve([w])
report("① 같은 과목, 교수가 다른 분반끼리는 겹쳐도 됨", len(cells(t, w)) == 4 and same(sec(w, 1), sec(w, 2)),
       f"({[x for x in cells(t, w)]})")

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
hdb.set_pair_request(c, 1, pc, pb, "BACK_TO_BACK")
_, courses, secs, *_ = sc.load_input(c, 1, 1)
report("⑤ 응답 칸 → 그 교수의 분반 3·4만 짝", courses[pc]["pairs"] == [([3, 4], "BACK_TO_BACK")] and secs[(pc, 3)]["paired"] and not secs[(pc, 1)]["paired"],
       f"({courses[pc]['pairs']})")
r, t = resolve([pc])
pos = {(s, ss): (d, per) for s, ss, d, per in c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.period_no FROM assignment a
        JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? AND a.course_id=?""", (t, pc))}
adj = all(pos[(3, ss)][0] == pos[(4, ss)][0] and abs(pos[(3, ss)][1] - pos[(4, ss)][1]) == 1 for ss in (1, 2)) if len(pos) == 8 else False
report("⑤ 3·4반 같은 요일 바로 붙은 교시", adj, f"({ {k: v for k, v in sorted(pos.items()) if k[0] >= 3} })")

# ⑦ 교필↔전필: 두 칸만 되는 1학년 교필 + 1학년 전필 → 같은 칸에 함께 못 놓음 (한쪽은 못 놓음)
#              1학년 교필 + 2학년 전필 → 둘 다 같은 칸에 놓임
# 시험 과목은 가상 학과 2에 둔다 (규칙은 같은 학과 안에서만 → 기준 시간표의 학과 1 필수과목과 섞이지 않음). 경우마다 다른 칸
t7a, t7b, t7c = [("화", "13:30"), ("목", "13:30")], [("화", "15:00"), ("목", "15:00")], [("월", "15:00"), ("수", "15:00")]
g1 = new_course("교양필수", "1", ok_slots=t7a, dept=2); j1 = new_course("전공필수", "1", ok_slots=t7a, dept=2)
r, t = resolve([g1, j1])
cg, cj = cells(t, g1), cells(t, j1)
both = {x[2:] for x in cg} & {x[2:] for x in cj}
report("⑦ 같은 학년 교필↔전필은 같은 칸에 못 놓임", not both and len(cg) + len(cj) == 2,
       f"(교필 {[x[2:] for x in cg]}, 전필 {[x[2:] for x in cj]}, 못 놓은 회차 {len([k for k in r['unplaced'] if k[0] in (g1, j1)])})")
report("⑦ 검증 위반 없음", verify(c, t))
g2 = new_course("교양필수", "1", ok_slots=t7b, dept=2); j2 = new_course("전공필수", "2", ok_slots=t7b, dept=2)
r, t = resolve([g2, j2])
cg, cj = cells(t, g2), cells(t, j2)
report("⑦ 1학년 교필 ↔ 2학년 전필은 같은 칸에 놓여도 됨", len(cg) == 2 and len(cj) == 2 and {x[2:] for x in cg} == {x[2:] for x in cj},
       f"(교필 {[x[2:] for x in cg]}, 전필 {[x[2:] for x in cj]})")
g3 = new_course("교양필수", "1", ok_slots=t7c, dept=2); g4 = new_course("교양필수", "1", ok_slots=t7c, dept=2)
r, t = resolve([g3, g4])
report("⑦ 교필끼리는 겹쳐도 됨", len(cells(t, g3)) == 2 and len(cells(t, g4)) == 2)

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
