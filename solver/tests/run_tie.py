"""동점 처리와 연강 동선 검사 (작은 가상 DB, 11/25).
  ① 같은 희망 칸(월·수 09:00)을 두고 점수가 같은 두 분반(같은 학년 전공필수라 함께 못 놓음):
     가능한 시간이 적은 분반 → 먼저 임용된 교수 → 과목 번호 순서로 그 칸을 받는다. 같은 입력이면 같은 결과
  ② 같은 학년 전공 두 과목이 같은 요일 이어진 교시면 같은 건물로 (강의실은 달라도 됨). 다른 학년은 보너스 없음
  ③ 동점 순위·동선은 원래 점수(objective)를 바꾸지 않는다 (두 단계 풀이: 1단계 원래 점수, 2단계 동선)
  python solver/tests/run_tie.py"""
import os, sys, sqlite3
from test_data import SCHEMA_PATH          # 경로 설정은 test_data 가 한다
import seed_time_slot as sd, solver_core as sc, db as hdb

results = []
def report(label, ok, detail=""):
    results.append(ok); print(("OK  " if ok else "틀림") + f" {label} {detail}")


def small():
    c = hdb.connect(":memory:"); c.executescript(open(SCHEMA_PATH, encoding="utf-8").read()); sd.seed(c)
    c.execute("INSERT INTO department VALUES (1,'가상학과','가상대학')")
    c.execute("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)")
    c.execute("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
    for b in (1, 2):
        c.execute("INSERT INTO building VALUES (?,?)", (b, f"가상건물{b}"))
        for k in range(2):
            c.execute("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (?,?,?,?,?)", (b * 100 + k, b, f"{b}0{k}", 60, 0))
    c.commit(); return c


SL = None
def course(c, cid, prof, cat, year, prefer=(), only=None, hire=None):
    global SL
    SL = SL or {(d, t): i for i, d, t in c.execute("SELECT id, day, start_time FROM time_slot")}
    if not c.execute("SELECT 1 FROM user WHERE id=?", (prof,)).fetchone():
        c.execute("INSERT INTO user(id,role,name,department_id,password_hash,hire_year) VALUES (?,?,?,?,?,?)",
                  (prof, "PROF", f"가상교수{prof}", 1, "x", hire))
    c.execute("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, 1, 1, f"과목{cid}", prof, cat, year, 2, 1))
    c.execute("INSERT INTO course_section VALUES (?,?,?,?)", (cid, 1, prof, 30))
    c.execute("INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?,?)",
              (cid, 1, cid, 1, prof, "NONE", "NONE"))
    for x in prefer:
        c.execute("INSERT INTO response_slot VALUES (?,?,'PREFER')", (cid, SL[x]))
    if only is not None:
        for x, sid in SL.items():
            if x not in only and x not in prefer:
                c.execute("INSERT INTO response_slot VALUES (?,?,'BLOCK')", (cid, sid))
    c.commit()


def cells(c, tt, cid):
    return sorted(c.execute("""SELECT ts.day, ts.start_time, r.building_id FROM assignment a JOIN time_slot ts ON ts.id=a.slot_id
                               JOIN room r ON r.id=a.room_id WHERE a.timetable_id=? AND a.course_id=?""", (tt, cid)).fetchall())


P = [("월", "09:00"), ("수", "09:00")]
got = lambda c, tt, cid: [(d, t) for d, t, _ in cells(c, tt, cid)] == sorted(P)

# ① 동점 처리 (같은 학년 전공필수 둘은 겹칠 수 없음 → 한 과목만 월·수 09:00)
c = small()
course(c, 11, 1, "전공필수", "1", prefer=P)
course(c, 12, 2, "전공필수", "1", prefer=P, only=P + [("화", "13:30"), ("목", "13:30"), ("화", "15:00"), ("목", "15:00")])
tt = sc.solve(c, 1, 1, time_limit=20)["timetable_id"]
report("① 가능한 시간이 적은 분반(과목 12, 번호는 뒤)이 희망 칸을 받음", got(c, tt, 12) and not got(c, tt, 11), f"({cells(c, tt, 11)} / {cells(c, tt, 12)})")

c = small()
course(c, 11, 1, "전공필수", "1", prefer=P, hire=2015)
course(c, 12, 2, "전공필수", "1", prefer=P, hire=2008)
tt = sc.solve(c, 1, 1, time_limit=20)["timetable_id"]
report("① 가능한 시간이 같으면 먼저 임용된 교수(2008, 과목 12)가 받음", got(c, tt, 12) and not got(c, tt, 11))

c = small()
course(c, 11, 1, "전공필수", "1", prefer=P, hire=2008)
course(c, 12, 2, "전공필수", "1", prefer=P)                         # 연차 없음 → 뒤
tt = sc.solve(c, 1, 1, time_limit=20)["timetable_id"]
report("① 연차가 없는 교수는 연차 있는 교수 뒤", got(c, tt, 11) and not got(c, tt, 12))

wins = set()
for seed in range(4):
    c = small()
    course(c, 11, 1, "전공필수", "1", prefer=P)
    course(c, 12, 2, "전공필수", "1", prefer=P)
    r = sc.solve(c, 1, 1, time_limit=20, seed=seed); tt = r["timetable_id"]
    wins.add(11 if got(c, tt, 11) else 12 if got(c, tt, 12) else None)
report("① 모두 같으면 과목 번호가 앞인 분반(11), 실행을 바꿔도 같은 결과", wins == {11}, f"({wins})")
report("③ 원래 점수는 희망 -20 그대로(동선·동점 순위는 2단계·보너스로 따로)", r["objective"] == -20,
       f"(objective {r['objective']}, 동선 {r['flow_pairs']}, 2단계 {r['flow_status']})")

# ② 동선: 과목 21(2학년 전공선택)은 월·수 09:00만, 과목 22(2학년 전공기초)는 월·수 10:30 또는 화·목 15:00 (희망 없음)
def flow_case(year22, flow_w=None):
    c = small()
    course(c, 21, 1, "전공선택", "2", only=P)
    course(c, 22, 2, "전공기초", year22, only=[("월", "10:30"), ("수", "10:30"), ("화", "15:00"), ("목", "15:00")])
    r = sc.solve(c, 1, 1, time_limit=20, weights=None if flow_w is None else {"flow": flow_w})
    return c, r
c, r = flow_case("2")
a, b = cells(c, r["timetable_id"], 21), cells(c, r["timetable_id"], 22)
report("② 같은 학년 전공: 바로 이어진 교시(월·수 10:30)에 같은 건물", [x[:2] for x in b] == [("수", "10:30"), ("월", "10:30")]
       and {x[2] for x in a} == {x[2] for x in b} and len({x[2] for x in a}) == 1 and r["flow_pairs"] == 2, f"({a} / {b}, 동선 {r['flow_pairs']})")
c, r = flow_case("3")
report("② 학년이 다르면 동선 보너스 없음", r["flow_pairs"] == 0, f"(동선 {r['flow_pairs']})")
c, r = flow_case("2", flow_w=0)
report("② flow 가중치 0 이면 보너스 없음", r["flow_pairs"] == 0)

print("\n결과:", "모두 통과" if all(results) else "실패")
sys.exit(0 if all(results) else 1)
