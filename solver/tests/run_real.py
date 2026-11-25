"""실제 개설 강좌(분반 목록 CSV, real_convert.py 결과)로 풀이 시간과 못 놓는 분반 수를 잰다. 숫자만 출력한다(과목명 없음).

  python solver/tests/run_real.py data/private/real/2026-2_sections.csv [시간 제한 초, 기본 60]

입력 만들기 (실제 값 / 가정):
- 실제: 과목, 이수구분, 학년, 분반, 담당 교수(가명), 수강 인원, 강의실(파일에 나온 것), 실제 배정 시간
- 가정: 강의실 정원 = 그 강의실을 쓴 분반 인원 중 가장 큰 값 (파일에 정원이 없음)
        실습실 = CLAUDE.md 목록(21101·21206·21305·21306·03407·03408·03411·19328)
        수업 구성 = 실제 시간에서 요일별 이어진 칸 수 (격자 밖·불규칙하면 요일 수 × 1칸)
        채플 칸 = 가상 (1학년 화·2학년 목·3학년 수·4학년 월 12:00)
두 경우를 푼다
  ① 응답 없음: 교수 응답 없이 하드 규칙(겹침·정원·채플 등)만
  ② 실제 시간을 희망으로: 교수마다 실제로 받은 칸을 희망(PREFER), 가상 불가 6칸, 실습실 = 실제 강의실이 실습실이면 1,
     주 1회 연강 = 실제가 하루 2칸이면 무조건, 희망 건물 = 실제로 가장 많이 쓴 건물
"""
import csv
import random
import sys
import time
from collections import Counter, defaultdict

from test_data import SCHEMA_PATH, sd, sc, db
from test_solver2 import verify

LABS = {"21101", "21206", "21305", "21306", "03407", "03408", "03411", "19328"}
CHAPEL = {"1": ("화", "12:00"), "2": ("목", "12:00"), "3": ("수", "12:00"), "4": ("월", "12:00")}   # 가상
GRID = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30"]


def structure(times):
    """실제 시간 → (회차 수, 한 회 칸 수, 실제 칸 목록[(요일, 시작)], 규칙적인지)"""
    by_day = defaultdict(list)
    for t in times:
        d, st, k = t.split()
        by_day[d].append((st, int(k)))
    cells = [(d, st) for d, xs in by_day.items() for st, k in xs if k]
    if any(k == 0 for xs in by_day.values() for _, k in xs):          # 격자 밖 (50분 등)
        return len(by_day), 1, [], False
    runs = []
    for d, xs in by_day.items():
        idx = sorted(GRID.index(st) for st, _ in xs)
        if idx != list(range(idx[0], idx[0] + len(idx))):
            return len(cells), 1, cells, False
        runs.append(len(idx))
    if len(set(runs)) != 1:
        return len(cells), 1, cells, False
    return len(by_day), runs[0], cells, True


def build(rows, with_responses):
    c = db.connect(":memory:"); c.executescript(open(SCHEMA_PATH, encoding="utf-8").read()); sd.seed(c)
    q = c.execute
    q("INSERT INTO department VALUES (1,'AI소프트웨어학부','AI대학')")
    q("INSERT INTO term(id,year,semester,grid_id) VALUES (1,2026,'2',1)")
    q("INSERT INTO round VALUES (1,1,1,NULL,'2026-11-20','CLOSED')")
    SL = {(d, t): i for i, d, t in q("SELECT id, day, start_time FROM time_slot")}
    for yr, (d, t) in CHAPEL.items():
        q("INSERT INTO chapel_slot VALUES (1,?,?)", (yr, SL[(d, t)]))
    profs = sorted({r["professor"] for r in rows})
    pid = {p: i + 1 for i, p in enumerate(profs)}
    for p, i in pid.items():
        q("INSERT INTO user(id,role,name,department_id,password_hash) VALUES (?,?,?,?,?)", (i, "PROF", p, 1, "x"))
    rooms = sorted({r["room"] for r in rows if r["room"]})
    blds = sorted({x.split()[0] for x in rooms})
    bid = {b: i + 1 for i, b in enumerate(blds)}
    for b, i in bid.items():
        q("INSERT INTO building VALUES (?,?)", (i, b))
    cap = Counter()
    for r in rows:
        if r["room"]:
            cap[r["room"]] = max(cap[r["room"]], int(r["enrollment"]))
    rid_of = {}
    for i, x in enumerate(rooms, 1):
        b, no = x.split()
        q("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (?,?,?,?,?)", (i, bid[b], no, cap[x], int(no in LABS)))
        rid_of[x] = i
    courses = {}
    stats = Counter()
    for r in rows:
        n, k, cells, regular = structure(r["times"].split("; ") if r["times"] else [])
        stats["불규칙·격자 밖"] += not regular
        key = r["course"]
        if key not in courses:
            courses[key] = len(courses) + 1
            q("INSERT INTO course(id,term_id,department_id,name,professor_id,category,target_year,session_count,slots_per_session) VALUES (?,?,?,?,?,?,?,?,?)",
              (courses[key], 1, 1, f"과목{courses[key]}", pid[r["professor"]], r["category"], r["year"] or None, n, k))
        q("INSERT INTO course_section VALUES (?,?,?,?)", (courses[key], int(r["section"]), pid[r["professor"]], int(r["enrollment"]) or None))
        r["_cid"], r["_cells"], r["_long"] = courses[key], cells, regular and n * k == 2 and k == 2
    if with_responses:
        rnd = random.Random(1)
        by_cp = defaultdict(list)
        for r in rows:
            by_cp[(r["_cid"], r["professor"])].append(r)
        bld_use = defaultdict(Counter)
        for r in rows:
            if r["room"]:
                bld_use[r["professor"]][r["room"].split()[0]] += 1
        i = 0
        for (cid, p), rs in by_cp.items():
            lab = int(any(r["room"].split()[-1] in LABS for r in rs if r["room"]))
            single = "MUST" if all(r["_long"] for r in rs) else "NONE"
            pref = {SL[(d, st)] for r in rs for d, st in r["_cells"] if (d, st) in SL}
            block = rnd.sample(sorted(set(SL.values()) - pref), 6)
            secs_p = [r[0] for r in q("SELECT section_no FROM course_section WHERE course_id=? AND professor_id=? ORDER BY 1",
                                       (cid, pid[p])).fetchall()] or [1]
            for sec in secs_p:                    # 희망 입력은 분반마다 (11/25). 같은 교수의 분반은 같은 값
                i += 1
                q("INSERT INTO course_response(id,round_id,course_id,section_no,professor_id,lab_requirement,single_day_pref) VALUES (?,?,?,?,?,?,?)",
                  (i, 1, cid, sec, pid[p], lab, single))
                for s in pref:
                    q("INSERT INTO response_slot VALUES (?,?,'PREFER')", (i, s))
                for s in block:
                    q("INSERT INTO response_slot VALUES (?,?,'BLOCK')", (i, s))
        for p, cnt in bld_use.items():
            q("INSERT INTO professor_building_pref VALUES (?,?)", (pid[p], bid[cnt.most_common(1)[0][0]]))
    c.commit()
    return c, stats, len(rooms), sum(int(x.split()[-1] in LABS) for x in rooms)


def measure(label, rows, with_responses, limit):
    c, stats, n_rooms, n_labs = build([dict(r) for r in rows], with_responses)
    n_sec = c.execute("SELECT COUNT(*) FROM course_section").fetchone()[0]
    n_ses = c.execute("SELECT SUM(c.session_count) FROM course_section s JOIN course c ON c.id=s.course_id").fetchone()[0]
    t0 = time.time()
    r = sc.solve(c, 1, 1, time_limit=limit)
    wall = time.time() - t0
    un_secs = {(k[0], k[1]) for k in r["unplaced"]}
    print(f"\n[{label}] 분반 {n_sec}개(회차 {n_ses}개), 강의실 {n_rooms}개(실습실 {n_labs}), 불규칙·격자 밖 {stats['불규칙·격자 밖']}개")
    print(f"  상태 {r['status']}, 풀이 {r['seconds']:.1f}초 (호출 전체 {wall:.1f}초, 제한 {limit}초)")
    print(f"  못 놓은 분반 {len(un_secs)}개 / 회차 {len(r['unplaced'])}개, 지원불가 안내 {len(r['unsupported'])}건")
    ok = verify(c, r["timetable_id"]) if r["timetable_id"] else False
    if with_responses and r["timetable_id"]:
        same = c.execute("""SELECT COUNT(*) FROM (SELECT a.course_id, a.section_no FROM assignment a
                            JOIN course_response cr ON cr.course_id=a.course_id AND cr.section_no=a.section_no
                             AND cr.professor_id=(SELECT professor_id FROM course_section WHERE course_id=a.course_id AND section_no=a.section_no)
                            GROUP BY 1,2 HAVING SUM(a.slot_id IN (SELECT slot_id FROM response_slot WHERE response_id=cr.id AND kind='PREFER'))=COUNT(*))""").fetchone()[0]
        inb = c.execute("""SELECT AVG(r.building_id = p.building_id) FROM v_schedule v JOIN room r ON r.id=v.room_id
                           JOIN professor_building_pref p ON p.professor_id=v.professor_id WHERE v.timetable_id=?""", (r["timetable_id"],)).fetchone()[0]
        print(f"  모든 칸이 희망(실제 시간) 안인 분반 {same}/{n_sec}, 희망 건물에 놓인 회차 {inb:.0%}")
    return ok and r["timetable_id"] is not None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: python solver/tests/run_real.py 분반목록.csv [시간 제한 초]")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")))
    a = measure("① 응답 없음", rows, False, limit)
    b = measure("② 실제 시간을 희망으로 (불가 칸·채플은 가상)", rows, True, limit)
    print("\n결과:", "두 경우 모두 검증 위반 없음" if a and b else "검증 위반 또는 풀이 실패 있음")
