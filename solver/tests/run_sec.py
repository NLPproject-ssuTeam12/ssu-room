from test_solver2 import *
c = build()
cid = c.execute("select id from course where id not in (select course_id from course_response) order by id limit 1").fetchone()[0]
pa = c.execute("select professor_id from course where id=?", (cid,)).fetchone()[0]; pb = pa % 30 + 1; pc = pb % 30 + 1
def reset():
    c.execute("DELETE FROM request_item WHERE response_id IN (SELECT id FROM course_response WHERE course_id=?)", (cid,))
    c.execute("DELETE FROM course_response WHERE course_id=?", (cid,)); c.execute("DELETE FROM course_section WHERE course_id=?", (cid,))
def resp(prof, n=None, rid=[8000]):
    rid[0] += 1
    c.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?)", (rid[0],1,cid,prof,0,'NONE'))
    if n: c.execute("INSERT INTO request_item(response_id,type,value_int) VALUES (?,?,?)", (rid[0],'SECTION_COUNT',n))
def secs():
    _, courses, sd, *_ = sc.load_input(c, 1, 1)
    return [sd[(cid, s)]["prof"] for s in range(1, courses[cid]["sections"]+1)]
A, B, C = f"가({pa})", f"나({pb})", f"다({pc})"
nm = {pa:"가", pb:"나", pc:"다"}
def check(label, expect):
    got = "".join(nm.get(p, str(p)) for p in secs())
    print(("OK  " if got == expect else "틀림") + f" {label}: {got}  (기대 {expect})")
reset(); check("응답 없음", "가")
reset(); resp(pa); check("가만 응답, 분반 수 미입력", "가")
reset(); resp(pa, 2); check("가가 분반 2개 요청 (단독 과목)", "가가")
reset(); resp(pa, 2); resp(pb, 2); check("가 2개 + 나 2개 (분반 지정 없음)", "가가나나")
reset(); resp(pa, 1); resp(pb, 3); check("가 1개 + 나 3개", "가나나나")
reset(); resp(pa, 2); resp(pb, 2); resp(pc, 1); check("세 교수: 2+2+1", "가가나나다")
reset(); c.execute("INSERT INTO course_section VALUES (?,1,?)",(cid,pa)); c.execute("INSERT INTO course_section VALUES (?,2,?)",(cid,pb)); check("조교가 가·나 지정, 응답 없음", "가나")
reset(); resp(pa, 2); resp(pb, 2); [c.execute("INSERT INTO course_section VALUES (?,?,?)",(cid,s,p)) for s,p in [(1,pa),(2,pa),(3,pb),(4,pb)]]; check("조교 지정과 요청이 같음", "가가나나")
reset(); resp(pa, 3); c.execute("INSERT INTO course_section VALUES (?,1,?)",(cid,pa)); c.execute("INSERT INTO course_section VALUES (?,2,?)",(cid,pb)); check("조교가 가·나 1개씩 지정 + 가가 3개 요청", "가나가가")
reset(); resp(pa, 1); [c.execute("INSERT INTO course_section VALUES (?,?,?)",(cid,s,pa)) for s in (1,2)]; check("가가 1개 요청했지만 조교가 가에게 2개 지정(지정이 더 큼)", "가가")
reset(); c.execute("INSERT INTO course_section VALUES (?,3,?)",(cid,pb)); check("조교가 3번 분반만 나에게 지정(빈 번호는 기본 담당)", "가가나") 
