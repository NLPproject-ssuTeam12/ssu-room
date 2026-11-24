"""확인된 조건(confirmed conditions) 흐름 검사 (가상 데이터).
교수 답장 → 해석 저장 → 조교 [확인]/[수정]으로 조건 저장(decide_reply) → confirmed_conditions 로 읽기
→ alternatives(condition=...)에 그대로 넘기기 → 대안이 조건을 지키는지.
조건이 없으면 confirmed_conditions 는 None 이고, None 을 넘기면 조건 없이 만든 대안과 같아야 한다.
  python solver/tests/run_cc.py"""
import copy, sys
from test_solver2 import *          # build, verify, sc (경로 설정은 test_data가 한다)
import db as hdb                     # db/db.py

c = build()
r = sc.solve(c, 1, 1, time_limit=30); tt = r["timetable_id"]
print("1차:", r["status"], "못놓음", len(r["unplaced"])); ok = verify(c, tt)
info = {sid: (d, st) for sid, d, st in c.execute("select id, day, start_time from time_slot")}
DAYN = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4}
ENDS = {st: en for st, en in c.execute("select distinct start_time, end_time from time_slot")}
pos = lambda sid: (DAYN[info[sid][0]], info[sid][1])
prev = sc.load_assignment(c, tt)[0]

TA = 999
c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (TA, "TA", "조교(가상)", 1, "x"))
c.commit()


def target():
    """분반 하나, 주 2회 × 1칸으로 놓인 과목 하나 (run_ds 와 같은 기준)."""
    for (cid, sec, ss) in prev:
        if sec != 1:
            continue
        if c.execute("select count(distinct section_no) from assignment where timetable_id=? and course_id=?", (tt, cid)).fetchone()[0] != 1:
            continue
        if c.execute("select count(distinct session_no) from assignment where timetable_id=? and course_id=?", (tt, cid)).fetchone()[0] == 2:
            return cid
    return None


def open_proposal(cid, sec=1):
    """조율 안건 + 조교가 보낸 조율 메시지(가상). -> (안건 id, 담당 교수 id)"""
    prof = c.execute("SELECT COALESCE((SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?),"
                     " (SELECT professor_id FROM course WHERE id=?))", (cid, sec, cid)).fetchone()[0]
    pid = c.execute("INSERT INTO proposal(round_id,timetable_id,course_id,section_no,reason,status) VALUES (1,?,?,?,'가상 조율','SENT')",
                    (tt, cid, sec)).lastrowid
    c.execute("INSERT INTO message(round_id,proposal_id,sender_id,receiver_id,kind,channel,body,sent_at) "
              "VALUES (1,?,?,?,'ALTERNATIVE','APP','1차 조율 안내(가상)',datetime('now'))", (pid, TA, prof))
    c.commit()
    return pid, prof


def cells_of(alts):
    return [[pos(v[0]) for v in a["placements"].values()] for a in alts]


def end_of(d, t, k=1):
    """시작 칸 (요일, 시각)에서 k칸 수업이 끝나는 시각."""
    sids = sorted(s for s, (dd, st) in info.items() if DAYN[dd] == d)
    starts = [info[s][1] for s in sids]
    i = starts.index(t)
    return ENDS[starts[i + k - 1]]


def satisfies(cond, row):
    """한 대안(회차들의 (요일, 시작))이 조건을 지키는지. day_slots 규칙은 SOLVER_API.md 와 같다."""
    ds = {int(k): v for k, v in cond.get("day_slots", {}).items()}
    days = [d for d, _ in row]
    if ds:
        if len(ds) == 1:
            (d0,) = ds
            if d0 not in days:
                return False
        elif not all(d in ds for d in days):
            return False
        if not all(not ds.get(d) or t in ds[d] for d, t in row if d in ds):
            return False
    for e in cond.get("end_before", []):
        if any(d == e["day"] and end_of(d, t) > e["time"] for d, t in row):
            return False
    return True


cid = target(); print("대상(주 2회, 가상):", cid, "현재:", [pos(v[0]) for k, v in prev.items() if k[0] == cid])
if cid is None:
    print("대상 과목을 찾지 못함"); sys.exit(1)
results = []

# 1) [확인]: 해석한 조건을 조교가 그대로 확인
pid, prof = open_proposal(cid)
m = hdb.add_reply(c, pid, prof, "화요일이나 목요일이면 됩니다. 화요일은 오전만요. (가상 답장)")
cond1 = {"day_slots": {"1": ["09:00", "10:30"], "3": []}, "end_before": []}
hdb.save_interpretation(c, m, "CONDITIONAL", {"conditions": cond1}, model_name="test")
hdb.decide_reply(c, m, TA, "CONFIRM", conditions=cond1)
got = hdb.confirmed_conditions(c, pid); sent = copy.deepcopy(got)
a = sc.alternatives(c, 1, 1, tt, cid, condition=got, n=3, time_limit=10)
cs = cells_of(a); good = got == cond1 and len(a) > 0 and all(satisfies(cond1, row) for row in cs) and got == sent
print(f"[확인] 저장=읽기 {got == cond1}, 대안 {len(a)}개 {cs}, 조건 {'OK' if good else '위반!!'}, 넘긴 조건 그대로 {got == sent}")
results.append(good)

# 2) [수정]: 조교가 조건을 고쳐 확인 (수요일 + 수 13:30 전 종료)
pid2, _ = open_proposal(cid)
m2 = hdb.add_reply(c, pid2, prof, "수요일만 됩니다. (가상 답장)")
hdb.save_interpretation(c, m2, "CONDITIONAL", {"conditions": {"day_slots": {"2": []}, "end_before": []}})
cond2 = {"day_slots": {"1": [], "2": []}, "end_before": [{"day": 2, "time": "13:30"}]}
hdb.decide_reply(c, m2, TA, "EDIT", reason="교수님과 통화: 화요일도 가능, 수요일은 오전만(가상)", conditions=cond2)
got2 = hdb.confirmed_conditions(c, pid2)
a2 = sc.alternatives(c, 1, 1, tt, cid, condition=got2, n=3, time_limit=10)
cs2 = cells_of(a2); good2 = got2 == cond2 and len(a2) > 0 and all(satisfies(cond2, row) for row in cs2)
print(f"[수정] 저장=읽기 {got2 == cond2}, 대안 {len(a2)}개 {cs2}, 조건 {'OK' if good2 else '위반!!'}")
results.append(good2)

# 3) 조건 없음: [현재대로 유지] → None → 조건 없이 만든 대안과 같음
pid3, _ = open_proposal(cid)
m3 = hdb.add_reply(c, pid3, prof, "셋 다 어렵습니다. (가상 답장)")
hdb.save_interpretation(c, m3, "REJECT", {})
hdb.decide_reply(c, m3, TA, "KEEP")
got3 = hdb.confirmed_conditions(c, pid3)
b1 = sc.alternatives(c, 1, 1, tt, cid, condition=got3, n=3, time_limit=10)
b2 = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10)
good3 = got3 is None and cells_of(b1) == cells_of(b2)
print(f"[조건 없음] confirmed_conditions={got3}, 대안 {len(b1)}개 / 인자 없이 {len(b2)}개, 같은 대안 {cells_of(b1) == cells_of(b2)} "
      f"{'OK' if good3 else '다름!!'}")
results.append(good3)

# 4) 아직 결정 전(PROPOSED)이면 None
pid4, _ = open_proposal(cid)
m4 = hdb.add_reply(c, pid4, prof, "목요일 오후요. (가상 답장)")
hdb.save_interpretation(c, m4, "CONDITIONAL", {"conditions": {"day_slots": {"3": ["13:30", "15:00", "16:30"]}, "end_before": []}})
good4 = hdb.confirmed_conditions(c, pid4) is None
print(f"[결정 전] confirmed_conditions=None {'OK' if good4 else '다름!!'}")
results.append(good4)

ok = ok and verify(c, tt, " (조율 기록 뒤 시간표 그대로)") and all(results)
print("\n결과:", "모두 통과" if ok else "실패")
sys.exit(0 if ok else 1)
