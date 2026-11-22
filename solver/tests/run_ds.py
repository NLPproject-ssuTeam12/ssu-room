"""day_slots 조건 검사: 요일 둘 이상 / 하나 / 빈 값 / 연강 / 안 맞는 시각"""
from test_solver2 import *
c = build(); sp = add_section_profs(c)
r = sc.solve(c, 1, 1, time_limit=30); tt = r['timetable_id']
print("1차:", r['status'], "못놓음", len(r['unplaced'])); verify(c, tt)
info = {sid: (d, st) for sid, d, st in c.execute("select id, day, start_time from time_slot")}
DAYN = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4}
pos = lambda sid: (DAYN[info[sid][0]], info[sid][1])
prev = sc.load_assignment(c, tt)[0]

def cand(single):   # 2회×1칸 분반이고, 분반이 하나인 과목 중 single_day_pref가 single인 것
    for (cid, sec, ss) in prev:
        if cid in sp or sec != 1: continue
        row = c.execute("select single_day_pref from course_response where course_id=? limit 1", (cid,)).fetchone()
        if row and row[0] == single:
            n = c.execute("select count(distinct session_no) from assignment where timetable_id=? and course_id=?", (tt, cid)).fetchone()[0]
            if single == 'NONE' and n == 2: return cid
            if single == 'MUST' and n == 1: return cid
    return None

def run(name, cid, cond, check, n=3):
    a = sc.alternatives(c, 1, 1, tt, cid, condition=cond, n=n, time_limit=10)
    cells = [[pos(v[0]) for v in x['placements'].values()] for x in a]
    ok = check(cells)
    print(f"[{name}] 대안 {len(a)}개 {cells[:2]}  조건 {'OK' if ok else '위반!!'}")
    return a

cid = cand('NONE'); print("대상(주 2회):", cid, "현재:", [pos(v[0]) for k, v in prev.items() if k[0] == cid])
# 1) 요일 둘 이상: 월 13:30·15:00 시작, 수는 아무 교시 -> 월·수 밖에는 없고, 월은 그 두 시각만
a = run("월(13:30,15:00)+수(전체)", cid, {"day_slots": {"0": ["13:30", "15:00"], "2": []}},
        lambda cs: all(d in (0, 2) and (d == 2 or t in ("13:30", "15:00")) for row in cs for d, t in row))
# 2) 요일 하나: 화 10:30만 -> 화가 들어가야 하고 화는 10:30만, 다른 하루는 자유
a = run("화 10:30만 (하나)", cid, {"day_slots": {"1": ["10:30"]}},
        lambda cs: all(any(d == 1 for d, _ in row) and all(t == "10:30" for d, t in row if d == 1) for row in cs))
# 3) 빈 값: 조건 없음 -> 조건 없이 한 것과 같은 개수
b1 = sc.alternatives(c, 1, 1, tt, cid, condition={"day_slots": {}}, n=3, time_limit=10)
b2 = sc.alternatives(c, 1, 1, tt, cid, condition=None, n=3, time_limit=10)
print(f"[빈 day_slots] 대안 {len(b1)}개 / 조건 없음 {len(b2)}개  {'OK' if len(b1) == len(b2) else '다름!!'}")
# 4) 시작 시각이 격자에 없음 -> 불가능(0개). 조건이 무시되면 안 된다
a = run("격자에 없는 시각만(월 13:00, 수 15:30)", cid, {"day_slots": {"0": ["13:00"], "2": ["15:30"]}}, lambda cs: len(cs) == 0)
# 5) end_before와 같이: 화 전체 + 수 전체, 수는 12:00 전에 끝
a = run("화·수 전체 + 수 13:30 전 종료(end_before)", cid, {"day_slots": {"1": [], "2": []}, "end_before": [{"day": 2, "time": "13:30"}]},
        lambda cs: all(d in (1, 2) and (d != 2 or t in ("09:00", "10:30")) for row in cs for d, t in row))
# 6) 연강(2칸 연속) 분반: 두 교시가 모두 있어야 함
cm = cand('MUST'); print("대상(연강):", cm, "현재:", [pos(v[0]) for k, v in prev.items() if k[0] == cm])
if cm:
    a = run("연강: 목 13:30만 (15:00 빠짐)", cm, {"day_slots": {"3": ["13:30"]}}, lambda cs: len(cs) == 0 or all(d != 3 for row in cs for d, _ in row))
    a = run("연강: 목 13:30+15:00", cm, {"day_slots": {"3": ["13:30", "15:00"]}},
            lambda cs: len(cs) > 0 and all(d == 3 for row in cs for d, _ in row))
