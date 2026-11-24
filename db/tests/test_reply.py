"""교수 직접 회신 함수 검사 (메모리 DB, 가상 데이터).
  python db/tests/test_reply.py      (pytest 로도 돈다)
교수 이름은 가상(교수가·교수나·교수다)이다."""
import json, os, sqlite3, sys
DB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # db/
sys.path.insert(0, DB)
import db as hdb
import seed_time_slot as sd

COND = {"day_slots": {"1": ["09:00", "10:30"], "3": []}, "end_before": [{"day": 2, "time": "17:00"}]}


def make():
    """조교 1, 교수 3, 과목 2(과목 10: 1분반은 교수가(기본 담당), 2분반은 교수나), 안건 1(과목 10 2분반)."""
    con = sqlite3.connect(":memory:")
    con.executescript(open(os.path.join(DB, "schema.sql"), encoding="utf-8").read())
    q = con.execute
    sd.seed(con)
    q("INSERT INTO department VALUES (1,'AI','AI융합대학')")
    q("""INSERT INTO user(id,role,name,department_id,password_hash) VALUES
         (1,'TA','조교',1,'x'),(2,'PROF','교수가',1,'x'),(3,'PROF','교수나',1,'x'),(4,'PROF','교수다',1,'x')""")
    q("INSERT INTO term(id,year,semester,grid_id,phase) VALUES (1,2027,'1',1,'ROUND1')")
    q("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (1,1,1,'2026-12-01')")
    q("INSERT INTO round_invite(round_id,professor_id) VALUES (1,3)")
    q("INSERT INTO building VALUES (1,'건물')"); q("INSERT INTO room(id,building_id,room_no,capacity,is_lab) VALUES (1,1,'101',50,0)")
    q("""INSERT INTO course(id,term_id,department_id,name,professor_id,expected_enrollment,session_count,slots_per_session)
         VALUES (10,1,1,'자료구조',2,80,2,1),(11,1,1,'알고리즘',4,40,2,1)""")
    q("INSERT INTO course_section VALUES (10,2,3)")
    q("INSERT INTO solver_run(id,round_id,status) VALUES (1,1,'OPTIMAL')")
    q("INSERT INTO timetable(id,term_id,round_id,kind,solver_run_id) VALUES (1,1,1,'DRAFT',1)")
    q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,reason) VALUES (1,1,1,10,2,'희망 시간 겹침'),(2,1,1,11,1,'겹침')")
    q("INSERT INTO proposal_option(id,proposal_id,option_no,source) VALUES (1,1,1,'SOLVER'),(2,1,2,'SOLVER'),(3,2,1,'SOLVER')")
    q("""INSERT INTO message(id,round_id,proposal_id,sender_id,receiver_id,kind,channel,body,sent_at)
         VALUES (1,1,1,1,3,'ALTERNATIVE','APP','1차 조율 안내','2026-11-24 09:00:00'),
                (2,1,2,1,4,'ALTERNATIVE','APP','1차 조율 안내','2026-11-24 09:00:00')""")
    q("UPDATE proposal SET status='SENT'")
    con.commit()
    con.execute("PRAGMA foreign_keys = ON")
    return con


def raises(fn, *a, has="", **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        assert has in str(e), f"오류 문구에 '{has}' 없음: {e}"
        return str(e)
    raise AssertionError(f"ValueError 가 나야 함: {fn.__name__}{a}")


def status(con, pid=1):
    return con.execute("SELECT status FROM proposal WHERE id=?", (pid,)).fetchone()[0]


def test_professor_owns():
    con = make()
    assert hdb.professor_owns(con, 3, 10, 2)              # course_section 지정
    assert not hdb.professor_owns(con, 2, 10, 2)          # 기본 담당이어도 지정된 분반은 아님
    assert hdb.professor_owns(con, 2, 10, 1)              # 지정 없는 분반은 course.professor_id
    assert hdb.professor_owns(con, 2, 10) and hdb.professor_owns(con, 3, 10)   # 어느 분반이든
    assert not hdb.professor_owns(con, 4, 10) and not hdb.professor_owns(con, 3, 99)


def test_reject_not_owner():
    con = make()
    raises(hdb.add_reply, con, 1, 2, "A안 좋아요", has="담당 교수가 아닙니다")
    raises(hdb.add_reply, con, 99, 3, "A안", has="없는 조율 안건")
    assert con.execute("SELECT count(*) FROM message WHERE kind='REPLY'").fetchone()[0] == 0


def test_reject_by_status():
    for st in ("OPEN", "RESOLVED", "KEPT", "NEXT"):
        con = make(); con.execute("UPDATE proposal SET status=? WHERE id=1", (st,)); con.commit()
        raises(hdb.add_reply, con, 1, 3, "A안 좋아요", has=st)
        assert con.execute("SELECT count(*) FROM message WHERE kind='REPLY'").fetchone()[0] == 0


def test_add_reply_fills_fields():
    con = make()
    mid = hdb.add_reply(con, 1, 3, "A안 좋아요")
    row = con.execute("""SELECT round_id, proposal_id, sender_id, receiver_id, kind, channel, body, sent_at IS NOT NULL,
                         delivery_status, reply_to_id FROM message WHERE id=?""", (mid,)).fetchone()
    assert row == (1, 1, 3, 1, "REPLY", "APP", "A안 좋아요", 1, "RECEIVED", 1), row
    inv = con.execute("SELECT status, responded_at IS NOT NULL FROM round_invite WHERE round_id=1 AND professor_id=3").fetchone()
    assert inv == ("RESPONDED", 1), inv
    assert status(con) == "SENT"


def test_reply_to_checks():
    con = make()
    raises(hdb.add_reply, con, 1, 3, "답", reply_to_id=2, has="다른 안건")
    raises(hdb.add_reply, con, 1, 3, "답", reply_to_id=99, has="없는 메시지")
    mid = hdb.add_reply(con, 1, 3, "답", reply_to_id=1, channel="EMAIL")
    raises(hdb.add_reply, con, 1, 3, "답", reply_to_id=mid, has="교수 답장에는")


def test_receiver_falls_back_to_ta():
    con = make()
    con.execute("UPDATE message SET sender_id=NULL WHERE id=1"); con.commit()
    mid = hdb.add_reply(con, 1, 3, "B안")
    assert con.execute("SELECT receiver_id FROM message WHERE id=?", (mid,)).fetchone()[0] == 1
    con.execute("UPDATE user SET role='PROF' WHERE id=1"); con.commit()
    raises(hdb.add_reply, con, 1, 3, "B안", has="조교가 없습니다")


def test_resubmit_keeps_history_latest_is_target():
    con = make()
    m1 = hdb.add_reply(con, 1, 3, "A안 좋아요")
    hdb.save_interpretation(con, m1, "ACCEPT", {"picks": ["A"]}, model_name="keyword", chosen_option_id=1)
    assert status(con) == "PROPOSED"
    m2 = hdb.add_reply(con, 1, 3, "다시 생각해 보니 화요일 오전만 됩니다")   # 조교 결정 전 재제출
    assert m2 > m1
    assert con.execute("SELECT count(*) FROM message WHERE proposal_id=1 AND kind='REPLY'").fetchone()[0] == 2
    assert con.execute("SELECT label FROM reply_interpretation WHERE message_id=?", (m1,)).fetchone()[0] == "ACCEPT"   # 이력
    raises(hdb.save_interpretation, con, m1, "REJECT", {}, has="가장 최근 답장")
    raises(hdb.decide_reply, con, m1, 1, "CONFIRM", proposal_action="move", has="가장 최근 답장")
    raises(hdb.decide_reply, con, m2, 1, "CONFIRM", proposal_action="move", has="해석이 아직 없습니다")
    hdb.save_interpretation(con, m2, "CONDITIONAL", json.dumps({"conditions": COND}), model_name="llm")
    hdb.save_interpretation(con, m2, "CONDITIONAL", {"conditions": COND, "v": 2}, model_name="llm")   # 갱신
    row = con.execute("SELECT label, extracted_json, model_name FROM reply_interpretation WHERE message_id=?", (m2,)).fetchone()
    assert row[0] == "CONDITIONAL" and json.loads(row[1])["v"] == 2 and row[2] == "llm"
    assert status(con) == "PROPOSED"


def test_save_interpretation_checks():
    con = make()
    raises(hdb.save_interpretation, con, 1, "ACCEPT", {}, has="REPLY")              # 조율 메시지는 해석 대상이 아님
    m = hdb.add_reply(con, 1, 3, "A안")
    raises(hdb.save_interpretation, con, m, "수용", {}, has="ACCEPT")
    raises(hdb.save_interpretation, con, m, "ACCEPT", {}, chosen_option_id=3, has="이 안건의 대안이 아닙니다")
    raises(hdb.save_interpretation, con, m, "ACCEPT", "[1,2]", has="객체")
    assert status(con) == "SENT"


def test_decide_confirm_and_conditions():
    con = make()
    assert hdb.confirmed_conditions(con, 1) is None
    m = hdb.add_reply(con, 1, 3, "화 오전이나 목요일, 수요일은 17시 전")
    hdb.save_interpretation(con, m, "CONDITIONAL", {"conditions": COND})
    assert hdb.confirmed_conditions(con, 1) is None                                  # 해석만으로는 확인된 조건 아님
    raises(hdb.decide_reply, con, m, 3, "CONFIRM", proposal_action="move", has="조교만")
    raises(hdb.decide_reply, con, m, 1, "OK", has="CONFIRM")
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", proposal_action="move", conditions={"day_slots": {1: ["09:00"]}}, has="문자열")
    hdb.decide_reply(con, m, 1, "CONFIRM", proposal_action="move", conditions=COND)
    assert status(con) == "RESOLVED"
    assert hdb.confirmed_conditions(con, 1) == COND
    row = con.execute("SELECT ta_action, ta_user_id, ta_at IS NOT NULL, ta_reason, extracted_json FROM reply_interpretation WHERE message_id=?", (m,)).fetchone()
    assert row[:4] == ("CONFIRM", 1, 1, None)
    assert json.loads(row[4])["conditions"] == COND                                  # 해석 결과는 그대로 남음
    raises(hdb.decide_reply, con, m, 1, "KEEP", has="이미 결정")
    raises(hdb.add_reply, con, 1, 3, "그래도 바꾸고 싶어요", has="RESOLVED")       # 결정 뒤 재제출 거부
    raises(hdb.save_interpretation, con, m, "REJECT", {}, has="이미 결정")


def test_decide_edit_requires_reason():
    con = make()
    m = hdb.add_reply(con, 1, 3, "B안이요")
    hdb.save_interpretation(con, m, "ACCEPT", {"picks": ["B"]}, chosen_option_id=2)
    raises(hdb.decide_reply, con, m, 1, "EDIT", conditions=COND, has="사유")
    raises(hdb.decide_reply, con, m, 1, "EDIT", reason="  ", has="사유")
    assert status(con) == "PROPOSED"
    edited = {"day_slots": {"4": ["13:30"]}, "end_before": []}
    hdb.decide_reply(con, m, 1, "EDIT", reason="교수님과 통화로 금요일 오후 확인", conditions=edited)
    assert status(con) == "RESOLVED" and hdb.confirmed_conditions(con, 1) == edited
    assert con.execute("SELECT ta_reason FROM reply_interpretation WHERE message_id=?", (m,)).fetchone()[0].startswith("교수님과")


def test_decide_keep():
    con = make()
    m = hdb.add_reply(con, 1, 3, "셋 다 어렵습니다")
    hdb.save_interpretation(con, m, "REJECT", {})
    raises(hdb.decide_reply, con, m, 1, "KEEP", conditions=COND, has="조건을 넣지")
    hdb.decide_reply(con, m, 1, "KEEP")
    assert status(con) == "KEPT" and hdb.confirmed_conditions(con, 1) is None
    raises(hdb.add_reply, con, 1, 3, "다시", has="KEPT")


def test_confirm_without_conditions_is_none():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안 좋아요")
    hdb.save_interpretation(con, m, "ACCEPT", {"picks": ["A"]}, chosen_option_id=1)
    hdb.decide_reply(con, m, 1, "CONFIRM", proposal_action="move")
    assert hdb.confirmed_conditions(con, 1) is None and status(con) == "RESOLVED"


def proposed(con, body="화 오전이나 목요일, 수요일은 17시 전"):
    """안건 1에 답장·해석까지 넣는다 (조교 확인 대기). -> 답장 id"""
    m = hdb.add_reply(con, 1, 3, body)
    hdb.save_interpretation(con, m, "CONDITIONAL", {"conditions": COND})
    return m


def add_rounds(con):
    """같은 학기 2·3·4차(4차는 거부 확인용), 다른 학기 1차, 다른 학기 시간표."""
    q = con.execute
    q("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (2,1,2,'2026-12-08'),(3,1,3,'2026-12-15'),(4,1,4,'2026-12-22')")
    q("INSERT INTO term(id,year,semester,grid_id) VALUES (2,2027,'2',1)")
    q("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (9,2,2,'2027-06-01')")
    q("INSERT INTO timetable(id,term_id,round_id,kind) VALUES (2,1,2,'TA_EDIT'),(9,2,9,'DRAFT')")
    con.commit()


def next_round(con, pid, round_id, cond):
    """안건 pid 를 SENT 로 보내고 답장·해석·[확인](next)까지. 차수 round_id 의 새 안건을 연다. -> 새 안건 id"""
    con.execute("UPDATE proposal SET status='SENT' WHERE id=?", (pid,))
    con.execute("""INSERT INTO message(round_id,proposal_id,sender_id,receiver_id,kind,channel,body,sent_at)
                   SELECT round_id, id, 1, 3, 'ALTERNATIVE', 'APP', '조율 안내', datetime('now') FROM proposal WHERE id=?""", (pid,))
    con.commit()
    m = hdb.add_reply(con, pid, 3, "다음 차수 조건 (가상)")
    hdb.save_interpretation(con, m, "CONDITIONAL", {"conditions": cond})
    hdb.decide_reply(con, m, 1, "CONFIRM", conditions=cond, proposal_action="next")
    return hdb.open_next_proposal(con, pid, round_id)


def test_confirm_requires_proposal_action():
    con = make(); m = proposed(con)
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", conditions=COND, has="처리안")
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", conditions=COND, proposal_action="later", has="move")
    assert status(con) == "PROPOSED"
    assert con.execute("SELECT ta_action FROM reply_interpretation WHERE message_id=?", (m,)).fetchone()[0] is None


def test_confirm_next_requires_conditions():
    con = make(); m = proposed(con)
    for empty in (None, {}, {"day_slots": {}, "end_before": []}, "{}"):
        raises(hdb.decide_reply, con, m, 1, "CONFIRM", conditions=empty, proposal_action="next", has="조건")
    assert status(con) == "PROPOSED"
    hdb.decide_reply(con, m, 1, "CONFIRM", conditions=COND, proposal_action="next")
    assert status(con) == "NEXT" and hdb.confirmed_conditions(con, 1) == COND
    raises(hdb.add_reply, con, 1, 3, "다시", has="NEXT")                              # NEXT 뒤 같은 안건에 재제출 거부


def test_edit_keep_ignore_proposal_action():
    con = make(); m = proposed(con)
    hdb.decide_reply(con, m, 1, "EDIT", reason="통화로 확인", conditions=COND, proposal_action="next")
    assert status(con) == "RESOLVED"
    con = make(); m = proposed(con)
    hdb.decide_reply(con, m, 1, "KEEP", proposal_action="move")
    assert status(con) == "KEPT"


def test_open_next_proposal():
    con = make(); add_rounds(con)
    raises(hdb.open_next_proposal, con, 1, 2, has="다음 차수로 넘긴 안건이 아닙니다")     # SENT
    m = proposed(con)
    hdb.decide_reply(con, m, 1, "CONFIRM", conditions=COND, proposal_action="next")
    raises(hdb.open_next_proposal, con, 99, 2, has="없는 조율 안건")
    raises(hdb.open_next_proposal, con, 1, 3, has="바로 다음 차수가 아닙니다")           # 1차 → 3차
    raises(hdb.open_next_proposal, con, 1, 1, has="바로 다음 차수가 아닙니다")           # 같은 차수
    raises(hdb.open_next_proposal, con, 1, 9, has="다른 학기")
    raises(hdb.open_next_proposal, con, 1, 2, timetable_id=9, has="다른 학기의 시간표")
    raises(hdb.open_next_proposal, con, 1, 77, has="없는 차수")
    assert hdb.carried_conditions(con, 1) is None                                    # 1차 안건은 이어받은 조건 없음
    new = hdb.open_next_proposal(con, 1, 2)
    row = con.execute("SELECT round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id FROM proposal WHERE id=?",
                      (new,)).fetchone()
    assert row == (2, 1, 10, 2, "희망 시간 겹침", "OPEN", 1), row                      # 시간표는 이전 안건 것
    assert status(con, 1) == "NEXT"                                                  # 이전 안건은 그대로 (되돌리지 않음)
    assert hdb.carried_conditions(con, new) == COND and hdb.confirmed_conditions(con, new) is None
    raises(hdb.open_next_proposal, con, 1, 2, has="이미 다음 차수 안건")                  # 중복 생성
    raises(hdb.carried_conditions, con, 99, has="없는 조율 안건")
    assert not con.in_transaction


def test_open_next_with_timetable_and_one_step_only():
    con = make(); add_rounds(con)
    m = proposed(con)
    hdb.decide_reply(con, m, 1, "CONFIRM", conditions=COND, proposal_action="next")
    p2 = hdb.open_next_proposal(con, 1, 2, timetable_id=2)
    assert con.execute("SELECT timetable_id FROM proposal WHERE id=?", (p2,)).fetchone()[0] == 2
    cond2 = {"day_slots": {"4": ["13:30"]}, "end_before": []}
    p3 = next_round(con, p2, 3, cond2)                                               # 2차에서도 next → 3차
    assert hdb.carried_conditions(con, p3) == cond2                                  # 한 단계만: 2차에서 확인한 조건
    assert hdb.carried_conditions(con, p2) == COND
    p3b = con.execute("SELECT id FROM proposal WHERE round_id=3").fetchone()[0]
    assert p3b == p3
    raises(next_round, con, p3, 4, cond2, has="3차 다음 차수는 없습니다")               # 3차 다음
    assert status(con, p3) == "NEXT"                                                 # [확인]은 남고, 새 안건만 안 열림
    assert con.execute("SELECT count(*) FROM proposal WHERE round_id=4").fetchone()[0] == 0


def test_prev_unique_and_section_status():
    con = make()
    q = con.execute
    q("INSERT INTO timetable_section(timetable_id,course_id,section_no) VALUES (1,10,1)")
    assert q("SELECT status FROM timetable_section WHERE course_id=10 AND section_no=1").fetchone()[0] == "DONE"   # 기본값
    try:
        q("INSERT INTO timetable_section(timetable_id,course_id,section_no,status) VALUES (1,10,2,'WAIT')")
        raise AssertionError("status CHECK 가 막아야 함")
    except sqlite3.IntegrityError:
        pass
    q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,status,prev_proposal_id) VALUES (5,1,1,10,2,'OPEN',1)")
    try:
        q("INSERT INTO proposal(id,round_id,timetable_id,course_id,section_no,status,prev_proposal_id) VALUES (6,1,1,10,2,'OPEN',1)")
        raise AssertionError("한 안건에서 다음 차수 안건은 하나만 (UNIQUE)")
    except sqlite3.IntegrityError:
        pass


# README "어긋남 점검" 쿼리와 같은 글. 고치면 README 도 고친다.
MISMATCH_SQL = """
SELECT p.id, p.course_id, p.section_no, ts.status
FROM proposal p
JOIN timetable t   ON t.id = p.timetable_id
JOIN timetable_section ts
     ON ts.timetable_id = (SELECT MAX(id) FROM timetable WHERE term_id = t.term_id)   -- 그 학기 최신 시간표
    AND ts.course_id = p.course_id
    AND (p.section_no IS NULL OR ts.section_no = p.section_no)
WHERE p.status = 'NEXT' AND ts.status = 'DONE'
  AND NOT EXISTS (SELECT 1 FROM proposal n WHERE n.prev_proposal_id = p.id);
"""


def test_mismatch_query():
    con = make()
    q = con.execute
    q("INSERT INTO timetable_section(timetable_id,course_id,section_no,status) VALUES (1,10,2,'COORD'),(1,11,1,'COORD')")
    q("UPDATE proposal SET status='NEXT'"); con.commit()
    assert q(MISMATCH_SQL).fetchall() == []                                           # 아직 조율 중: 정상
    q("UPDATE timetable_section SET status='DONE' WHERE course_id=10"); con.commit()
    assert q(MISMATCH_SQL).fetchall() == [(1, 10, 2, "DONE")]                          # NEXT 인데 이미 DONE
    q("INSERT INTO round(id,term_id,round_no,deadline_at) VALUES (2,1,2,'2026-12-08')"); con.commit()
    hdb.open_next_proposal(con, 1, 2)
    assert q(MISMATCH_SQL).fetchall() == []                                           # 다음 차수 안건이 열렸으면 제외


def test_rollback_on_failure():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안")
    raises(hdb.save_interpretation, con, m, "ACCEPT", {}, chosen_option_id=3)
    assert not con.in_transaction
    assert con.execute("SELECT count(*) FROM reply_interpretation").fetchone()[0] == 0


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for n, f in tests:
        try:
            f(); print("  OK  ", n)
        except AssertionError as e:
            failed += 1; print("  실패", n, e)
    print(f"\n결과: {len(tests) - failed}/{len(tests)} 통과" + ("" if not failed else " — 실패 있음"))
    sys.exit(1 if failed else 0)
