from test_solver2 import *
c = build(); modes = add_pairs(c); sp = add_section_profs(c)
r = sc.solve(c, 1, 1, time_limit=45); tt = r['timetable_id']
print("1차:", r['status'], "못놓음", len(r['unplaced'])); verify(c, tt)
lab = lambda s: c.execute('select day||period_no||"("||start_time||")" from time_slot where id=?',(s,)).fetchone()[0]
tgt = next(k[0] for k in sc.load_assignment(c,tt)[0] if k[0] not in modes and k[0] not in sp
           and not c.execute("select 1 from course_response cr join response_slot rs on rs.response_id=cr.id where cr.course_id=? and rs.kind='BLOCK' and rs.slot_id in (select id from time_slot where (day='월' and period_no=4) or (day='수' and period_no=5))",(tgt:=k[0],)).fetchone())
print("대상 과목", tgt, "현재:", {k[1:]:lab(v[0]) for k,v in sc.load_assignment(c,tt)[0].items() if k[0]==tgt})
def show(name, cond, n=3):
    a = sc.make_alternatives(c,1,1,tt,tgt,condition=cond,n=n,time_limit=10)
    print(f"[{name}] 대안 {len(a)}개")
    for x in a: print("    ", {k:lab(v[0]) for k,v in x['placements'].items()}, x['stage'][:6])
    return a
# 1) 요일마다 다른 시간: 월 13:30 시작(4교시), 수 15:00 시작(5교시)
a = show("월 4교시 / 수 5교시만", {"by_day": {"0": ["13:30","14:45"], "2": ["15:00","16:15"]}})
ok = all((lab(v[0]).startswith("월4") or lab(v[0]).startswith("수5")) for x in a for v in x['placements'].values())
print("   조건 만족:", ok)
# 2) 사용자가 든 예시 그대로: 화 09:00~10:30, 목 13:30~15:00
a = show("화 09:00~10:30 / 목 13:30~15:00 (75분 격자에 안 맞는 예시)", {"by_day": {"1": ["09:00","10:30"], "3": ["13:30","15:00"]}})
print("   허용된 칸:", "화 1교시(09:00-10:15), 목 4교시(13:30-14:45)만 — 다른 교시는 범위를 벗어남")
# 3) 한 요일에 여러 시간대 + 다른 조건과 AND
a = show("월 1교시·4교시, 수 5교시 + 수요일 17시 전", {"by_day": {"0": [["09:00","10:15"],["13:30","14:45"]], "2": ["15:00","16:15"]}, "end_before":[{"day":2,"time":"17:00"}]})
# 4) 후보가 없는 조건 → 빈 리스트(오류 아님)
a = show("월 새벽 3시만(불가능)", {"by_day": {"0": ["03:00","04:00"]}})
# 5) 요일 키를 정수로 줘도 됨
a = show("키가 정수(0,2)", {"by_day": {0: ["13:30","14:45"], 2: ["15:00","16:15"]}}, n=1)
