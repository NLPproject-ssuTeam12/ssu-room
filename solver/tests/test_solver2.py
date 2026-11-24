import time, sqlite3
from test_data import build, SCHEMA_PATH   # 경로 설정은 test_data가 한다
import solver_core as sc

def add_pairs(c):
    two = [r[0] for r in c.execute("""SELECT cs.course_id FROM course_section cs JOIN course_response cr ON cr.course_id=cs.course_id
                                       GROUP BY cs.course_id HAVING COUNT(DISTINCT cs.section_no)=2 ORDER BY cs.course_id LIMIT 4""")]
    modes = dict(zip(two, ['CROSS', 'CROSS', 'BACK_TO_BACK', 'CROSS']))
    for cid, mode in modes.items():   # 교수 응답 칸으로 (두 분반 모두 그 교수)
        c.execute("UPDATE course_response SET section_pair=? WHERE course_id=?", (mode, cid))
    for cid in modes:   # 분반 연강·교차를 요청한 과목은 주1회 연강 응답을 '필요 없음'으로
        c.execute("UPDATE course_response SET single_day_pref='NONE' WHERE course_id=?", (cid,))
    c.commit(); return modes

def add_section_profs(c, n=4):
    """2분반 과목 일부에서 2분반을 다른 교수가 맡게 한다(그 교수는 아직 응답 없음)."""
    rows = c.execute("""SELECT c.id, c.professor_id FROM course c JOIN course_response cr ON cr.course_id=c.id
                         WHERE (SELECT COUNT(*) FROM course_section s WHERE s.course_id=c.id)=2
                           AND c.id NOT IN (SELECT course_id FROM course_response WHERE section_pair<>'NONE')
                         ORDER BY c.id LIMIT ?""", (n,)).fetchall()
    out = {}
    for cid, prof in rows:
        other = prof % 30 + 1
        c.execute("UPDATE course_section SET professor_id=? WHERE course_id=? AND section_no=2", (other, cid))
        out[cid] = other
    c.commit(); return out

def verify(c, tt, label=""):
    """규칙 위반을 DB 쿼리로 독립 검사"""
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    res = dict(
        prof_conflict=q("select count(*) from v_professor_conflict where timetable_id=?", tt),
        block=q("""SELECT COUNT(*) FROM assignment a JOIN course c0 ON c0.id=a.course_id
                   JOIN course_response cr ON cr.course_id=a.course_id AND cr.professor_id=COALESCE((SELECT professor_id FROM course_section WHERE course_id=a.course_id AND section_no=a.section_no), c0.professor_id)
                   JOIN response_slot rs ON rs.response_id=cr.id AND rs.slot_id=a.slot_id AND rs.kind='BLOCK' WHERE a.timetable_id=?""", tt),
        capacity=q("""SELECT COUNT(*) FROM assignment a JOIN course_section s ON s.course_id=a.course_id AND s.section_no=a.section_no
                      JOIN room r ON r.id=a.room_id WHERE a.timetable_id=? AND s.enrollment>r.capacity""", tt),   # 분반 인원 > 정원
        lab_req=q("""SELECT COUNT(*) FROM assignment a JOIN course c0 ON c0.id=a.course_id
                     JOIN course_response cr ON cr.course_id=a.course_id AND cr.professor_id=COALESCE((SELECT professor_id FROM course_section WHERE course_id=a.course_id AND section_no=a.section_no), c0.professor_id)
                     JOIN room r ON r.id=a.room_id
                     WHERE a.timetable_id=? AND cr.lab_requirement=1 AND r.is_lab=0""", tt),
        same_day=q("""SELECT COUNT(*) FROM (SELECT a.course_id,a.section_no,ts.day,COUNT(DISTINCT a.session_no) n FROM assignment a
                      JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? GROUP BY 1,2,3 HAVING n>1)""", tt),
        chapel=q("""SELECT COUNT(*) FROM assignment a JOIN course c ON c.id=a.course_id JOIN timetable t ON t.id=a.timetable_id
                    JOIN chapel_slot ch ON ch.term_id=t.term_id AND ch.target_year=c.target_year AND ch.slot_id=a.slot_id
                    WHERE a.timetable_id=? AND c.category='전공필수'""", tt),          # 전공필수가 그 학년 채플 칸에
        late_long=q("""SELECT COUNT(*) FROM (SELECT a.course_id,a.section_no,a.session_no,COUNT(*) n,MIN(ts.start_time) st FROM assignment a
                    JOIN time_slot ts ON ts.id=a.slot_id WHERE a.timetable_id=? GROUP BY 1,2,3) WHERE n>=2 AND st>='18:00'""", tt))   # 18:00 이후 시작 연강
    # 연강 응답대로 구성되었나: MUST=연속 2칸 한 번, NONE=1칸씩 두 번. 미응답은 원래 입력 구성
    shape = {}
    for cid, sec, ss, n in c.execute("SELECT course_id, section_no, session_no, COUNT(*) FROM assignment WHERE timetable_id=? GROUP BY 1,2,3", (tt,)):
        shape.setdefault((cid, sec), []).append(n)
    wrong = 0
    for (cid, sec), ns in shape.items():
        if sum(ns) < 2: continue   # 못 놓은 회차가 있는 분반은 모양을 따지지 않는다(못놓음으로 따로 집계)
        if c.execute("SELECT session_count*slots_per_session FROM course WHERE id=?", (cid,)).fetchone()[0] != 2: continue   # 주 1회 연강은 주당 2칸 수업만
        prof = c.execute("SELECT COALESCE((SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?), (SELECT professor_id FROM course WHERE id=?))", (cid, sec, cid)).fetchone()[0]
        r = c.execute("SELECT single_day_pref FROM course_response WHERE course_id=? AND professor_id=?", (cid, prof)).fetchone()
        pref = r[0] if r else None
        sc_, k_ = c.execute("SELECT session_count, slots_per_session FROM course WHERE id=?", (cid,)).fetchone()
        ok = {"MUST": ns == [2], "NONE": sorted(ns) == [1, 1], None: sorted(ns) == [k_] * sc_}[pref]   # 미응답은 입력된 구성 그대로
        if not ok and WRONG_LOG is not None: WRONG_LOG.append((cid, sec, ns))
        wrong += (not ok)
    res["single_day_shape"] = wrong
    bad = {k: v for k, v in res.items() if v}
    print(f"  [검증{label}] 위반:", bad if bad else "없음")
    return not bad

WRONG_LOG = None

def pair_check(c, tt, modes):
    for cid, mode in modes.items():
        rows = c.execute("""SELECT a.section_no,a.session_no,ts.day,ts.period_no FROM assignment a JOIN time_slot ts ON ts.id=a.slot_id
                            WHERE a.timetable_id=? AND a.course_id=?""", (tt, cid)).fetchall()
        t = {(s, ss): (d, p) for s, ss, d, p in rows}
        if len(t) < 4: print(f"  과목{cid} {mode}: 못 놓은 회차 있음"); continue
        adj = all(t[(1, s)][0] == t[(2, s)][0] and abs(t[(1, s)][1] - t[(2, s)][1]) == 1 for s in (1, 2))
        cross = t[(1, 1)][1] == t[(2, 2)][1] and t[(1, 2)][1] == t[(2, 1)][1]
        print(f"  과목{cid} {mode}: {'OK' if adj and (cross or mode=='BACK_TO_BACK') else '위반'}")

def snapshot(c, tt):
    return {(a,b,cc):(d,e) for a,b,cc,d,e in c.execute("select course_id,section_no,session_no,min(slot_id),min(room_id) from assignment where timetable_id=? group by 1,2,3",(tt,))}
