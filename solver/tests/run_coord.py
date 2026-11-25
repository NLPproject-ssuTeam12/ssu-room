"""조율 대상 구분과 분반별 희망 입력 검사 (가상 데이터, 11/25).
  ① coord_targets: 못 놓음(UNPLACED) / 희망에서 어긋남(MISMATCH: 모든 회차가 희망 칸 밖 또는 희망 건물 밖) /
     일부 어긋남(PARTIAL: 일부 회차만) / 대상 아님(희망대로, 희망 칸을 안 칠함), 고정 분반은 뺌
  ② open_coord_proposals: 못 놓음·어긋남 → OPEN(자동 보냄), 일부 → HOLD(조교 선택), 대안 없음 → NO_OPTION, 두 번 불러도 한 번만
  ③ 같은 대안을 두 번 보내지 않음: 한 안건 안(요일 순서만 바뀐 안 포함)과, 같은 분반의 이전 차수(fill_options)
  ④ 희망 입력은 분반마다: 같은 교수의 두 분반이 서로 다른 희망·불가 칸을 가짐 (솔버 입력, 규칙 검사)
  ⑤ 분반 연강은 교수가 정한 분반으로: 세 분반 중 적은 순서 앞 두 분반만 붙이고 나머지는 안내, 두 분반만 적으면 그 둘만
  python solver/tests/run_coord.py"""
import sys
from test_solver2 import *
import db as hdb

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")

c = build()
base = sc.solve(c, 1, 1, time_limit=30); tt = base["timetable_id"]
print("기준:", base["status"], "못놓음", len(base["unplaced"])); report("기준 시간표 검증", verify(c, tt))
TA = 999
c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (TA, "TA", "조교(가상)", 1, "x"))
c.execute("INSERT INTO department VALUES (2,'가상학과','가상대학')")
for b in (5, 6):                                   # 시험용 건물(가상): 5 = 희망 건물, 6 = 다른 건물. 강의실 6개씩
    c.execute("INSERT INTO building VALUES (?,?)", (b, f"시험건물{b}"))
    for k in range(6):
        c.execute("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (?,?,?,?,?)", (b * 100 + k, b, f"{b}9{k}", 60, 0))
c.commit()
SL = {(d, t): i for i, d, t in c.execute("SELECT id, day, start_time FROM time_slot")}
INFO = {i: (d, t) for (d, t), i in SL.items()}
ROOM_B = dict(c.execute("SELECT id, building_id FROM room").fetchall())
NEXT = [900]


def new_course(sections, prefer=None, block=None, bld=None, cat="전공선택", year="1"):
    """시험용 과목(가상, 학과 2). sections=[교수, ...] 분반마다. prefer/block: 분반마다 칸 목록(없으면 모든 분반 같은 값)."""
    NEXT[0] += 1; cid = NEXT[0]
    for p in dict.fromkeys(sections):
        if not c.execute("SELECT 1 FROM user WHERE id=?", (p,)).fetchone():
            c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (p, "PROF", f"가상교수{p}", 2, "x"))
        if bld:
            c.execute("INSERT OR REPLACE INTO professor_building_pref VALUES (?,?)", (p, bld))
    c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, 1, 2, f"시험과목{cid}", sections[0], cat, year, 2, 1))
    for sec, p in enumerate(sections, 1):
        c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, sec, p, 30))
        NEXT[0] += 1; rid = NEXT[0]
        c.execute("INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?,?)",
                  (rid, 1, cid, sec, p, 0, "NONE"))
        pf = prefer[sec - 1] if prefer and isinstance(prefer[0], list) else (prefer or [])
        bk = block[sec - 1] if block and isinstance(block[0], list) else (block or [])
        for x in pf: c.execute("INSERT INTO response_slot VALUES (?,?,'PREFER')", (rid, SL[x]))
        for x in bk: c.execute("INSERT INTO response_slot VALUES (?,?,'BLOCK')", (rid, SL[x]))
    c.commit(); return cid


def free_room(t, slots, building=None, other_than=None):
    """시간표 t 에서 그 칸들에 비어 있는 강의실 (건물 조건)"""
    used = {r for (r,) in c.execute(f"SELECT room_id FROM assignment WHERE timetable_id=? AND slot_id IN ({','.join('?'*len(slots))})", (t, *slots))}
    for rid, b in sorted(ROOM_B.items()):
        if rid in used or (building and b != building) or (other_than and b == other_than):
            continue
        if c.execute("SELECT capacity FROM room WHERE id=?", (rid,)).fetchone()[0] >= 30:
            return rid


def place(t, cid, sec, cells):
    """cells = [((요일, 시각), 'in'|'out'), ...] 회차 순. in = 희망 건물(5), out = 다른 건물(6). -> 새 시간표"""
    rows = []
    for ss, (cell, where) in enumerate(cells, 1):
        sid = SL[cell]
        room = free_room(t, [sid], building=5) if where == "in" else free_room(t, [sid], building=6)
        rows.append((sec, ss, sid, room))
    return hdb.apply_option(c, None, None, rows, course_id=cid, base_timetable_id=t)


P = [("월", "09:00"), ("수", "09:00"), ("화", "10:30"), ("목", "10:30")]      # 희망 칸
OUT = [("금", "13:30"), ("월", "15:00")]                                        # 희망 밖 (서로 다른 요일)
# ① 시험 과목 (교수 희망 건물 = 시험건물 5)
k_ok = new_course([801], prefer=P, bld=5)
k_part_t = new_course([802], prefer=P, bld=5)
k_mis_t = new_course([803], prefer=P, bld=5)
k_mis_b = new_course([804], prefer=P, bld=5)
k_part_b = new_course([805], prefer=P, bld=5)
k_nopref = new_course([806], bld=None)                                         # 희망 칸·희망 건물 없음
k_un = new_course([807], prefer=P, bld=5)
t = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=tt, free_courses={k_ok, k_part_t, k_mis_t, k_mis_b, k_part_b, k_nopref, k_un})["timetable_id"]
t = place(t, k_ok, 1, [(P[0], "in"), (P[1], "in")])
t = place(t, k_part_t, 1, [(P[2], "in"), (OUT[0], "in")])
t = place(t, k_mis_t, 1, [(OUT[0], "in"), (OUT[1], "in")])
t = place(t, k_mis_b, 1, [(P[0], "out"), (P[1], "out")])
t = place(t, k_part_b, 1, [(P[2], "in"), (P[3], "out")])
t = place(t, k_nopref, 1, [(OUT[0], "out"), (OUT[1], "out")])
c.execute("DELETE FROM assignment WHERE timetable_id=? AND course_id=? AND session_no=2", (t, k_un)); c.commit()   # 한 회차를 못 놓은 상태
tg = {(x["course_id"], x["section_no"]): x for x in sc.coord_targets(c, 1, 1, t)}
kind = lambda k: tg.get((k, 1), {}).get("kind")
report("① 희망대로 → 대상 아님", kind(k_ok) is None)
report("① 한 회차만 희망 칸 밖 → 일부 어긋남", kind(k_part_t) == "PARTIAL", f"({tg.get((k_part_t, 1), {}).get('reason')})")
report("① 두 회차 모두 희망 칸 밖 → 어긋남", kind(k_mis_t) == "MISMATCH")
report("① 희망 칸이지만 두 회차 모두 다른 건물 → 어긋남", kind(k_mis_b) == "MISMATCH", f"({tg.get((k_mis_b, 1), {}).get('reason')})")
report("① 한 회차만 다른 건물 → 일부 어긋남", kind(k_part_b) == "PARTIAL")
report("① 희망 칸·희망 건물이 없으면 대상 아님", kind(k_nopref) is None)
report("① 한 회차를 못 놓음 → 못 놓음", kind(k_un) == "UNPLACED")
order = [x["kind"] for x in sc.coord_targets(c, 1, 1, t)]
report("① 못 놓음 → 어긋남 → 일부 순서", order == sorted(order, key=["UNPLACED", "MISMATCH", "PARTIAL"].index))
c.execute("UPDATE timetable_section SET locked=1 WHERE timetable_id=? AND course_id=?", (t, k_mis_t)); c.commit()
report("① 고정된 분반은 뺌", (k_mis_t, 1) not in {(x["course_id"], x["section_no"]) for x in sc.coord_targets(c, 1, 1, t)})
c.execute("UPDATE timetable_section SET locked=0 WHERE timetable_id=? AND course_id=?", (t, k_mis_t)); c.commit()

# ② 안건 열기: 시험 과목만 (빠르게)
FRI = [("금", "13:30"), ("금", "15:00")]
k_none = new_course([808], prefer=[], block=[x for x in SL if x not in FRI], bld=5)   # 금 13:30·15:00 만 됨 → 하루에 두 번 못 하므로 한 회차는 못 놓음
r0 = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=t, free_courses={k_none}); print("   k_none 풀이:", r0["status"], r0["unplaced"]); t = r0["timetable_id"]
c.execute("DELETE FROM assignment WHERE timetable_id=? AND course_id=? AND session_no=2", (t, k_un)); c.commit()   # 다시 한 회차를 못 놓은 상태로
mine = [x for x in sc.coord_targets(c, 1, 1, t) if x["course_id"] in (k_un, k_mis_t, k_part_t)]
tg_none = [x for x in sc.coord_targets(c, 1, 1, t) if x["course_id"] == k_none]
opened = sc.open_coord_proposals(c, 1, 1, t, n=3, time_limit=10, targets=mine + tg_none)
st = {o["course_id"]: (o["kind"], o["status"], o["options"]) for o in opened}
print("   안건:", st)
report("② 못 놓음 → OPEN, 대안 있음", st[k_un][1] == "OPEN" and st[k_un][2] >= 1)
report("② 어긋남 → OPEN", st[k_mis_t][:2] == ("MISMATCH", "OPEN") and st[k_mis_t][2] >= 1)
report("② 일부 어긋남 → HOLD (보내지 않음)", st[k_part_t][:2] == ("PARTIAL", "HOLD"))
report("② 대안이 없으면 → NO_OPTION", tg_none and st.get(k_none, (None, None, None))[1:] == ("NO_OPTION", 0), f"({st.get(k_none)})")
report("② 두 번 불러도 다시 열지 않음", sc.open_coord_proposals(c, 1, 1, t, targets=mine + tg_none) == [])
pid_none = [o["proposal_id"] for o in opened if o["course_id"] == k_none][0]
hdb.ack_no_option(c, pid_none, TA)
report("② 대안 없음 확인 → 따로 연락(OFFLINE)", c.execute("SELECT status FROM proposal WHERE id=?", (pid_none,)).fetchone()[0] == "OFFLINE")
pid_hold = [o["proposal_id"] for o in opened if o["course_id"] == k_part_t][0]
hdb.release_hold(c, pid_hold, TA, send=True)
report("② 조교가 고른 일부 어긋남 → OPEN", c.execute("SELECT status FROM proposal WHERE id=?", (pid_hold,)).fetchone()[0] == "OPEN")

# ③ 같은 대안을 두 번 보내지 않음
def sigs(pid):
    out = []
    for (oid,) in c.execute("SELECT id FROM proposal_option WHERE proposal_id=? ORDER BY option_no", (pid,)).fetchall():
        out.append(frozenset(sc.load_option(c, oid)["slots"]))
    return out
pid_mis = [o["proposal_id"] for o in opened if o["course_id"] == k_mis_t][0]
s1 = sigs(pid_mis)
report("③ 한 안건 안에서 같은 칸 묶음 없음(요일 순서만 바뀐 안 포함)", len(set(s1)) == len(s1), f"({[sorted(INFO[x] for x in s) for s in s1]})")
c.execute("UPDATE proposal SET status='NEXT' WHERE id=?", (pid_mis,))                    # 보냈고 다음 차수로 넘김 (가상)
c.execute("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (2,1,2,'2026-12-08')"); c.commit()
p2 = hdb.open_next_proposal(c, pid_mis, 2)
n2 = sc.fill_options(c, p2, n=3, time_limit=10)
s2 = sigs(p2)
report("③ 다음 차수 대안은 이전 차수에 보낸 안과 겹치지 않음", n2 >= 1 and not (set(s1) & set(s2)),
       f"(1차 {[sorted(INFO[x] for x in s) for s in s1]} / 2차 {[sorted(INFO[x] for x in s) for s in s2]})")
report("③ 다음 차수 안건은 조율 대상 종류를 이어받음", c.execute("SELECT target_kind FROM proposal WHERE id=?", (p2,)).fetchone()[0] == "MISMATCH")
again = sc.alternatives(c, 1, 2, t, k_mis_t, 1, n=3, time_limit=10, exclude_sent=False)
report("③ exclude_sent=False 면 이전 안도 다시 나올 수 있음(pick_best 용)", isinstance(again, list))

# ④ 분반마다 다른 희망: 같은 교수 두 분반, 1분반은 월·수 09:00 희망, 2분반은 화·목 15:00 희망·월·수 09:00 불가
k_sec = new_course([811, 811], prefer=[[P[0], P[1]], [("화", "15:00"), ("목", "15:00")]],
                   block=[[], [P[0], P[1]]], bld=5)
_, courses, secs, *_ = sc.load_input(c, 1, 1)
report("④ 솔버 입력: 분반마다 다른 희망 칸", secs[(k_sec, 1)]["prefer"] == {SL[P[0]], SL[P[1]]} and secs[(k_sec, 2)]["prefer"] == {SL[("화", "15:00")], SL[("목", "15:00")]})
r = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=t, free_courses={k_sec}); t4 = r["timetable_id"]
got = {s: sorted(INFO[x] for (x,) in c.execute("SELECT slot_id FROM assignment WHERE timetable_id=? AND course_id=? AND section_no=?", (t4, k_sec, s)))
       for s in (1, 2)}
report("④ 각 분반이 자기 희망 칸에", got[1] == sorted([P[0], P[1]]) and got[2] == [("목", "15:00"), ("화", "15:00")], f"({got})")
rows = [(2, 1, SL[P[0]], free_room(t4, [SL[P[0]]])), (2, 2, SL[P[1]], free_room(t4, [SL[P[1]]]))]
c.execute("DELETE FROM assignment WHERE timetable_id=? AND course_id=? AND section_no=1", (t4, k_sec)); c.commit()   # 교수 겹침은 빼고 불가 칸만 보려고
t4b = hdb.apply_option(c, None, None, rows, course_id=k_sec, base_timetable_id=t4)
bad = [v for v in sc.check_timetable(c, t4b) if v["rule"] == "불가 칸" and v["course_id"] == k_sec]
report("④ 규칙 검사: 2분반만 불가 칸 위반", bad and all(v["section_no"] == 2 for v in bad), f"({bad})")

# ⑤ 분반 연강: 교수 하나가 세 분반
k_tri = new_course([821, 821, 821])
hdb.set_pair_request(c, 1, k_tri, 821, "BACK_TO_BACK", [3, 1, 2])
r = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=tt, free_courses={k_tri}); t5 = r["timetable_id"]
pos = {(s, ss): (d, per) for s, ss, d, per in c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.period_no FROM assignment a
        JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? AND a.course_id=?""", (t5, k_tri))}
adj = lambda a, b: all(pos[(a, ss)][0] == pos[(b, ss)][0] and abs(pos[(a, ss)][1] - pos[(b, ss)][1]) == 1 for ss in (1, 2))
msg = [m for k, m in r["unsupported"] if k == k_tri]
report("⑤ 세 분반 연강 요청 → 적은 순서 앞 두 분반(3·1)만 붙임", len(pos) == 6 and adj(3, 1), f"({sorted(pos.items())})")
report("⑤ 셋째 분반(2)은 조교가 수동 배치·고정하라고 안내", any("나머지 분반(2)" in m and "수동" in m for m in msg), f"({msg})")
hdb.set_pair_request(c, 1, k_tri, 821, "BACK_TO_BACK", [2, 3])                       # 두 분반만 붙이고 1분반은 떨어뜨림
r = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=tt, free_courses={k_tri}); t5 = r["timetable_id"]
pos = {(s, ss): (d, per) for s, ss, d, per in c.execute("""SELECT a.section_no, a.session_no, ts.day, ts.period_no FROM assignment a
        JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? AND a.course_id=?""", (t5, k_tri))}
_, courses, secs, *_ = sc.load_input(c, 1, 1)
report("⑤ 두 분반(2·3)만 적으면 그 둘만 붙이고 안내 없음", len(pos) == 6 and adj(2, 3) and not secs[(k_tri, 1)]["paired"]
       and not [m for k, m in r["unsupported"] if k == k_tri], f"({courses[k_tri]['pairs']})")

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
