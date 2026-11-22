from test_solver2 import *
c = build(); modes = add_pairs(c)
ids = add_prefer_only(c, 6)
print("'선호 시간 외 불가' 응답 id:", ids)
r = sc.solve(c, 1, 1, time_limit=60); tt = r['timetable_id']
print(r['status'], "못놓음", len(r['unplaced']), "지원불가", r['unsupported']); verify(c, tt)
# 실제로 희망 칸 안에만 있는지 눈으로
lab = lambda s: c.execute('select day||period_no from time_slot where id=?',(s,)).fetchone()[0]
rid = ids[0]; cid, prof = c.execute("select course_id, professor_id from course_response where id=?", (rid,)).fetchone()
prefs = [lab(s) for s, in c.execute("select slot_id from response_slot where response_id=? and kind='PREFER'", (rid,))]
got = [lab(x[0]) for x in c.execute("select slot_id from assignment where timetable_id=? and course_id=?", (tt, cid))]
print(f"  과목{cid}: 희망 칸 {prefs} → 배정 {got}")
# 대안도 희망 칸 안에서만
alts = sc.alternatives(c, 1, 1, tt, cid, n=3, time_limit=10)
print(f"  대안 {len(alts)}개:", [[lab(v[0]) for v in a['placements'].values()] for a in alts])
okalt = all(lab(v[0]) in prefs for a in alts for v in a['placements'].values())
print("  대안이 모두 희망 칸 안:", okalt)
# 희망 칸을 안 골랐는데 '선호 시간 외 불가'만 켠 경우: 막히지 않고 알림만
rid2 = c.execute("select id from course_response where prefer_only=0 order by id limit 1").fetchone()[0]
c.execute("DELETE FROM response_slot WHERE response_id=? AND kind='PREFER'", (rid2,)); c.execute("UPDATE course_response SET prefer_only=1 WHERE id=?", (rid2,)); c.commit()
r2 = sc.solve(c, 1, 1, time_limit=20)
print("희망 칸 없이 켠 경우:", r2['status'], "| 알림:", [u for u in r2['unsupported'] if "선호 시간 외" in u[1]])
