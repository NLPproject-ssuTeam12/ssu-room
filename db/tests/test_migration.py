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

def compare(label, con):
    new = sqlite3.connect(":memory:"); new.executescript(open(P("schema.sql"), encoding="utf-8").read())
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

print("=== 경로 1: schema_v3 → 001 → 002 → 003 → 004")
old = build_v3(); before = counts(old, KEEP); before["response_slot"] -= 1   # AVOID 1개는 003에서 지워지는 게 정상
run(P("migrations","001_20261121_feedback.sql"), old)
run(P("migrations","002_20261122_phase_other_request.sql"), old)
run(P("migrations","003_20261122_lab_binary_no_avoid.sql"), old)
old.execute("UPDATE term SET phase='ROUND2', phase_changed_at='2026-11-22 10:00:00' WHERE id=1"); old.commit()   # 004 전에 진행 중이던 학기
run(P("migrations","004_20261122_phase_round3.sql"), old)
ok1 = compare("001~004 적용 후", old)
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

print("\n=== 경로 2: schema_v4(001까지 적용된 모양)에서 002 → 003 → 004")
v4 = sqlite3.connect(":memory:"); v4.executescript(open(P("archive","schema_v4.sql"), encoding="utf-8").read()); seed(v4)
v4.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref,note) VALUES (100,1,10,2,'PREFER','PREFER','메모')")
v4.execute("INSERT INTO request_item(response_id,type,value_int) VALUES (100,'SECTION_COUNT',2)"); v4.commit()
run(P("migrations","002_20261122_phase_other_request.sql"), v4)
run(P("migrations","003_20261122_lab_binary_no_avoid.sql"), v4)
run(P("migrations","004_20261122_phase_round3.sql"), v4)
ok2 = compare("v4 + 002~004", v4)
print("  응답:", v4.execute("select id, professor_id, lab_requirement, single_day_pref, prefer_only from course_response").fetchall(), "| 기타 요청:", v4.execute("select body, status from other_request").fetchall())
print("\n결과:", "모두 통과" if ok1 and ok2 else "실패")
