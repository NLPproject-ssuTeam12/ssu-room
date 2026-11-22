from test_solver2 import *
c = build(); modes = add_pairs(c); sp = add_section_profs(c)
print("분반별 교수 지정:", sp)
r = sc.solve(c, 1, 1, time_limit=30)
print(r['status'], "목적", round(r['objective']), "못놓음", len(r['unplaced']), "지원불가", r['unsupported'])
tt = r['timetable_id']; verify(c, tt); pair_check(c, tt, modes)
# 연강 응답별 결과
for pref in ('MUST','PREFER','NONE',None):
    q = """SELECT COUNT(*), SUM(n=2) FROM (SELECT a.course_id, a.section_no, a.session_no, COUNT(*) n FROM assignment a WHERE a.timetable_id=? GROUP BY 1,2,3) s
           JOIN course c ON c.id=s.course_id LEFT JOIN course_response cr ON cr.course_id=c.id AND cr.professor_id=COALESCE((SELECT professor_id FROM course_section WHERE course_id=s.course_id AND section_no=s.section_no), c.professor_id)
           WHERE """ + ("cr.single_day_pref IS NULL" if pref is None else f"cr.single_day_pref='{pref}'")
    n, longn = c.execute(q, (tt,)).fetchone()
    print(f"  연강 응답 {pref}: 회차 {n}개 중 연속 2칸 {longn or 0}개")
# 분반별 교수: 같은 칸에 교수 겹침 없는지(뷰), 분반 교수가 다른 과목에서 확인
cid, other = next(iter(sp.items()))
print("분반 교수 확인(과목%d):"%cid, c.execute("select section_no, professor_id from v_schedule where timetable_id=? and course_id=? group by section_no",(tt,cid)).fetchall())
