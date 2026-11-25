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
    q("""INSERT INTO course(id,term_id,department_id,name,professor_id,session_count,slots_per_session)
         VALUES (10,1,1,'자료구조',2,2,1),(11,1,1,'알고리즘',4,2,1)""")
    q("INSERT INTO course_section VALUES (10,2,3,40)")
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
    raises(hdb.add_reply, con, 1, 2, "A안 좋아요", choices=["A"], has="담당 교수가 아닙니다")
    raises(hdb.add_reply, con, 99, 3, "A안", choices=["A"], has="없는 조율 안건")
    assert con.execute("SELECT count(*) FROM message WHERE kind='REPLY'").fetchone()[0] == 0


def test_reject_by_status():
    for st in ("OPEN", "RESOLVED", "KEPT", "NEXT"):
        con = make(); con.execute("UPDATE proposal SET status=? WHERE id=1", (st,)); con.commit()
        raises(hdb.add_reply, con, 1, 3, "A안 좋아요", choices=["A"], has=st)
        assert con.execute("SELECT count(*) FROM message WHERE kind='REPLY'").fetchone()[0] == 0


def test_add_reply_fills_fields():
    con = make()
    mid = hdb.add_reply(con, 1, 3, "A안 좋아요", choices=["A"])
    row = con.execute("""SELECT round_id, proposal_id, sender_id, receiver_id, kind, channel, body, sent_at IS NOT NULL,
                         delivery_status, reply_to_id FROM message WHERE id=?""", (mid,)).fetchone()
    assert row == (1, 1, 3, 1, "REPLY", "APP", "A안 좋아요", 1, "RECEIVED", 1), row
    inv = con.execute("SELECT status, responded_at IS NOT NULL FROM round_invite WHERE round_id=1 AND professor_id=3").fetchone()
    assert inv == ("RESPONDED", 1), inv
    assert status(con) == "SENT"


def test_reply_to_checks():
    con = make()
    raises(hdb.add_reply, con, 1, 3, "답", choices=["ETC"], reply_to_id=2, has="다른 안건")
    raises(hdb.add_reply, con, 1, 3, "답", choices=["ETC"], reply_to_id=99, has="없는 메시지")
    mid = hdb.add_reply(con, 1, 3, "답", choices=["ETC"], reply_to_id=1, channel="EMAIL")
    raises(hdb.add_reply, con, 1, 3, "답", choices=["ETC"], reply_to_id=mid, has="교수 답장에는")


def test_receiver_falls_back_to_ta():
    con = make()
    con.execute("UPDATE message SET sender_id=NULL WHERE id=1"); con.commit()
    mid = hdb.add_reply(con, 1, 3, "B안", choices=["B"])
    assert con.execute("SELECT receiver_id FROM message WHERE id=?", (mid,)).fetchone()[0] == 1
    con.execute("UPDATE user SET role='PROF' WHERE id=1"); con.commit()
    raises(hdb.add_reply, con, 1, 3, "B안", choices=["B"], has="조교가 없습니다")


def test_resubmit_keeps_history_latest_is_target():
    con = make()
    m1 = hdb.add_reply(con, 1, 3, "A안 좋아요", choices=["A"])
    hdb.save_interpretation(con, m1, "ACCEPT", {"picks": ["A"]}, model_name="keyword", chosen_option_id=1)
    assert status(con) == "PROPOSED"
    m2 = hdb.add_reply(con, 1, 3, "다시 생각해 보니 화요일 오전만 됩니다", choices=["ETC"])   # 조교 결정 전 재제출
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
    m = hdb.add_reply(con, 1, 3, "A안", choices=["A"])
    raises(hdb.save_interpretation, con, m, "수용", {}, has="ACCEPT")
    raises(hdb.save_interpretation, con, m, "ACCEPT", {}, chosen_option_id=3, has="이 안건의 대안이 아닙니다")
    raises(hdb.save_interpretation, con, m, "ACCEPT", "[1,2]", has="객체")
    assert status(con) == "SENT"


def test_decide_confirm_and_conditions():
    con = make()
    assert hdb.confirmed_conditions(con, 1) is None
    m = hdb.add_reply(con, 1, 3, "화 오전이나 목요일, 수요일은 17시 전", choices=["ETC"])
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
    raises(hdb.add_reply, con, 1, 3, "그래도 바꾸고 싶어요", choices=["ETC"], has="RESOLVED")       # 결정 뒤 재제출 거부
    raises(hdb.save_interpretation, con, m, "REJECT", {}, has="이미 결정")


def test_decide_edit_requires_reason():
    con = make()
    m = hdb.add_reply(con, 1, 3, "B안이요", choices=["B"])
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
    m = hdb.add_reply(con, 1, 3, "셋 다 어렵습니다", choices=["ETC"])
    hdb.save_interpretation(con, m, "REJECT", {})
    raises(hdb.decide_reply, con, m, 1, "KEEP", conditions=COND, has="조건을 넣지")
    hdb.decide_reply(con, m, 1, "KEEP")
    assert status(con) == "KEPT" and hdb.confirmed_conditions(con, 1) is None
    raises(hdb.add_reply, con, 1, 3, "다시", choices=["ETC"], has="KEPT")


def test_confirm_without_conditions_is_none():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안 좋아요", choices=["A"])
    hdb.save_interpretation(con, m, "ACCEPT", {"picks": ["A"]}, chosen_option_id=1)
    hdb.decide_reply(con, m, 1, "CONFIRM", proposal_action="move")
    assert hdb.confirmed_conditions(con, 1) is None and status(con) == "RESOLVED"


def proposed(con, body="화 오전이나 목요일, 수요일은 17시 전"):
    """안건 1에 답장·해석까지 넣는다 (조교 확인 대기). -> 답장 id"""
    m = hdb.add_reply(con, 1, 3, body, choices=["ETC"])
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
    m = hdb.add_reply(con, pid, 3, "다음 차수 조건 (가상)", choices=["ETC"])
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
    raises(hdb.add_reply, con, 1, 3, "다시", choices=["ETC"], has="NEXT")                              # NEXT 뒤 같은 안건에 재제출 거부


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


def test_choices_required():
    con = make()
    raises(hdb.add_reply, con, 1, 3, "셋 다 어렵습니다", has="하나 이상")                  # 아무것도 안 고름
    raises(hdb.add_reply, con, 1, 3, "셋 다 어렵습니다", choices=[], has="하나 이상")
    raises(hdb.add_reply, con, 1, 3, "x", choices=["D"], has="고를 수 있는 값")
    raises(hdb.add_reply, con, 1, 3, "  ", choices=["ETC"], has="기타 내용")
    raises(hdb.add_reply, con, 1, 3, "", choices=["C"], has="C안이 없습니다")            # 안건 1의 대안은 1·2번만
    assert con.execute("SELECT count(*) FROM message WHERE kind='REPLY'").fetchone()[0] == 0
    m = hdb.add_reply(con, 1, 3, "B도 괜찮고 목요일 오후면 더 좋아요", choices=["ETC", "B", "A", "B"])   # 중복 가능, 같은 값은 하나로
    assert hdb.reply_choices(con, m) == [dict(choice="A", option_id=1), dict(choice="B", option_id=2), dict(choice="ETC", option_id=None)]
    m2 = hdb.add_reply(con, 1, 3, "", choices=["A"])                                       # A·B·C 만 고르면 글은 없어도 됨
    assert hdb.reply_choices(con, m2) == [dict(choice="A", option_id=1)]


def test_reject_without_condition_goes_offline():
    """버그 재현: '셋 다 어렵습니다'(조건 없음)를 다음 차수로 [확인]하면 저장 오류 → 이제 [따로 연락]으로 처리."""
    con = make()
    m = hdb.add_reply(con, 1, 3, "위의 대안에선 어렵습니다", choices=["ETC"])
    hdb.save_interpretation(con, m, "REJECT", {})
    e = raises(hdb.decide_reply, con, m, 1, "CONFIRM", proposal_action="next", has="조건")
    assert "OFFLINE" in e                                                                  # 오류 문구가 [따로 연락]을 알려 줌
    raises(hdb.decide_reply, con, m, 1, "OFFLINE", conditions=COND, has="조건을 넣지")
    raises(hdb.decide_reply, con, m, 1, "OFFLINE", option_id=1, has="대안을 넣지")
    hdb.decide_reply(con, m, 1, "OFFLINE", reason="교수님께 전화로 따로 조율")
    assert status(con) == "OFFLINE"
    raises(hdb.add_reply, con, 1, 3, "다시", choices=["A"], has="OFFLINE")                 # 따로 연락 중에는 답장을 받지 않음


def test_offline_needs_interpretation():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안", choices=["A"])
    raises(hdb.decide_reply, con, m, 1, "OFFLINE", has="해석이 아직 없습니다")


def test_confirm_records_option():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A나 B 다 괜찮아요", choices=["A", "B"])
    hdb.save_interpretation(con, m, "ACCEPT", {"picks": ["A", "B"]})
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", proposal_action="move", option_id=3, has="이 안건의 대안이 아닙니다")
    hdb.decide_reply(con, m, 1, "CONFIRM", proposal_action="move", option_id=2)         # 엔진 pick_best 가 고른 B
    assert con.execute("SELECT chosen_option_id FROM reply_interpretation WHERE message_id=?", (m,)).fetchone()[0] == 2
    assert status(con) == "RESOLVED"


def test_confirm_pair_updates_response():
    con = make()
    con.execute("INSERT INTO course_response(id,round_id,course_id,professor_id,lab_requirement,single_day_pref) VALUES (50,1,10,3,0,'NONE')")
    con.commit()
    m = hdb.add_reply(con, 1, 3, "두 분반을 이어서 해 주세요", choices=["ETC"])
    hdb.save_interpretation(con, m, "CONDITIONAL", {"section_pair": "BACK_TO_BACK"})
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", proposal_action="pair", has="pair_mode")
    raises(hdb.decide_reply, con, m, 1, "CONFIRM", proposal_action="pair", pair_mode="BOTH", has="pair_mode")
    hdb.decide_reply(con, m, 1, "CONFIRM", proposal_action="pair", pair_mode="BACK_TO_BACK")
    assert con.execute("SELECT section_pair FROM course_response WHERE id=50").fetchone()[0] == "BACK_TO_BACK"
    assert status(con) == "RESOLVED"
    con2 = make()                                                                          # 응답이 없으면 반영할 곳이 없음
    m = hdb.add_reply(con2, 1, 3, "두 분반 교차로", choices=["ETC"])
    hdb.save_interpretation(con2, m, "CONDITIONAL", {})
    raises(hdb.decide_reply, con2, m, 1, "CONFIRM", proposal_action="pair", pair_mode="CROSS", has="교수 응답이 없습니다")
    assert status(con2) == "PROPOSED"


def test_reply_other_request():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안 좋고, 실습 조교 한 명 배치 부탁드립니다", choices=["A", "ETC"])
    oid = hdb.add_reply_request(con, m, "실습 조교 한 명 배치")
    assert hdb.pending_other_requests(con, 1) == [(oid, 10, 3, "실습 조교 한 명 배치")]
    raises(hdb.add_reply_request, con, m, "또", has="이미 있습니다")
    m2 = hdb.add_reply(con, 1, 3, "", choices=["B"])
    raises(hdb.add_reply_request, con, m2, "x", has="기타를 고르지 않은")
    raises(hdb.add_reply_request, con, 1, "x", has="교수 답장이 아닙니다")
    hdb.confirm_other_request(con, oid, 1, memo="실습 조교 배정함")
    assert hdb.pending_other_requests(con, 1) == []


def with_timetable(con):
    """시간표 1에 과목 10의 1·2분반, 과목 11 1분반을 놓는다 (월 09:00·수 09:00 등, 강의실 1)."""
    S = {(d, t): i for i, d, t in con.execute("SELECT id, day, start_time FROM time_slot")}
    q = con.execute
    q("INSERT INTO timetable_section(timetable_id,course_id,section_no,planned_enrollment,status) VALUES (1,10,1,40,'DONE'),(1,10,2,40,'COORD'),(1,11,1,40,'DONE')")
    q("INSERT INTO assignment VALUES (1,10,1,1,?,1),(1,10,1,2,?,1)", (S[("월", "09:00")], S[("수", "09:00")]))
    q("INSERT INTO assignment VALUES (1,10,2,1,?,1),(1,10,2,2,?,1)", (S[("화", "09:00")], S[("목", "09:00")]))
    q("INSERT INTO assignment VALUES (1,11,1,1,?,1),(1,11,1,2,?,1)", (S[("월", "10:30")], S[("수", "10:30")]))
    con.commit()
    return S


def test_manual_place_and_lock():
    con = make(); S = with_timetable(con)
    m = hdb.add_reply(con, 1, 3, "위의 대안에선 어렵습니다", choices=["ETC"])
    hdb.save_interpretation(con, m, "REJECT", {})
    rows = [(2, 1, S[("화", "15:00")], 1), (2, 2, S[("목", "15:00")], 1)]
    raises(hdb.manual_place, con, 1, 1, rows, has="따로 연락")                               # 아직 OFFLINE 아님
    hdb.decide_reply(con, m, 1, "OFFLINE")
    raises(hdb.manual_place, con, 1, 3, rows, has="조교만")
    raises(hdb.manual_place, con, 1, 1, [(1, 1, S[("화", "15:00")], 1)], has="이 안건의 분반이 아닙니다")
    raises(hdb.manual_place, con, 1, 1, [], has="놓을 칸이 없습니다")
    raises(hdb.manual_place, con, 1, 1, [(2, 1, 9999, 1)], has="없는 칸")
    n_tt = con.execute("SELECT count(*) FROM timetable").fetchone()[0]
    raises(hdb.manual_place, con, 1, 1, [(2, 1, S[("월", "10:30")], 1)], has="이미 쓰는 강의실")   # 과목 11과 같은 칸·같은 방
    assert con.execute("SELECT count(*) FROM timetable").fetchone()[0] == n_tt and status(con) == "OFFLINE"   # 되돌려짐
    tt = hdb.manual_place(con, 1, 1, rows)
    assert con.execute("SELECT kind, parent_id, created_by FROM timetable WHERE id=?", (tt,)).fetchone() == ("TA_EDIT", 1, 1)
    secs = con.execute("SELECT course_id, section_no, status, locked FROM timetable_section WHERE timetable_id=? ORDER BY 1,2", (tt,)).fetchall()
    assert secs == [(10, 1, "DONE", 0), (10, 2, "MANUAL", 1), (11, 1, "DONE", 0)], secs
    got = con.execute("SELECT section_no, session_no, slot_id FROM assignment WHERE timetable_id=? AND course_id=10 ORDER BY 1,2", (tt,)).fetchall()
    assert got == [(1, 1, S[("월", "09:00")]), (1, 2, S[("수", "09:00")]), (2, 1, S[("화", "15:00")]), (2, 2, S[("목", "15:00")])], got
    assert con.execute("SELECT count(*) FROM assignment WHERE timetable_id=? AND course_id=11", (tt,)).fetchone()[0] == 2
    assert status(con) == "RESOLVED"
    hdb.set_lock(con, tt, 10, 2, False)                                                    # 조교가 고정을 풂
    assert con.execute("SELECT locked FROM timetable_section WHERE timetable_id=? AND course_id=10 AND section_no=2", (tt,)).fetchone()[0] == 0
    raises(hdb.set_lock, con, tt, 10, 9, True, has="없는 분반 배정")


def test_rollback_on_failure():
    con = make()
    m = hdb.add_reply(con, 1, 3, "A안", choices=["A"])
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
