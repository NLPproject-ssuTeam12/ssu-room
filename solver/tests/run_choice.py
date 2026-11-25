"""교수 답장 선택(A·B·C·기타)과 수동 배치 고정 검사 (가상 데이터).
  ① pick_best: 고른 안 여러 개 → 점수 좋은 순, 지금 놓을 수 없는 안은 feasible=False
     교수가 글로 순서를 밝히면(respect_order) 점수보다 그 순서, 앞 순서 안을 못 놓으면 다음 순서
  ② 기타 조건 → 조건에 맞는 새 안(ETC)도 함께 비교, add_option 으로 저장·load_option 으로 다시 읽기
  ③ 따로 연락 → manual_place(규칙을 어겨도 저장) → check_timetable 경고 → 고정은 부분·전체 재풀이에서 그대로, 대안은 거부
  python solver/tests/run_choice.py"""
import sys
from test_solver2 import *
import db as hdb

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")

c = build()
base = sc.solve(c, 1, 1, time_limit=30); tt = base["timetable_id"]
print("기준:", base["status"], "못놓음", len(base["unplaced"])); report("기준 시간표 검증", verify(c, tt))
info = {sid: (d, st) for sid, d, st in c.execute("SELECT id, day, start_time FROM time_slot")}
TA = 999
c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (TA, "TA", "조교(가상)", 1, "x")); c.commit()

# 대상: 응답한 교수의 분반 하나짜리 과목 (주 2회), 그 교수가 다른 과목도 맡음
cid, prof, other = c.execute("""SELECT s.course_id, s.professor_id, (SELECT MIN(s2.course_id) FROM course_section s2
                                       WHERE s2.professor_id=s.professor_id AND s2.course_id<>s.course_id)
                                FROM course_section s JOIN course_response r ON r.course_id=s.course_id AND r.professor_id=s.professor_id
                                WHERE (SELECT COUNT(*) FROM course_section x WHERE x.course_id=s.course_id)=1
                                  AND r.single_day_pref='NONE'
                                  AND EXISTS (SELECT 1 FROM course_section s2 WHERE s2.professor_id=s.professor_id AND s2.course_id<>s.course_id)
                                ORDER BY s.course_id LIMIT 1""").fetchone()
print(f"대상: 과목{cid} (교수 {prof}, 같은 교수의 다른 과목 {other})")
alts = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10)
pid = sc.save_proposal(c, 1, tt, cid, alts, "가상 조율", section_no=1)
opts = [o for o, in c.execute("SELECT id FROM proposal_option WHERE proposal_id=? ORDER BY option_no", (pid,))]
cells = lambda o: sorted(info[s] for s in sc.load_option(c, o)["slots"])
print("   대안:", [cells(o) for o in opts])

# ① 고른 안 여러 개
r1 = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=opts[:3], time_limit=10)
objs = [x["objective"] for x in r1]
report("① 고른 안 셋 모두 놓을 수 있고 점수 좋은 순", all(x["feasible"] for x in r1) and objs == sorted(objs),
       f"({[(x['source'], x['objective']) for x in r1]})")
report("① 고른 안의 칸 그대로", all(sorted(info[sl] for (sec, ss), (st, _) in x["placements"].items()
                                           for sl in sc._covered(st, x["ks"][(sec, ss)], {d: sorted(p) for d, p in sc.load_input(c, 1, 1)[0].items()}))
                                  == cells(x["option_id"]) for x in r1))
rid = c.execute("SELECT id FROM course_response WHERE course_id=? AND professor_id=?", (cid, prof)).fetchone()[0]
#    B안 칸을 교수가 희망으로 칠함 → B안 점수가 가장 좋음 (희망 칸 보너스)
saved = c.execute("SELECT slot_id, kind FROM response_slot WHERE response_id=?", (rid,)).fetchall()
for sl in sc.load_option(c, opts[1])["slots"]:
    c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'PREFER')", (rid, sl))
c.commit()
r1p = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=opts[:3], time_limit=10)
report("① 희망 칸이 많은 B안이 점수가 가장 좋아 맨 앞", r1p[0]["option_id"] == opts[1] and r1p[0]["objective"] < r1p[1]["objective"],
       f"({[(x['source'], x['objective']) for x in r1p]})")
#    교수가 "A가 제일 좋고 안 되면 B" → 점수는 B가 좋아도 A가 먼저
r1o = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=[opts[0], opts[1]], time_limit=10, respect_order=True)
report("① 교수가 밝힌 순서(A→B)가 점수(B)보다 먼저", [x["option_id"] for x in r1o] == [opts[0], opts[1]] and r1o[0]["objective"] > r1o[1]["objective"],
       f"({[(x['source'], x['objective']) for x in r1o]})")
#    A안 칸을 불가로 칠해 A를 못 놓게 하면 → 다음 순서 B
asl = sorted(sc.load_option(c, opts[0])["slots"])[0]
c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'BLOCK')", (rid, asl)); c.commit()
r1q = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=[opts[0], opts[1]], time_limit=10, respect_order=True)
report("① 앞 순서(A)를 못 놓으면 다음 순서(B)", r1q[0]["option_id"] == opts[1] and r1q[0]["feasible"] and not r1q[1]["feasible"],
       f"({[(x['source'], x['feasible']) for x in r1q]})")
#    기타 조건 새 안은 밝힌 순서 뒤 (점수가 더 좋아도)
r1e = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=[opts[1]], condition={"day_slots": {"3": []}, "end_before": []},
                   time_limit=10, respect_order=True)
report("① 순서 모드에서 기타 조건 새 안(ETC)은 밝힌 순서 뒤", [x["source"] for x in r1e] == ["B", "ETC"], f"({[(x['source'], x['objective']) for x in r1e]})")
c.execute("DELETE FROM response_slot WHERE response_id=?", (rid,))
c.executemany("INSERT INTO response_slot VALUES (?,?,?)", [(rid, sl, k) for sl, k in saved]); c.commit()
#    C안 칸 하나를 교수가 불가로 칠함 → C안은 지금 놓을 수 없음
csl = sorted(sc.load_option(c, opts[2])["slots"])[0]
c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'BLOCK')", (rid, csl)); c.commit()
r1b = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=opts[:3], time_limit=10)
bad = [x for x in r1b if x["option_id"] == opts[2]][0]
report("① 지금 놓을 수 없는 안은 feasible=False, 맨 뒤", not bad["feasible"] and r1b[-1] is bad and all(x["feasible"] for x in r1b[:-1]),
       f"({[(x['source'], x['feasible']) for x in r1b]})")
c.execute("DELETE FROM response_slot WHERE response_id=? AND slot_id=?", (rid, csl)); c.commit()

# ② 기타 조건(목요일 아무 교시나)으로 새 안
cond = {"day_slots": {"3": []}, "end_before": []}
r2 = sc.pick_best(c, 1, 1, tt, cid, 1, option_ids=[opts[0]], condition=cond, time_limit=10)
etc = [x for x in r2 if x["source"] == "ETC"]
report("② 기타 조건으로 만든 새 안이 함께 비교됨", len(etc) == 1 and etc[0]["feasible"] and etc[0]["option_id"] is None
       and any(info[st][0] == "목" for st, _ in etc[0]["placements"].values()),
       f"({[(x['source'], x['objective']) for x in r2]})")
new_oid = sc.add_option(c, pid, etc[0])
lo = sc.load_option(c, new_oid)
report("② add_option → 4번 대안으로 저장, load_option 으로 같은 칸", lo["option_no"] == 4 and lo["placements"] == etc[0]["placements"],
       f"(번호 {lo['option_no']})")

# ③ 따로 연락 → 수동 배치: 같은 교수의 다른 과목과 같은 칸에 (교수 겹침, 규칙 위반이지만 저장)
S = {(d, st): i for i, (d, st) in info.items()}
osl = [s for s, in c.execute("SELECT DISTINCT slot_id FROM assignment WHERE timetable_id=? AND course_id=? ORDER BY slot_id", (tt, other))][:2]
rows = []
for k, sl in enumerate(osl, 1):
    room = c.execute("SELECT id FROM room WHERE is_lab=0 AND capacity>=? AND id NOT IN (SELECT room_id FROM assignment WHERE timetable_id=? AND slot_id=?) ORDER BY id",
                     (c.execute("SELECT enrollment FROM course_section WHERE course_id=?", (cid,)).fetchone()[0], tt, sl)).fetchone()[0]
    rows.append((1, k, sl, room))
c.execute("UPDATE proposal SET status='OFFLINE' WHERE id=?", (pid,)); c.commit()      # (조교가 [따로 연락]을 누른 상태)
mt = hdb.manual_place(c, pid, TA, rows)
warn = sc.check_timetable(c, mt)
report("③ 수동 배치는 규칙을 어겨도 저장, check_timetable 이 경고", any(w["rule"] == "교수 겹침" for w in warn), f"({[w['rule'] for w in warn]})")
report("③ 수동 배치 분반은 MANUAL·고정", c.execute("SELECT status, locked FROM timetable_section WHERE timetable_id=? AND course_id=?", (mt, cid)).fetchone() == ("MANUAL", 1))
placed = lambda t, k: sorted(c.execute("SELECT session_no, slot_id, room_id FROM assignment WHERE timetable_id=? AND course_id=?", (t, k)).fetchall())
want = sorted((ss, sl, rm) for _, ss, sl, rm in rows)
#    부분 재풀이: 고정 과목을 free 에 넣어도 그대로 (교수 겹침이 고정끼리라 풀이가 막히지 않아야 함)
rp = sc.solve(c, 1, 1, time_limit=20, previous_timetable_id=mt, free_courses={cid})
report("③ 부분 재풀이(고정 과목을 풀어 달라고 해도)에서 그대로", rp["timetable_id"] is not None and placed(rp["timetable_id"], cid) == want,
       f"({rp['status']})")
#    전체 재풀이: 고정 과목은 그대로, 겹친 다른 과목이 비켜남
rf = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=mt, free_courses=None)
tf = rf["timetable_id"]
report("③ 전체 재풀이에서도 그대로, 고정 표시도 이어짐", tf is not None and placed(tf, cid) == want
       and c.execute("SELECT status, locked FROM timetable_section WHERE timetable_id=? AND course_id=?", (tf, cid)).fetchone() == ("MANUAL", 1),
       f"({rf['status']})")
report("③ 전체 재풀이 뒤 교수 겹침이 풀림(다른 과목이 비켜남)", not [w for w in sc.check_timetable(c, tf) if w["rule"] == "교수 겹침"],
       f"({[w['rule'] for w in sc.check_timetable(c, tf)]})")
try:
    sc.alternatives(c, 1, 1, tf, cid, n=1, time_limit=5); report("③ 고정 분반은 대안을 만들지 않음", False)
except ValueError as e:
    report("③ 고정 분반은 대안을 만들지 않음", "고정" in str(e))
hdb.set_lock(c, tf, cid, 1, False)
report("③ 고정을 풀면 다시 대안을 만듦", len(sc.alternatives(c, 1, 1, tf, cid, n=1, time_limit=10)) == 1)

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
