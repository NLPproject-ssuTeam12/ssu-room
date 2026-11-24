import random, sqlite3, time
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_SOLVER = os.path.dirname(_HERE)                                   # solver/
_DB = os.path.join(os.path.dirname(_SOLVER), "db")                 # db/
for _p in (_SOLVER, _DB):
    if _p not in sys.path: sys.path.insert(0, _p)
SCHEMA_PATH = os.path.join(_DB, "schema.sql")
import seed_time_slot as sd, solver_core as sc, db

def build(seed=1, n_courses=70, n_prof=30):
    rnd = random.Random(seed)
    c = db.connect(":memory:"); c.executescript(open(SCHEMA_PATH, encoding="utf-8").read()); sd.seed(c)
    assert c.execute("pragma foreign_keys").fetchone()[0] == 1   # 외래키 검사 켜진 채로 테스트
    c.execute("INSERT INTO department VALUES (1,'AI소프트웨어학부','AI융합대학')")
    c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)")
    c.execute("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
    for i in range(1, n_prof+1):
        c.execute("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (i,'PROF',f'교수{i}',1,'x'))
    for b in range(1,5): c.execute("INSERT INTO building VALUES (?,?)",(b,f'건물{b}'))
    rid = 0
    for b in range(1,5):
        for k in range(5):
            rid += 1
            c.execute("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (?,?,?,?,?)",
                      (rid,b,f'{b}0{k}', rnd.choice([40,60,80,100]), 1 if k==0 and b<=3 else 0))
    rid_resp = 0
    for cid in range(1, n_courses+1):
        prof = rnd.randint(1, n_prof)
        cat = rnd.choice(['전공필수','전공선택','전공선택','교양선택'])
        yr, enr = str(rnd.randint(1,4)), rnd.randint(25,90)     # 과목 전체 인원 (분반으로 나눈다)
        c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
                  (cid,1,1,f'과목{cid}',prof,cat,yr,2,1))
        lab = rnd.choices([1,0,None],[0.20,0.40,0.40])[0]
        single_day = rnd.choices(['MUST','PREFER','NONE'],[0.15,0.25,0.60])[0]
        if lab is None:            # 미회신 교수: 응답 행 없음, 분반 1개
            c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, 1, prof, enr)); continue
        rid_resp += 1
        c.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?)",
                  (rid_resp,1,cid,prof,lab,single_day))
        slots = [r[0] for r in c.execute("SELECT id FROM time_slot")]
        for sid in rnd.sample(slots, 6): c.execute("INSERT OR IGNORE INTO response_slot VALUES (?,?,?)",(rid_resp,sid,'BLOCK'))
        for sid in rnd.sample(slots, 4): c.execute("INSERT OR IGNORE INTO response_slot VALUES (?,?,?)",(rid_resp,sid,'PREFER'))
        n_sec = 2 if rnd.random() < 0.3 else 1   # 분반 수 (오프라인 회의에서 정해 조교가 입력)
        for s in range(1, n_sec+1):
            c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, s, prof, -(-enr // n_sec)))
    for p in range(1,n_prof+1):
        c.execute("INSERT INTO professor_building_pref VALUES (?,?)",(p,rnd.randint(1,4)))   # 희망 건물 하나
    c.commit(); return c

