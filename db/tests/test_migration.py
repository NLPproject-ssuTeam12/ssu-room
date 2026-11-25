"""변경 SQL 검사: 옛 스키마로 만든 DB에 변경 SQL을 차례로 적용해서
  (1) 최종 schema.sql 과 같은 모양이 되는지  (2) 데이터가 보존되는지  (3) 새 규칙이 작동하는지 확인"""
import os, sqlite3, sys
DB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # db/
sys.path.insert(0, DB)
import seed_time_slot as sd

def P(*a): return os.path.join(DB, *a)

def norm_sql(x): return " ".join((x or "").replace("\n", " ").split())

def shape(con):
    out = {}
    for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
        cols = sorted((r[1], r[2].upper(), r[3], r[5]) for r in con.execute(f"pragma table_info({t})"))
        fks = sorted((r[2], r[3], r[4]) for r in con.execute(f"pragma foreign_key_list({t})"))
        idx = sorted((r[2],) + tuple(x[2] for x in con.execute(f"pragma index_info({r[1]})")) for r in con.execute(f"pragma index_list({t})"))
        out[t] = (cols, fks, idx)
    views = {n: norm_sql(s) for n, s in con.execute("select name, sql from sqlite_master where type='view'")}
    return out, views

V8 = P("archive", "schema_v8.sql")      # 005까지 적용한 모양 (006 전)
M6 = P("migrations", "006_20261124_section.sql")
V9 = P("archive", "schema_v9.sql")      # 006까지 적용한 모양 (007 전)
M7 = P("migrations", "007_20261125_reply_choice.sql")
V10 = P("archive", "schema_v10.sql")    # 007까지 적용한 모양 (008 전)
M8 = P("migrations", "008_20261125_timetable_reason.sql")
V11 = P("archive", "schema_v11.sql")    # 008까지 적용한 모양 (009 전)
M9 = P("migrations", "009_20261125_section_response.sql")
V12 = P("archive", "schema_v12.sql")    # 009까지 적용한 모양 (010 전)
M10 = P("migrations", "010_20261125_lab_must_keep.sql")

def compare(label, con, target=None):
    """con 이 target(기본: 최종 schema.sql)과 같은 모양인지"""
    new = sqlite3.connect(":memory:"); new.executescript(open(target or P("schema.sql"), encoding="utf-8").read())
    a, va = shape(con); b, vb = shape(new)
    diff = [t for t in b if a.get(t) != b[t]]
    print(f"  [{label}] 테이블 {len(a)}개 vs {len(b)}개, 목록 동일 {set(a) == set(b)}, 모양이 다른 테이블 {diff if diff else '없음'}, 뷰 동일 {va == vb}")
    for t in diff: print("     ", t, "\n       변경 후:", a.get(t), "\n       최종   :", b[t])
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    print(f"  [{label}] foreign_key_check:", fk if fk else "문제 없음")
    return not diff and set(a) == set(b) and va == vb and not fk

def run(path, con):
    con.executescript(open(path, encoding="utf-8").read())

def seed(con):
    q = con.execute
    sd.seed(con)
    q("INSERT INTO department VALUES (1,'AI','AI융합대학')")
    q("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (1,'TA','조교',1,'x'),(2,'PROF','교수2',1,'x'),(3,'PROF','교수3',1,'x')")
    q("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)"); q("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
    q("INSERT INTO building VALUES (1,'건물')"); q("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (1,1,'101',50,0)")
    q("INSERT INTO course(id,term_id,department_id,name,professor_id,expected_enrollment,session_count,slots_per_session) VALUES (10,1,1,'알고리즘',2,40,2,1),(11,1,1,'객체지향',3,40,2,1)")

def build_v3():
    old = sqlite3.connect(":memory:"); old.executescript(open(P("archive","schema_v3.sql"), encoding="utf-8").read()); seed(old); q = old.execute
    q("INSERT INTO course_response(id,round_id,course_id,lab_requirement,language,note) VALUES (100,1,10,'REQUIRE','한국어','분반 2개 부탁드립니다'),(101,1,11,'NONE',NULL,NULL)")
    q("INSERT INTO response_slot VALUES (100,1,'BLOCK'),(100,2,'PREFER'),(100,3,'AVOID')")
    q("INSERT INTO request_item(id,response_id,type,value_int,source,status,confirmed_by,confirmed_at) VALUES (1,100,'SECTION_COUNT',2,'NLP','CONFIRMED',1,'2026-11-10 09:00:00')")
    q("INSERT INTO request_item(id,response_id,type,value_int,source,status) VALUES (2,101,'SECTION_COUNT',3,'FORM','EXTRACTED')")
    q("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
    q("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
    q("INSERT INTO timetable_section VALUES (1,10,1,40)"); q("INSERT INTO assignment VALUES (1,10,1,1,3,1)")
    q("INSERT INTO proposal(id,round_id,timetable_id,course_id) VALUES (1,1,1,10)"); q("INSERT INTO proposal_option(id,proposal_id,option_no) VALUES (1,1,1)")
    q("INSERT INTO message(id,round_id,proposal_id,sender_id,receiver_id,kind) VALUES (1,1,1,1,2,'REPLY'),(2,1,1,1,2,'REPLY'),(3,1,1,1,2,'REPLY'),(4,1,1,1,2,'REPLY'),(5,1,1,1,2,'REPLY')")
    for mid, lab in [(1,'수용'),(2,'조건부'),(3,'거절'),(4,'확인 필요'),(5,None)]:
        q("INSERT INTO reply_interpretation(message_id,label) VALUES (?,?)", (mid, lab))
    old.commit(); return old

def counts(con, tabs): return {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in tabs}
KEEP = ("response_slot", "proposal", "reply_interpretation", "assignment", "course", "term")

print("=== 경로 1: schema_v3 → 001 → 002 → 003 → 004 → 005 (→ schema_v8) → 006")
old = build_v3(); before = counts(old, KEEP); before["response_slot"] -= 1   # AVOID 1개는 003에서 지워지는 게 정상
run(P("migrations","001_20261121_feedback.sql"), old)
run(P("migrations","002_20261122_phase_other_request.sql"), old)
run(P("migrations","003_20261122_lab_binary_no_avoid.sql"), old)
old.execute("UPDATE term SET phase='ROUND2', phase_changed_at='2026-11-22 10:00:00' WHERE id=1"); old.commit()   # 004 전에 진행 중이던 학기
run(P("migrations","004_20261122_phase_round3.sql"), old)
run(P("migrations","005_20261124_reply.sql"), old)
ok1 = compare("001~005 적용 후 = schema_v8", old, V8)
print("  행 수 보존:", before == counts(old, KEEP), "| 응답 수:", old.execute("select count(*) from course_response").fetchone()[0])
print("  기타 요청 옮김:", old.execute("select id, response_id, body, status from other_request").fetchall())
print("  prefer_only:", old.execute("select id, prefer_only from course_response order by id").fetchall())
print("  request_item:", old.execute("select id, response_id, type, value_int, source, created_by, created_at, other_request_id from request_item order by id").fetchall())
print("  term 단계(ROUND2 그대로여야 함):", old.execute("select id, phase, phase_changed_at from term").fetchall())
old.execute("UPDATE term SET phase='ROUND3' WHERE id=1"); print("  ROUND3 허용: OK")
print("  응답 칸(AVOID 삭제, 2개 남아야 함):", old.execute("select slot_id, kind from response_slot where response_id=100 order by slot_id").fetchall())
print("  실습실 값(REQUIRE→1, NONE→0):", old.execute("select id, lab_requirement from course_response order by id").fetchall())
for bad in ["INSERT INTO term(id,year,semester,grid_id,phase) VALUES (9,2027,'1',1,'아무거나')",
            "INSERT INTO request_item(response_id,type,source) VALUES (100,'X','NLP')",
            "INSERT INTO course_response(round_id,course_id,professor_id,lab_requirement,single_day_pref,prefer_only) VALUES (1,11,3,0,'NONE',2)",
            "INSERT INTO course_response(round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (1,11,3,'PREFER','NONE')",
            "INSERT INTO response_slot VALUES (101,1,'AVOID')"]:
    try: old.execute(bad); print("  거부 안 됨!!", bad[:60])
    except sqlite3.IntegrityError as e: print("  새 규칙 거부 OK:", str(e)[:60])
run(M6, old)
ok1 = compare("001~006 적용 후 = schema_v9", old, V9) and ok1
run(M7, old)
ok1 = compare("001~007 적용 후 = schema_v10", old, V10) and ok1
run(M8, old)
ok1 = compare("001~008 적용 후 = schema_v11", old, V11) and ok1
run(M9, old)
ok1 = compare("001~009 적용 후 = schema_v12", old, V12) and ok1
run(M10, old)
ok1 = compare("001~010 적용 후", old) and ok1

print("\n=== 경로 2: schema_v4(001까지 적용된 모양)에서 002 → 003 → 004 → 005 → 006")
v4 = sqlite3.connect(":memory:"); v4.executescript(open(P("archive","schema_v4.sql"), encoding="utf-8").read()); seed(v4)
v4.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref,note) VALUES (100,1,10,2,'PREFER','PREFER','메모')")
v4.execute("INSERT INTO request_item(response_id,type,value_int) VALUES (100,'SECTION_COUNT',2)"); v4.commit()
run(P("migrations","002_20261122_phase_other_request.sql"), v4)
run(P("migrations","003_20261122_lab_binary_no_avoid.sql"), v4)
run(P("migrations","004_20261122_phase_round3.sql"), v4)
run(P("migrations","005_20261124_reply.sql"), v4)
ok2 = compare("v4 + 002~005 = schema_v8", v4, V8)
print("  응답:", v4.execute("select id, professor_id, lab_requirement, single_day_pref, prefer_only from course_response").fetchall(), "| 기타 요청:", v4.execute("select body, status from other_request").fetchall())
run(M6, v4)
ok2 = compare("v4 + 002~006 = schema_v9", v4, V9) and ok2
run(M7, v4)
ok2 = compare("v4 + 002~007 = schema_v10", v4, V10) and ok2
run(M8, v4)
ok2 = compare("v4 + 002~008 = schema_v11", v4, V11) and ok2
run(M9, v4)
ok2 = compare("v4 + 002~009 = schema_v12", v4, V12) and ok2
run(M10, v4)
ok2 = compare("v4 + 002~010", v4) and ok2
print("\n=== 경로 3: schema_v7(004까지 적용된 모양)에서 005 → 006")
def build_v7():
    v7 = sqlite3.connect(":memory:"); v7.executescript(open(P("archive","schema_v7.sql"), encoding="utf-8").read()); seed(v7); q = v7.execute
    q("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
    q("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
    q("INSERT INTO timetable_section VALUES (1,10,1,40),(1,11,2,30)")
    q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,reason) VALUES (1,1,1,10,1,'겹침')")   # 옛 기본값 WAITING
    q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,reason,status) VALUES (2,1,1,11,NULL,NULL,NULL),(3,1,1,11,2,'이유','SENT')")
    q("INSERT INTO proposal_option(id,proposal_id,option_no,source) VALUES (1,1,1,'SOLVER'),(2,1,2,'SOLVER'),(3,3,1,'SOLVER')")
    q("INSERT INTO message(id,round_id,proposal_id,sender_id,receiver_id,kind,channel,body) VALUES (1,1,1,1,2,'ALTERNATIVE','APP','조율 안내'),(2,1,1,2,1,'REPLY','APP','A안 좋아요')")
    q("INSERT INTO reply_interpretation(message_id,label,chosen_option_id) VALUES (2,'ACCEPT',1)")
    v7.commit(); return v7

v7 = build_v7(); before7 = counts(v7, ("proposal", "proposal_option", "message", "reply_interpretation"))
run(P("migrations","005_20261124_reply.sql"), v7)
ok3 = compare("v7 + 005 = schema_v8", v7, V8)
keep3 = before7 == counts(v7, ("proposal", "proposal_option", "message", "reply_interpretation"))
print("  행 수 보존:", keep3)
st = v7.execute("select id, course_id, section_no, reason, status from proposal order by id").fetchall()
print("  안건 상태(WAITING·NULL→OPEN, SENT 그대로):", st)
ok3 = ok3 and keep3 and [r[4] for r in st] == ["OPEN", "OPEN", "SENT"] and st[0][1:4] == (10, 1, "겹침")
print("  메시지 reply_to_id(기존 행은 NULL):", v7.execute("select id, reply_to_id from message order by id").fetchall())
v7.execute("UPDATE message SET reply_to_id=1 WHERE id=2"); v7.commit()
print("  reply_to_id 연결:", v7.execute("select m.id, t.kind from message m join message t on t.id=m.reply_to_id").fetchall())
v7.execute("INSERT INTO proposal(id,round_id,timetable_id,course_id) VALUES (4,1,1,10)")
d = v7.execute("select status, prev_proposal_id from proposal where id=4").fetchone(); print("  새 기본값(상태, 이전 안건):", d)
ok3 = ok3 and d == ("OPEN", None)
pv = v7.execute("select prev_proposal_id from proposal where id<=3").fetchall(); print("  기존 안건 prev_proposal_id(NULL):", pv)
ok3 = ok3 and pv == [(None,)] * 3
ts = v7.execute("select course_id, section_no, status from timetable_section order by course_id").fetchall()
print("  분반 배정 상태(기존 행은 DONE):", ts); ok3 = ok3 and ts == [(10, 1, "DONE"), (11, 2, "DONE")]
v7.execute("UPDATE proposal SET status='NEXT' WHERE id=1")
v7.execute("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,prev_proposal_id) VALUES (5,1,1,10,1,1)")
v7.execute("UPDATE timetable_section SET status='COORD' WHERE course_id=11"); v7.commit()
nx = v7.execute("select p.id, p.status, n.id from proposal p join proposal n on n.prev_proposal_id=p.id").fetchall()
print("  NEXT 와 다음 차수 안건 연결:", nx); ok3 = ok3 and nx == [(1, "NEXT", 5)]
for bad in ["UPDATE proposal SET status='WAITING' WHERE id=1",
            "UPDATE proposal SET status='DONE' WHERE id=1",
            "UPDATE proposal SET status=NULL WHERE id=1",
            "INSERT INTO proposal(id,round_id,timetable_id,course_id,prev_proposal_id) VALUES (6,1,1,10,1)",
            "INSERT INTO proposal(id,round_id,timetable_id,course_id,prev_proposal_id) VALUES (7,1,1,10,999)",
            "UPDATE timetable_section SET status='WAIT' WHERE course_id=10",
            "INSERT INTO message(round_id,proposal_id,sender_id,receiver_id,kind,reply_to_id) VALUES (1,1,2,1,'REPLY',999)"]:
    try: v7.execute(bad); print("  거부 안 됨!!", bad[:60]); ok3 = False
    except sqlite3.IntegrityError as e: print("  새 규칙 거부 OK:", str(e)[:60])

run(M6, v7)
ok3 = compare("v7 + 005 + 006 = schema_v9", v7, V9) and ok3
run(M7, v7)
ok3 = compare("v7 + 005 + 006 + 007 = schema_v10", v7, V10) and ok3
run(M8, v7)
ok3 = compare("v7 + 005~008 = schema_v11", v7, V11) and ok3
run(M9, v7)
ok3 = compare("v7 + 005~009 = schema_v12", v7, V12) and ok3
run(M10, v7)
ok3 = compare("v7 + 005~010", v7) and ok3

print("\n=== 경로 4: 목록 밖 status 가 있으면 005 가 멈추고 데이터는 그대로")
v7b = build_v7(); v7b.execute("UPDATE proposal SET status='DONE' WHERE id=3"); v7b.commit()
try:
    run(P("migrations","005_20261124_reply.sql"), v7b); print("  멈추지 않음!!"); ok4 = False
except sqlite3.IntegrityError as e:
    v7b.rollback(); v7b.execute("PRAGMA foreign_keys = ON")
    left = v7b.execute("select id, status from proposal order by id").fetchall()
    cols = [r[1] for r in v7b.execute("pragma table_info(message)")]
    tcols = [r[1] for r in v7b.execute("pragma table_info(timetable_section)")]
    print("  멈춤 OK:", str(e)[:60], "| 되돌린 뒤 안건:", left, "| reply_to_id 없음:", "reply_to_id" not in cols,
          "| 분반 status 없음:", "status" not in tcols)
    ok4 = left == [(1, "WAITING"), (2, None), (3, "DONE")] and "reply_to_id" not in cols and "status" not in tcols

print("\n=== 경로 5: schema_v8(005까지 적용된 모양)에서 006 — 분반 인원, 삭제된 칸, 희망 건물 하나")
def build_v8():
    v8 = sqlite3.connect(":memory:"); v8.executescript(open(V8, encoding="utf-8").read()); seed(v8); q = v8.execute
    q("INSERT INTO building VALUES (2,'건물2'),(3,'건물3')")
    q("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (4,'PROF','교수4',1,'x'),(5,'PROF','교수5',1,'x')")
    # 과목 10(40명): 분반 2개 지정 → 20명씩 / 11(40명): 분반 행 없음 → 1분반 40명 생성
    # 12(인원 없음): 행 만들지 않음 / 13(45명): 분반 2개 → 23명씩(올림)
    q("""INSERT INTO course(id,term_id,department_id,name,professor_id,expected_enrollment,session_count,slots_per_session)
         VALUES (12,1,1,'인원 미정',2,NULL,2,1),(13,1,1,'자료구조',4,45,2,1)""")
    q("INSERT INTO course_section VALUES (10,1,2),(10,2,3),(13,1,4),(13,2,5)")
    q("""INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref,prefer_only,language)
         VALUES (100,1,10,2,1,'MUST',1,'영어'),(101,1,11,3,0,'NONE',0,NULL),(102,1,13,4,0,'PREFER',0,NULL)""")
    q("INSERT INTO response_slot VALUES (100,1,'PREFER'),(100,2,'BLOCK')")
    q("INSERT INTO request_item(response_id,type,value_int) VALUES (100,'SECTION_COUNT',2)")
    q("INSERT INTO request_item(response_id,type,value_text) VALUES (100,'SECTION_PAIR','BACK_TO_BACK'),(100,'SECTION_PAIR','CROSS'),(101,'SECTION_PAIR','이상한 값')")
    # 교수2: 1순위 건물2, 2순위 건물1 → 건물2 / 교수3: 2순위만 건물3 → 건물3 / 교수4: 1순위 둘(건물3, 건물1) → 번호 작은 건물1
    q("INSERT INTO professor_building_pref VALUES (2,1,2),(2,2,1),(3,3,2),(4,3,1),(4,1,1)")
    v8.commit(); return v8

v8 = build_v8(); keep8 = ("course", "course_response", "response_slot", "request_item", "user", "building")
before8 = counts(v8, keep8)
run(M6, v8)
ok5 = compare("v8 + 006 = schema_v9", v8, V9)
same = before8 == counts(v8, keep8); print("  행 수 보존(과목·응답·칸·요청):", same)
secs8 = v8.execute("select course_id, section_no, professor_id, enrollment from course_section order by 1,2").fetchall()
print("  분반 인원:", secs8)
want8 = [(10, 1, 2, 20), (10, 2, 3, 20), (11, 1, 3, 40), (13, 1, 4, 23), (13, 2, 5, 23)]
bld8 = v8.execute("select professor_id, building_id from professor_building_pref order by 1").fetchall()
print("  희망 건물(교수당 하나):", bld8)
cr8 = v8.execute("select id, lab_requirement, single_day_pref, section_pair from course_response order by id").fetchall()
print("  응답(실습실 그대로, 연강 PREFER→NONE, 분반 연강·교차 옮김: 최근 값, 이상한 값은 NONE):", cr8)
rs8 = v8.execute("select response_id, slot_id, kind from response_slot order by 1,2").fetchall()
print("  응답 칸(다시 만든 응답에 그대로 연결):", rs8); ok_rs8 = rs8 == [(100, 1, "PREFER"), (100, 2, "BLOCK")]
cols8 = {t: [r[1] for r in v8.execute(f"pragma table_info({t})")] for t in ("course", "course_response")}
gone = "expected_enrollment" not in cols8["course"] and not {"prefer_only", "language"} & set(cols8["course_response"])
print("  삭제된 칸 없음:", gone)
ok5 = ok5 and ok_rs8 and same and secs8 == want8 and bld8 == [(2, 2), (3, 3), (4, 1)] and cr8 == [(100, 1, "MUST", "CROSS"), (101, 0, "NONE", "NONE"), (102, 0, "NONE", "NONE")] and gone
for bad in ["UPDATE course_section SET enrollment=0 WHERE course_id=10 AND section_no=1",
            "INSERT INTO professor_building_pref VALUES (2,3)",
            "INSERT INTO professor_building_pref(professor_id) VALUES (5)",
            "INSERT INTO professor_building_pref VALUES (5,99)",
            "UPDATE course_response SET section_pair='BOTH' WHERE id=100",
            "UPDATE course_response SET single_day_pref='PREFER' WHERE id=100",
            "INSERT INTO response_slot VALUES (999,1,'BLOCK')",
            "INSERT INTO chapel_slot VALUES (1,'1',999)",
            "INSERT INTO chapel_slot VALUES (1,'1',1),(1,'1',1)"]:
    try: v8.execute(bad); print("  거부 안 됨!!", bad[:60]); ok5 = False
    except sqlite3.IntegrityError as e: print("  새 규칙 거부 OK:", str(e)[:60])
for bad in ["INSERT INTO course(id,term_id,name,professor_id,expected_enrollment) VALUES (20,1,'x',2,30)",
            "UPDATE course_response SET prefer_only=1", "UPDATE course_response SET language='한국어'"]:
    try: v8.execute(bad); print("  없앤 칸에 써짐!!", bad[:60]); ok5 = False
    except sqlite3.OperationalError as e: print("  없앤 칸 OK:", str(e)[:60])

print("\n=== 경로 6: schema_v9(006까지 적용된 모양)에서 007 — 답장 선택, 따로 연락, 고정, 답장 기타 요청")
v9 = v8                                          # 경로 5 의 DB (006 까지 적용, 데이터 있음)
v9.execute("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
v9.execute("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
v9.execute("INSERT INTO timetable_section(timetable_id,course_id,section_no,planned_enrollment,status) VALUES (1,10,1,20,'COORD'),(1,10,2,20,'DONE')")
v9.execute("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,reason,status) VALUES (1,1,1,10,1,'겹침','PROPOSED'),(2,1,1,10,2,NULL,'NEXT')")
v9.execute("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,status,prev_proposal_id) VALUES (3,1,1,10,2,'OPEN',2)")
v9.execute("INSERT INTO proposal_option(id,proposal_id,option_no,source) VALUES (1,1,1,'SOLVER')")
v9.execute("INSERT INTO message(id,round_id,proposal_id,sender_id,receiver_id,kind,channel,body) VALUES (1,1,1,1,2,'ALTERNATIVE','APP','조율 안내'),(2,1,1,2,1,'REPLY','APP','셋 다 어렵습니다')")
v9.execute("INSERT INTO other_request(id,response_id,body) VALUES (1,100,'실습 조교 배치 부탁')")
v9.commit()
before9 = counts(v9, ("proposal", "proposal_option", "message", "other_request", "timetable_section", "request_item"))
run(M7, v9)
ok6 = compare("v9 + 007 = schema_v10", v9, V10)
same9 = before9 == counts(v9, ("proposal", "proposal_option", "message", "other_request", "timetable_section", "request_item"))
print("  행 수 보존:", same9)
pr9 = v9.execute("select id, status, prev_proposal_id from proposal order by id").fetchall()
ts9 = v9.execute("select course_id, section_no, status, locked from timetable_section order by 1,2").fetchall()
or9 = v9.execute("select id, response_id, message_id, body, status from other_request").fetchall()
print("  안건(상태·이전 안건 그대로):", pr9); print("  분반 배정(locked=0):", ts9); print("  기타 요청(message_id NULL):", or9)
ok6 = ok6 and same9 and pr9 == [(1, "PROPOSED", None), (2, "NEXT", None), (3, "OPEN", 2)] \
      and ts9 == [(10, 1, "COORD", 0), (10, 2, "DONE", 0)] and or9 == [(1, 100, None, "실습 조교 배치 부탁", "PENDING")]
v9.execute("UPDATE proposal SET status='OFFLINE' WHERE id=1")
v9.execute("INSERT INTO reply_choice VALUES (2,'A',1),(2,'ETC',NULL)")
v9.execute("INSERT INTO other_request(message_id, body) VALUES (2,'답장 기타: 실습 조교')")
v9.execute("UPDATE timetable_section SET locked=1 WHERE course_id=10 AND section_no=1"); v9.commit()
print("  새 값 허용 OK: OFFLINE, reply_choice, 답장 기타 요청, locked=1")
for bad in ["INSERT INTO reply_choice VALUES (2,'D',NULL)",
            "INSERT INTO reply_choice VALUES (2,'A',1)",
            "INSERT INTO reply_choice VALUES (999,'B',NULL)",
            "UPDATE proposal SET status='WAIT' WHERE id=1",
            "INSERT INTO other_request(body) VALUES ('어느 쪽도 아님')",
            "INSERT INTO other_request(response_id, message_id, body) VALUES (101, 2, '둘 다')",
            "INSERT INTO other_request(message_id, body) VALUES (2, '답장당 하나')",
            "UPDATE timetable_section SET locked=2 WHERE course_id=10"]:
    try: v9.execute(bad); print("  거부 안 됨!!", bad[:60]); ok6 = False
    except sqlite3.IntegrityError as e: print("  새 규칙 거부 OK:", str(e)[:60])

print("\n=== 경로 7: schema_v10(007까지 적용된 모양)에서 008 — 시간표 버전 사유")
n10 = v9.execute("select count(*) from timetable").fetchone()[0]
run(M8, v9)
ok7 = compare("v10 + 008 = schema_v11", v9, V11)
r10 = v9.execute("select id, kind, reason from timetable order by id").fetchall()
print("  시간표 행 보존·사유 NULL:", r10)
ok7 = ok7 and len(r10) == n10 and all(r[2] is None for r in r10)
v9.execute("INSERT INTO timetable(id,term_id,round_id,kind,parent_id,reason) VALUES (2,1,1,'TA_EDIT',1,'교수님과 통화로 확인')"); v9.commit()
print("  새 버전에 사유 저장:", v9.execute("select kind, parent_id, reason from timetable where id=2").fetchone())

print("\n=== 경로 8: schema_v11(008까지 적용된 모양)에서 009 — 분반별 응답·분반 연강 요청·조율 대상")
v11 = sqlite3.connect(":memory:"); v11.executescript(open(V11, encoding="utf-8").read()); q = v11.execute
sd.seed(v11)
q("INSERT INTO department VALUES (1,'AI','AI융합대학')")
q("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (1,'TA','조교',1,'x'),(2,'PROF','교수2',1,'x'),(3,'PROF','교수3',1,'x')")
q("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)"); q("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
q("INSERT INTO building VALUES (1,'건물')"); q("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (1,1,'101',50,0)")
q("INSERT INTO course(id,term_id,department_id,name,professor_id,session_count,slots_per_session) VALUES (10,1,1,'알고리즘',2,2,1),(11,1,1,'객체지향',3,2,1),(12,1,1,'자료구조',3,2,1)")
q("INSERT INTO course_section VALUES (10,1,2,40),(10,2,2,40),(10,3,3,40)")    # 과목 10: 교수2가 1·2분반, 교수3이 3분반. 과목 11·12 는 분반 행 없음
q("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref,section_pair) VALUES "
  "(100,1,10,2,1,'MUST','BACK_TO_BACK'),(101,1,10,3,0,'NONE','NONE'),(102,1,11,3,0,'NONE','CROSS')")
q("INSERT INTO response_slot VALUES (100,1,'BLOCK'),(100,2,'PREFER'),(101,3,'PREFER')")
q("INSERT INTO other_request(id,response_id,body) VALUES (1,100,'실습 조교 한 명 부탁드립니다')")
q("INSERT INTO request_item(id,response_id,type,value_int,source) VALUES (1,100,'SECTION_COUNT',2,'TA')")
q("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
q("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,reason,status) VALUES (1,1,1,10,1,'겹침','SENT')")
v11.commit()
run(M9, v11)
ok8 = compare("v11 + 009 = schema_v12", v11, V12)
resp = v11.execute("SELECT id, course_id, section_no, professor_id, lab_requirement, single_day_pref FROM course_response ORDER BY course_id, section_no, id").fetchall()
print("  응답 → 분반마다:", resp)
ok8 = ok8 and [(r[1], r[2], r[3]) for r in resp] == [(10, 1, 2), (10, 2, 2), (10, 3, 3), (11, 1, 3)]
ok8 = ok8 and resp[0][0] == 100 and resp[2][0] == 101 and resp[3][0] == 102 and resp[1][4:] == (1, "MUST")   # 첫 분반은 id 그대로, 둘째는 값 복사
slots = v11.execute("SELECT response_id, slot_id, kind FROM response_slot ORDER BY 1,2").fetchall()
print("  칠한 칸:", slots)
ok8 = ok8 and slots == [(100, 1, "BLOCK"), (100, 2, "PREFER"), (101, 3, "PREFER"), (resp[1][0], 1, "BLOCK"), (resp[1][0], 2, "PREFER")]
ok8 = ok8 and v11.execute("SELECT response_id FROM other_request").fetchone() == (100,) and v11.execute("SELECT response_id FROM request_item").fetchone() == (100,)
pairs = v11.execute("SELECT p.course_id, p.professor_id, p.mode, s.seq, s.section_no FROM pair_request p LEFT JOIN pair_request_section s ON s.request_id=p.id ORDER BY 1,2,4").fetchall()
print("  분반 연강·교차 요청:", pairs)
ok8 = ok8 and pairs == [(10, 2, "BACK_TO_BACK", 1, 1), (10, 2, "BACK_TO_BACK", 2, 2), (11, 3, "CROSS", None, None)]   # 과목 11 은 분반 행이 없어 붙일 분반 없음
pr = v11.execute("SELECT id, status, target_kind FROM proposal").fetchall()
print("  안건 보존·target_kind NULL:", pr)
ok8 = ok8 and pr == [(1, "SENT", None)]
for st, kind in (("HOLD", "PARTIAL"), ("NO_OPTION", "UNPLACED")):
    v11.execute("INSERT INTO proposal(round_id,timetable_id,course_id,section_no,status,target_kind) VALUES (1,1,10,2,?,?)", (st, kind))
try:
    v11.execute("INSERT INTO proposal(round_id,timetable_id,course_id,status,target_kind) VALUES (1,1,10,'OPEN','OTHER')"); ok8 = False
except sqlite3.IntegrityError:
    print("  없는 target_kind 거부")
try:
    v11.execute("INSERT INTO course_response(round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (1,10,1,2,0,'NONE')"); ok8 = False
except sqlite3.IntegrityError:
    print("  같은 분반·같은 교수 응답 두 번 거부")

print("\n=== 경로 9: schema_v12(009까지 적용된 모양)에서 010 — 실습실 MUST/NONE, 답장 '지금 자리 그대로'")
q("INSERT INTO message(id,round_id,proposal_id,sender_id,receiver_id,kind,channel,body) VALUES (1,1,1,1,2,'ALTERNATIVE','APP','안내'),(2,1,1,2,1,'REPLY','APP','A')")
q("INSERT INTO proposal_option(id,proposal_id,option_no) VALUES (1,1,1)"); q("INSERT INTO reply_choice VALUES (2,'A',1)"); v11.commit()
before = v11.execute("SELECT id, lab_requirement FROM course_response ORDER BY id").fetchall()
run(M10, v11)
ok9 = compare("v12 + 010", v11)
after = v11.execute("SELECT id, lab_requirement FROM course_response ORDER BY id").fetchall()
print("  실습실 1/0 → MUST/NONE:", before, "→", after)
ok9 = ok9 and [a for a, _ in before] == [a for a, _ in after] and all({1: "MUST", 0: "NONE"}[x] == y for (_, x), (_, y) in zip(before, after))
ok9 = ok9 and v11.execute("SELECT * FROM reply_choice").fetchall() == [(2, "A", 1)]
v11.execute("INSERT INTO reply_choice VALUES (2,'KEEP',NULL)"); print("  답장 선택 KEEP 허용")
for bad in ("UPDATE course_response SET lab_requirement=1 WHERE id=100", "INSERT INTO reply_choice VALUES (2,'STAY',NULL)"):
    try:
        v11.execute(bad); ok9 = False; print("  막아야 함:", bad)
    except sqlite3.IntegrityError:
        print("  거부 OK:", bad)

print("\n결과:", "모두 통과" if ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9 else "실패")
