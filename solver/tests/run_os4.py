from test_solver2 import *
def setup(c, with_section_rows):
    os_id, pa = c.execute("select id, professor_id from course where category='전공필수' and target_year is not null and id not in (select course_id from course_response r join request_item i on i.response_id=r.id) limit 1").fetchone()
    pb = pa % 30 + 1
    c.execute("DELETE FROM response_slot WHERE response_id IN (SELECT id FROM course_response WHERE course_id=?)", (os_id,))
    c.execute("DELETE FROM request_item WHERE response_id IN (SELECT id FROM course_response WHERE course_id=?)", (os_id,))
    c.execute("DELETE FROM course_response WHERE course_id=?", (os_id,))
    rid = 9000
    c.execute("DELETE FROM course_section WHERE course_id=?", (os_id,))
    for prof in (pa, pb):                      # 두 교수 모두 "분반 2개 개설" 요청(옛 방식, 이제 솔버는 읽지 않음)
        rid += 1
        c.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?)", (rid,1,os_id,prof,'NONE','NONE'))
        c.execute("INSERT INTO request_item(response_id,type,value_int) VALUES (?,?,?)", (rid,'SECTION_COUNT',2))
    if with_section_rows:                      # 오프라인 회의 결과: 조교가 분반 4개(교수·인원)를 입력
        for s, p in [(1,pa),(2,pa),(3,pb),(4,pb)]: c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (os_id, s, p, 30))
    c.commit(); return os_id, pa, pb

for label, rows in [("① 두 교수가 각자 '분반 2개'만 요청, course_section 없음 → 1분반(요청은 읽지 않음)", False),
                    ("② 조교가 course_section에 분반 4개(가가나나)를 입력", True)]:
    c = build(); os_id, pa, pb = setup(c, rows)
    _, courses, secs, *_ = sc.load_input(c, 1, 1)
    print(label)
    print("  엔진이 만든 분반 수:", courses[os_id]["sections"], "| 분반별 교수:", {s: secs[(os_id, s)]["prof"] for s in range(1, courses[os_id]["sections"]+1)}, f"(교수 {pa}=가, 교수 {pb}=나)")
    if rows:
        r = sc.solve(c, 1, 1, time_limit=40); tt = r['timetable_id']
        print("  ", r['status'], "못놓음", len([k for k in r['unplaced'] if k[0]==os_id]))
        for x in c.execute("select section_no, professor_id, count(*) from v_schedule where timetable_id=? and course_id=? group by 1,2", (tt, os_id)).fetchall(): print("    분반%d 교수%d 수업 %d회" % x)
        verify(c, tt)
