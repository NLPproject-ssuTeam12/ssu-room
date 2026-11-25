"""조교 [확인]·[수정]을 새 시간표 버전으로 저장(apply_option)하고, 다음 차수가 그 버전을 기준으로 쓰는지 검사 (가상 데이터).
  ① [확인]한 B안 → 시간표가 하나 늘고 kind=TA_EDIT, parent_id=이전 버전, 사유 저장, 옮기지 않은 분반은 그대로
  ② 다음 차수 alternatives(새 버전) 의 '현재 배정'이 B안 (B안은 대안에서 빠짐), solve(previous=새 버전) 도 B안 유지
  ③ 하드 규칙 위반이 새로 생기는 안(교수 불가 칸)은 거부, 시간표는 늘지 않음
  python solver/tests/run_apply.py"""
import sys
from test_solver2 import *

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")

c = build()
base = sc.solve(c, 1, 1, time_limit=30); tt = base["timetable_id"]
print("기준:", base["status"], "못놓음", len(base["unplaced"])); report("기준 시간표 검증", verify(c, tt))
info = {sid: (d, st) for sid, d, st in c.execute("SELECT id, day, start_time FROM time_slot")}
TA = 999
c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (TA, "TA", "조교(가상)", 1, "x")); c.commit()
cid, prof = c.execute("""SELECT s.course_id, s.professor_id FROM course_section s JOIN course_response r
                          ON r.course_id=s.course_id AND r.professor_id=s.professor_id
                         WHERE (SELECT COUNT(*) FROM course_section x WHERE x.course_id=s.course_id)=1
                           AND r.single_day_pref='NONE' ORDER BY s.course_id LIMIT 1""").fetchone()
alts = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10)
pid = sc.save_proposal(c, 1, tt, cid, alts, "가상 조율", section_no=1)
opts = [o for o, in c.execute("SELECT id FROM proposal_option WHERE proposal_id=? ORDER BY option_no", (pid,))]
c.execute("UPDATE proposal SET status='PROPOSED' WHERE id=?", (pid,)); c.commit()
cells = lambda t, k: sorted(info[s] for s, in c.execute("SELECT slot_id FROM assignment WHERE timetable_id=? AND course_id=?", (t, k)))
others = lambda t: sorted(c.execute("SELECT * FROM assignment WHERE timetable_id=? AND course_id<>? ", (t, cid)).fetchall())
B = sorted(info[s] for s in sc.load_option(c, opts[1])["slots"])
print(f"대상: 과목{cid} 현재 {cells(tt, cid)}, B안 {B}")

# ① [확인] B안
n0 = c.execute("SELECT count(*) FROM timetable").fetchone()[0]
rows = sc.option_rows(c, option_id=opts[1])
nt = sc.apply_option(c, pid, TA, rows, "가상 [확인]: B안", base_timetable_id=tt)
row = c.execute("SELECT kind, parent_id, created_by, reason FROM timetable WHERE id=?", (nt,)).fetchone()
report("① 시간표가 하나 늘고 TA_EDIT, parent=이전 버전, 사유 저장",
       c.execute("SELECT count(*) FROM timetable").fetchone()[0] == n0 + 1 and row == ("TA_EDIT", tt, TA, "가상 [확인]: B안"), f"({row})")
report("① 옮긴 분반은 B안, 안건 RESOLVED", cells(nt, cid) == B and
       c.execute("SELECT status FROM proposal WHERE id=?", (pid,)).fetchone()[0] == "RESOLVED", f"({cells(nt, cid)})")
report("① 옮기지 않은 분반은 그대로", [r[1:] for r in others(nt)] == [r[1:] for r in others(tt)])
report("① 새 버전 검증 위반 없음", verify(c, nt))
#    option_rows 는 대안 dict(pick_best·alternatives 결과)에서도 같은 rows
report("① option_rows: 저장된 대안 = 대안 dict", sc.option_rows(c, option=alts[1], timetable_id=tt) == sorted(rows))

# ② 다음 차수는 새 버전 기준
nxt = sc.alternatives(c, 1, 1, nt, cid, n=3, time_limit=10, exclude_sent=False)   # 이미 보낸 안 제외는 끄고 '현재 배정' 기준만 본다
sigs = [sorted(info[st] for st, _ in a["placements"].values()) for a in nxt]
report("② 새 버전 기준 대안: 현재 배정(B안)은 대안에서 빠짐", B not in sigs and len(nxt) > 0, f"({sigs})")
old = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10, exclude_sent=False)
report("②   (옛 버전 기준이면 B안이 다시 나옴: 기준이 달라졌다는 확인)",
       B in [sorted(info[st] for st, _ in a["placements"].values()) for a in old])
rs = sc.solve(c, 1, 1, time_limit=30, previous_timetable_id=nt)
report("② solve(previous=새 버전) 는 B안을 유지", rs["timetable_id"] is not None and cells(rs["timetable_id"], cid) == B,
       f"({rs['status']}, {cells(rs['timetable_id'], cid)})")

# ③ 하드 규칙 위반이 새로 생기는 안은 거부
rid = c.execute("SELECT id FROM course_response WHERE course_id=? AND professor_id=?", (cid, prof)).fetchone()[0]
C = sc.option_rows(c, option_id=opts[2])
c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'BLOCK')", (rid, C[0][2])); c.commit()   # C안 칸을 교수가 불가로
pid2 = sc.save_proposal(c, 1, nt, cid, alts, "가상 조율 2", section_no=1)
n1 = c.execute("SELECT count(*) FROM timetable").fetchone()[0]
try:
    sc.apply_option(c, pid2, TA, C, "가상 [수정]: C안", base_timetable_id=nt); report("③ 새 위반(불가 칸)이 생기는 안은 거부", False)
except ValueError as e:
    report("③ 새 위반(불가 칸)이 생기는 안은 거부", "불가 칸" in str(e) and c.execute("SELECT count(*) FROM timetable").fetchone()[0] == n1,
           f"({str(e)[:60]}…)")

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
