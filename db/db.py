"""DB 연결 함수. 서버·솔버·테스트는 sqlite3.connect를 직접 쓰지 말고 이것으로 연결한다.
SQLite는 외래키 검사가 연결마다 꺼진 채로 시작하므로 연결할 때마다 켠다."""
import json
import sqlite3


def connect(path="ssuroom.db"):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


# ---------------------------------------------------------------- 서버 단계
PHASES = ["COLLECTING", "ROUND1", "ROUND2", "ROUND3", "FINAL"]
PHASE_LABELS = {"COLLECTING": "희망 수집", "ROUND1": "1차 조율", "ROUND2": "2차 조율", "ROUND3": "3차 조율", "FINAL": "확정"}


def get_phase(con, term_id):
    """지금 단계. -> dict(phase='ROUND1', label='1차 조율', changed_at=...)"""
    row = con.execute("SELECT phase, phase_changed_at FROM term WHERE id=?", (term_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 학기: {term_id}")
    return dict(phase=row[0], label=PHASE_LABELS[row[0]], changed_at=row[1])


def set_phase(con, term_id, to_phase, user_id=None, force=False):
    """단계를 바꾸고 기록을 남긴다. 기본은 다음 단계로 한 칸씩만(희망 수집 → 1차 조율 → 2차 조율 → 3차 조율 → 확정).
    시연 중 처음으로 되돌리거나 건너뛰려면 force=True."""
    if to_phase not in PHASES:
        raise ValueError(f"단계는 {PHASES} 중 하나여야 합니다: {to_phase}")
    cur = get_phase(con, term_id)["phase"]
    if not force and PHASES.index(to_phase) != PHASES.index(cur) + 1:
        nxt = PHASES[min(PHASES.index(cur) + 1, len(PHASES) - 1)]
        raise ValueError(f"단계는 한 칸씩만 바꿀 수 있습니다: '{PHASE_LABELS[cur]}' → '{PHASE_LABELS[to_phase]}' 불가 "
                         f"(다음 단계는 '{PHASE_LABELS[nxt]}'). 되돌리거나 건너뛰려면 force=True")
    con.execute("UPDATE term SET phase=?, phase_changed_at=datetime('now') WHERE id=?", (to_phase, term_id))
    con.execute("INSERT INTO phase_log(term_id, from_phase, to_phase, changed_by) VALUES (?,?,?,?)",
                (term_id, cur, to_phase, user_id))
    con.commit()
    return get_phase(con, term_id)


# ---------------------------------------------------------------- 기타 요청 (조교 확인)
def pending_other_requests(con, round_id):
    """조교가 아직 확인하지 않은 기타 요청 (희망 입력의 기타 + 조율 답장 기타의 시간표 밖 요청).
    -> [(other_request_id, 과목 id, 교수 id, 본문)]"""
    return con.execute("""SELECT o.id, COALESCE(r.course_id, p.course_id), COALESCE(r.professor_id, m.sender_id), o.body
                          FROM other_request o
                          LEFT JOIN course_response r ON r.id = o.response_id
                          LEFT JOIN message m ON m.id = o.message_id
                          LEFT JOIN proposal p ON p.id = m.proposal_id
                          WHERE COALESCE(r.round_id, m.round_id)=? AND o.status='PENDING' ORDER BY o.id""",
                       (round_id,)).fetchall()


def confirm_other_request(con, other_request_id, user_id, memo=None):
    """조교가 '확인함'을 누른다."""
    n = con.execute("""UPDATE other_request SET status='CONFIRMED', confirmed_by=?, confirmed_at=datetime('now'),
                       ta_memo=COALESCE(?, ta_memo) WHERE id=?""", (user_id, memo, other_request_id)).rowcount
    if n == 0:
        raise ValueError(f"없는 기타 요청: {other_request_id}")
    con.commit()


# ---------------------------------------------------------------- 조율 회신 (교수가 자기 화면에서 직접 답장)
# 안건(proposal) 상태: 보내기 전 → 답 기다림 → 조교 확인 대기 → 반영됨 / 현재대로 유지 / 다음 차수로. 서버 조율 상태와 같은 이름.
# 다음 차수에는 같은 안건을 되돌리지 않고 새 안건을 연다 (open_next_proposal, prev_proposal_id 로 이어짐).
PROPOSAL_STATUSES = ["OPEN", "SENT", "PROPOSED", "RESOLVED", "KEPT", "NEXT", "OFFLINE"]
PROPOSAL_LABELS = {"OPEN": "보내기 전", "SENT": "답 기다림", "PROPOSED": "조교 확인 대기",
                   "RESOLVED": "반영됨", "KEPT": "현재대로 유지", "NEXT": "다음 차수로", "OFFLINE": "따로 연락 중"}
REPLY_LABELS = ["ACCEPT", "CONDITIONAL", "REJECT", "UNCLEAR"]          # 수용 / 조건부 / 거절 / 확인 필요
TA_ACTIONS = ["CONFIRM", "EDIT", "KEEP", "OFFLINE"]                    # [확인] / [수정] / [현재대로 유지] / [따로 연락]
PROPOSAL_ACTIONS = {"move": "RESOLVED", "next": "NEXT", "pair": "RESOLVED"}   # [확인]한 처리안: 옮김 / 다음 차수 / 분반 연강·교차 반영
REPLY_CHOICES = ["A", "B", "C", "ETC"]                                 # 답장에서 고르는 값: 대안 A·B·C / 기타(본문)
PAIR_MODES = ["NONE", "BACK_TO_BACK", "CROSS"]                         # course_response.section_pair
MAX_ROUND = 3                                                          # 조율은 3차까지


def professor_owns(con, professor_id, course_id, section_no=None):
    """이 교수가 그 과목(분반)의 담당인지. 분반 담당 규칙: course_section 에 행이 있으면 그 교수, 없으면 course.professor_id.
    section_no=None 이면 그 과목의 어느 분반이든 담당이면 True.
    (분반 수는 풀이 결과에서 생기므로, course.professor_id 가 이 교수면 course_section 이 모든 분반을 다른 교수로 지정했어도 True)"""
    row = con.execute("SELECT professor_id FROM course WHERE id=?", (course_id,)).fetchone()
    if row is None:
        return False
    if section_no is None:
        if row[0] == professor_id:
            return True
        return con.execute("SELECT 1 FROM course_section WHERE course_id=? AND professor_id=?",
                           (course_id, professor_id)).fetchone() is not None
    cs = con.execute("SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?",
                     (course_id, section_no)).fetchone()
    return (cs[0] if cs else row[0]) == professor_id


def _proposal(con, proposal_id):
    row = con.execute("SELECT round_id, course_id, section_no, status FROM proposal WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 조율 안건: {proposal_id}")
    return dict(round_id=row[0], course_id=row[1], section_no=row[2], status=row[3])


def _latest_reply_id(con, proposal_id):
    return con.execute("SELECT MAX(id) FROM message WHERE proposal_id=? AND kind='REPLY'", (proposal_id,)).fetchone()[0]


def _reply(con, message_id):
    """답장 메시지의 안건 id와 안건. 답장(REPLY)이 아니거나, 안건이 없거나, 가장 최근 답장이 아니면 ValueError."""
    row = con.execute("SELECT proposal_id, kind FROM message WHERE id=?", (message_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 메시지: {message_id}")
    if row[1] != "REPLY":
        raise ValueError(f"교수 답장(REPLY)이 아닙니다: 메시지 {message_id}는 {row[1]}")
    if row[0] is None:
        raise ValueError(f"조율 안건과 연결되지 않은 답장입니다: 메시지 {message_id}")
    if _latest_reply_id(con, row[0]) != message_id:
        raise ValueError(f"이 안건의 가장 최근 답장이 아닙니다: 메시지 {message_id}. 교수가 마지막으로 쓴 답장만 해석·결정합니다")
    return row[0], _proposal(con, row[0])


def _json_object(value, what):
    """dict 또는 JSON 글 → dict. 모양을 바꾸지 않고 JSON 으로 그대로 저장할 수 있는지 확인한다."""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"{what}이(가) JSON 이 아닙니다: {e}") from None
    if not isinstance(value, dict):
        raise ValueError(f"{what}은(는) JSON 객체(dict)여야 합니다: {type(value).__name__}")
    if json.loads(json.dumps(value, ensure_ascii=False)) != value:
        raise ValueError(f"{what}을(를) 모양 그대로 JSON 으로 저장할 수 없습니다 (요일 키는 \"1\"처럼 문자열로)")
    return value


def add_reply(con, proposal_id, professor_id, body, choices=None, reply_to_id=None, channel="APP"):
    """교수가 자기 화면에서 쓴 답장을 기록한다. -> 새 message id
    - choices: 고른 값 'A'·'B'·'C'·'ETC'(기타) 중 하나 이상 (여러 개 가능, 중복은 하나로). 하나도 없으면 ValueError.
      A·B·C 는 이 안건의 대안 1·2·3번(proposal_option)이 있어야 한다. 'ETC' 를 고르면 body(기타 글)가 비어 있으면 안 된다.
      고른 값은 reply_choice 에 남는다.
    - 안건이 없거나, 담당 교수가 아니거나, 안건 상태가 SENT(답 기다림)·PROPOSED(조교 확인 대기)가 아니면 ValueError.
    - reply_to_id 가 없으면 이 안건의 가장 최근 조율 메시지(REPLY 가 아닌 것)로 채운다. 주면 같은 안건의 조율 메시지인지 검사.
    - 받는 사람: 그 조율 메시지를 보낸 사람. 없으면 첫 조교(role='TA'). 조교도 없으면 ValueError.
    - round_invite(회차, 교수) 행이 있으면 status='RESPONDED', responded_at 을 채운다.
    - 조교 결정 전에 다시 쓰면 새 행이 생기고 이전 답장은 이력으로 남는다. 해석·결정 대상은 마지막 답장이다.
      (안건 상태는 그대로 둔다. 새 답장을 해석해 save_interpretation 을 부르면 PROPOSED)"""
    try:
        picked = list(dict.fromkeys(choices or []))
        if not picked:
            raise ValueError("대안 A·B·C 와 기타 중 하나 이상을 골라야 답장을 낼 수 있습니다")
        bad = [x for x in picked if x not in REPLY_CHOICES]
        if bad:
            raise ValueError(f"고를 수 있는 값은 {REPLY_CHOICES} 입니다: {bad}")
        if "ETC" in picked and not (body and body.strip()):
            raise ValueError("기타를 골랐으면 기타 내용을 적어야 합니다")
        p = _proposal(con, proposal_id)
        if not professor_owns(con, professor_id, p["course_id"], p["section_no"]):
            where = f"{p['section_no']}분반" if p["section_no"] is not None else "과목"
            raise ValueError(f"담당 교수가 아닙니다: 교수 {professor_id}는 과목 {p['course_id']} {where}의 담당이 아닙니다")
        if p["status"] not in ("SENT", "PROPOSED"):
            raise ValueError(f"지금은 답장을 받을 수 없습니다: 안건 {proposal_id} 상태가 "
                             f"'{PROPOSAL_LABELS.get(p['status'], p['status'])}'({p['status']}). "
                             f"조율 메시지를 보낸 뒤부터 조교가 결정하기 전까지만 받습니다")
        if reply_to_id is None:
            to = con.execute("""SELECT id, sender_id FROM message WHERE proposal_id=? AND kind<>'REPLY'
                                ORDER BY id DESC LIMIT 1""", (proposal_id,)).fetchone()
        else:
            to = con.execute("SELECT id, sender_id, proposal_id, kind FROM message WHERE id=?", (reply_to_id,)).fetchone()
            if to is None:
                raise ValueError(f"없는 메시지에 답할 수 없습니다: {reply_to_id}")
            if to[2] != proposal_id:
                raise ValueError(f"다른 안건의 메시지입니다: 메시지 {reply_to_id}는 안건 {to[2]}, 답장은 안건 {proposal_id}")
            if to[3] == "REPLY":
                raise ValueError(f"교수 답장에는 답할 수 없습니다: 메시지 {reply_to_id}는 REPLY. 조율 메시지를 가리켜야 합니다")
        receiver = to[1] if to is not None and to[1] is not None else None
        if receiver is None:
            ta = con.execute("SELECT id FROM user WHERE role='TA' ORDER BY id LIMIT 1").fetchone()
            if ta is None:
                raise ValueError("답장을 받을 조교가 없습니다: user 에 role='TA' 인 사용자를 먼저 넣으세요")
            receiver = ta[0]
        opt_of = {}
        for x in picked:
            if x == "ETC":
                continue
            row = con.execute("SELECT id FROM proposal_option WHERE proposal_id=? AND option_no=?",
                              (proposal_id, "ABC".index(x) + 1)).fetchone()
            if row is None:
                raise ValueError(f"이 안건에 {x}안이 없습니다: 안건 {proposal_id}")
            opt_of[x] = row[0]
        cur = con.execute("""INSERT INTO message(round_id, proposal_id, sender_id, receiver_id, kind, channel, body,
                                                 sent_at, delivery_status, reply_to_id)
                             VALUES (?,?,?,?,'REPLY',?,?,datetime('now'),'RECEIVED',?)""",
                          (p["round_id"], proposal_id, professor_id, receiver, channel, body,
                           to[0] if to is not None else None))
        for x in picked:
            con.execute("INSERT INTO reply_choice(message_id, choice, option_id) VALUES (?,?,?)",
                        (cur.lastrowid, x, opt_of.get(x)))
        con.execute("""UPDATE round_invite SET status='RESPONDED', responded_at=datetime('now')
                       WHERE round_id=? AND professor_id=?""", (p["round_id"], professor_id))
        con.commit()
        return cur.lastrowid
    except Exception:
        con.rollback()
        raise


def save_interpretation(con, message_id, label, extracted_json, model_name=None, chosen_option_id=None):
    """답장 해석(언어 모델 또는 키워드)을 저장하고 안건을 PROPOSED(조교 확인 대기)로 바꾼다. 이미 있으면 갱신.
    label: ACCEPT / CONDITIONAL / REJECT / UNCLEAR. extracted_json: dict 또는 JSON 글(객체).
    그 안건의 가장 최근 답장만 받는다. 조교가 이미 결정한 답장·안건이면 ValueError."""
    try:
        if label not in REPLY_LABELS:
            raise ValueError(f"해석 결과는 {REPLY_LABELS} 중 하나여야 합니다: {label}")
        proposal_id, p = _reply(con, message_id)
        if p["status"] not in ("SENT", "PROPOSED"):
            raise ValueError(f"이미 결정된 안건입니다: 안건 {proposal_id} 상태 {p['status']}")
        done = con.execute("SELECT ta_action FROM reply_interpretation WHERE message_id=?", (message_id,)).fetchone()
        if done is not None and done[0] is not None:
            raise ValueError(f"조교가 이미 결정한 답장입니다: 메시지 {message_id} ({done[0]})")
        if chosen_option_id is not None:
            opt = con.execute("SELECT proposal_id FROM proposal_option WHERE id=?", (chosen_option_id,)).fetchone()
            if opt is None or opt[0] != proposal_id:
                raise ValueError(f"이 안건의 대안이 아닙니다: 대안 {chosen_option_id}")
        data = json.dumps(_json_object(extracted_json, "extracted_json"), ensure_ascii=False)
        con.execute("""INSERT INTO reply_interpretation(message_id, label, chosen_option_id, extracted_json, model_name)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(message_id) DO UPDATE SET label=excluded.label, chosen_option_id=excluded.chosen_option_id,
                           extracted_json=excluded.extracted_json, model_name=excluded.model_name""",
                    (message_id, label, chosen_option_id, data, model_name))
        con.execute("UPDATE proposal SET status='PROPOSED' WHERE id=?", (proposal_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise


def _has_condition(cond):
    """조건 dict 에 실제 조건이 하나라도 있는지. {} 나 {"day_slots": {}, "end_before": []} 는 빈 조건."""
    return any(v not in (None, {}, [], "") for v in cond.values())


def decide_reply(con, message_id, user_id, action, reason=None, conditions=None, proposal_action=None,
                 option_id=None, pair_mode=None):
    """조교의 [확인](CONFIRM) / [수정](EDIT) / [현재대로 유지](KEEP) / [따로 연락](OFFLINE)을 기록한다.
    - 조교(role='TA')만, 해석이 저장돼 있고 안건이 PROPOSED 이고 그 안건의 가장 최근 답장일 때만. 이미 결정했으면 ValueError.
    - CONFIRM 은 proposal_action(조교가 확인한 처리안) 필수: 'move'(옮김) → RESOLVED, 'next'(다음 차수) → NEXT.
      'next' 는 conditions 가 비어 있으면 ValueError (다음 차수 대안에 넘길 조건이 있어야 한다).
    - CONFIRM + 'pair'(기타의 분반 연강·교차 요청): pair_mode(NONE/BACK_TO_BACK/CROSS) 필수. 답장한 교수의 그 과목 응답
      (가장 최근 차수) section_pair 를 바꾸고 → RESOLVED. 서버는 이어서 그 교수의 분반을 다시 풀어야 한다.
    - option_id: 옮긴 대안(proposal_option)을 reply_interpretation.chosen_option_id 에 남긴다 (CONFIRM 'move'·EDIT). 이 안건의 대안이어야 한다.
    - OFFLINE: 조교가 시스템 밖에서 교수와 따로 연락 → 안건 OFFLINE. 조건은 넣지 않는다. 이후 manual_place 로 수동 배치를 기록한다.
    - EDIT 는 reason(사유) 필수 → RESOLVED. KEEP 에는 conditions 를 넣지 않는다 → KEPT.
      EDIT·KEEP 에 넘긴 proposal_action 은 쓰지 않는다 (서버가 처리안 action 을 그대로 넘겨도 된다).
    - conditions(조교가 확인한 조건, EDIT 면 조교가 고친 조건)는 extracted_json 의 "confirmed_conditions" 에 그대로 저장한다.
      모양은 서버 conditions_json 과 같다: {"day_slots": {"1": ["09:00"]}, "end_before": [{"day": 2, "time": "17:00"}]}"""
    try:
        if action not in TA_ACTIONS:
            raise ValueError(f"조교 결정은 {TA_ACTIONS} 중 하나여야 합니다: {action}")
        if action == "CONFIRM":
            if proposal_action is None:
                raise ValueError("[확인]에는 처리안(proposal_action: 'move' 또는 'next')이 필요합니다")
            if proposal_action not in PROPOSAL_ACTIONS:
                raise ValueError(f"처리안은 {list(PROPOSAL_ACTIONS)} 중 하나여야 합니다: {proposal_action}")
            new_status = PROPOSAL_ACTIONS[proposal_action]
            if proposal_action == "pair" and pair_mode not in PAIR_MODES:
                raise ValueError(f"분반 연강·교차를 반영하려면 pair_mode({PAIR_MODES})가 필요합니다: {pair_mode}")
        else:
            new_status = {"EDIT": "RESOLVED", "KEEP": "KEPT", "OFFLINE": "OFFLINE"}[action]
        if action in ("KEEP", "OFFLINE") and option_id is not None:
            raise ValueError("[현재대로 유지]·[따로 연락]에는 옮길 대안을 넣지 않습니다")
        if action == "OFFLINE" and conditions is not None:
            raise ValueError("[따로 연락]에는 조건을 넣지 않습니다")
        if action == "EDIT" and not (reason and reason.strip()):
            raise ValueError("[수정]에는 사유가 필요합니다")
        if action == "KEEP" and conditions is not None:
            raise ValueError("[현재대로 유지]에는 조건을 넣지 않습니다")
        if new_status == "NEXT" and (conditions is None or not _has_condition(_json_object(conditions, "conditions"))):
            raise ValueError("처리안 '다음 차수'로 [확인]하려면 다음 차수에 넘길 조건(conditions)이 있어야 합니다. "
                             "조율할 조건이 없으면 [따로 연락](OFFLINE)을 고르세요")
        u = con.execute("SELECT role FROM user WHERE id=?", (user_id,)).fetchone()
        if u is None or u[0] != "TA":
            raise ValueError(f"조교만 결정할 수 있습니다: 사용자 {user_id}")
        proposal_id, p = _reply(con, message_id)
        ri = con.execute("SELECT extracted_json, ta_action FROM reply_interpretation WHERE message_id=?",
                         (message_id,)).fetchone()
        if ri is None:
            raise ValueError(f"해석이 아직 없습니다: 메시지 {message_id}. save_interpretation 을 먼저 부르세요")
        if ri[1] is not None:
            raise ValueError(f"이미 결정한 답장입니다: 메시지 {message_id} ({ri[1]})")
        if p["status"] != "PROPOSED":
            raise ValueError(f"조교 확인 대기(PROPOSED) 안건만 결정할 수 있습니다: 안건 {proposal_id} 상태 {p['status']}")
        if option_id is not None:
            opt = con.execute("SELECT proposal_id FROM proposal_option WHERE id=?", (option_id,)).fetchone()
            if opt is None or opt[0] != proposal_id:
                raise ValueError(f"이 안건의 대안이 아닙니다: 대안 {option_id}")
        data = _json_object(ri[0], "저장된 extracted_json")
        if conditions is not None:
            data["confirmed_conditions"] = _json_object(conditions, "conditions")
        if proposal_action == "pair" and action == "CONFIRM":
            prof = con.execute("SELECT sender_id FROM message WHERE id=?", (message_id,)).fetchone()[0]
            resp = con.execute("""SELECT id FROM course_response WHERE course_id=? AND professor_id=?
                                  ORDER BY round_id DESC, id DESC LIMIT 1""", (p["course_id"], prof)).fetchone()
            if resp is None:
                raise ValueError(f"분반 연강·교차를 반영할 교수 응답이 없습니다: 과목 {p['course_id']} 교수 {prof}")
            con.execute("UPDATE course_response SET section_pair=? WHERE id=?", (pair_mode, resp[0]))
            data["confirmed_section_pair"] = pair_mode
        con.execute("""UPDATE reply_interpretation SET ta_action=?, ta_reason=?, ta_user_id=?, ta_at=datetime('now'),
                       extracted_json=?, chosen_option_id=COALESCE(?, chosen_option_id) WHERE message_id=?""",
                    (action, reason, user_id, json.dumps(data, ensure_ascii=False), option_id, message_id))
        con.execute("UPDATE proposal SET status=? WHERE id=?", (new_status, proposal_id))
        con.commit()
    except Exception:
        con.rollback()
        raise


def confirmed_conditions(con, proposal_id):
    """조교가 [확인]·[수정]한 조건. 이 안건의 가장 최근 답장 중 CONFIRM·EDIT 된 것의 "confirmed_conditions".
    없으면 None. 저장한 모양 그대로 돌려준다 (solver alternatives(condition=...)에 바로 넘길 수 있다)."""
    row = con.execute("""SELECT ri.extracted_json FROM message m JOIN reply_interpretation ri ON ri.message_id = m.id
                         WHERE m.proposal_id=? AND m.kind='REPLY' AND ri.ta_action IN ('CONFIRM','EDIT')
                         ORDER BY m.id DESC LIMIT 1""", (proposal_id,)).fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(row[0]).get("confirmed_conditions")


def open_next_proposal(con, prev_proposal_id, round_id, timetable_id=None):
    """다음 차수에 새 조율 안건을 연다. -> 새 proposal id
    - 이전 안건이 NEXT(다음 차수로)이고, round_id 가 같은 학기의 바로 다음 차수(3차까지)일 때만.
    - 같은 과목·분반, status='OPEN', prev_proposal_id=이전 안건. 이유(reason)도 이어받는다.
    - timetable_id 가 없으면 이전 안건의 시간표 (NEXT 는 시간표를 바꾸지 않으므로). 주면 같은 학기 시간표인지 검사.
    - 이미 이 안건에서 다음 차수 안건을 열었으면 ValueError."""
    try:
        prev = con.execute("""SELECT p.timetable_id, p.course_id, p.section_no, p.reason, p.status, r.term_id, r.round_no
                              FROM proposal p JOIN round r ON r.id = p.round_id WHERE p.id=?""",
                           (prev_proposal_id,)).fetchone()
        if prev is None:
            raise ValueError(f"없는 조율 안건: {prev_proposal_id}")
        prev_tt, course_id, section_no, reason, status, term_id, prev_no = prev
        if status != "NEXT":
            raise ValueError(f"다음 차수로 넘긴 안건이 아닙니다: 안건 {prev_proposal_id} 상태 "
                             f"'{PROPOSAL_LABELS.get(status, status)}'({status}). 처리안 'next'로 [확인]한 안건만 이어 엽니다")
        if prev_no >= MAX_ROUND:
            raise ValueError(f"{MAX_ROUND}차 다음 차수는 없습니다: 안건 {prev_proposal_id}는 {prev_no}차. "
                             "남은 분반은 조교가 직접 정합니다")
        r = con.execute("SELECT term_id, round_no FROM round WHERE id=?", (round_id,)).fetchone()
        if r is None:
            raise ValueError(f"없는 차수: {round_id}")
        if r[0] != term_id:
            raise ValueError(f"다른 학기의 차수입니다: 차수 {round_id}는 학기 {r[0]}, 이전 안건은 학기 {term_id}")
        if r[1] != prev_no + 1:
            raise ValueError(f"바로 다음 차수가 아닙니다: 이전 안건은 {prev_no}차, 차수 {round_id}는 {r[1]}차")
        dup = con.execute("SELECT id FROM proposal WHERE prev_proposal_id=?", (prev_proposal_id,)).fetchone()
        if dup is not None:
            raise ValueError(f"이미 다음 차수 안건이 있습니다: 안건 {prev_proposal_id} → {dup[0]}")
        if timetable_id is None:
            timetable_id = prev_tt
        else:
            t = con.execute("SELECT term_id FROM timetable WHERE id=?", (timetable_id,)).fetchone()
            if t is None:
                raise ValueError(f"없는 시간표: {timetable_id}")
            if t[0] != term_id:
                raise ValueError(f"다른 학기의 시간표입니다: 시간표 {timetable_id}는 학기 {t[0]}, 이전 안건은 학기 {term_id}")
        cur = con.execute("""INSERT INTO proposal(round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id)
                             VALUES (?,?,?,?,?,'OPEN',?)""",
                          (round_id, timetable_id, course_id, section_no, reason, prev_proposal_id))
        con.commit()
        return cur.lastrowid
    except Exception:
        con.rollback()
        raise


def carried_conditions(con, proposal_id):
    """다음 차수 안건이 이어받은 조건: prev_proposal_id 가 가리키는 이전 안건의 confirmed_conditions (한 단계만).
    이전 안건이 없거나 확인된 조건이 없으면 None. solver alternatives(condition=...)에 바로 넘길 수 있다."""
    row = con.execute("SELECT prev_proposal_id FROM proposal WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 조율 안건: {proposal_id}")
    if row[0] is None:
        return None
    return confirmed_conditions(con, row[0])


def reply_choices(con, message_id):
    """답장에서 교수가 고른 값. -> [{"choice": 'A'|'B'|'C'|'ETC', "option_id": 대안 id 또는 None}] (A·B·C·기타 순)"""
    rows = con.execute("SELECT choice, option_id FROM reply_choice WHERE message_id=?", (message_id,)).fetchall()
    return [dict(choice=c, option_id=o) for c, o in sorted(rows, key=lambda r: REPLY_CHOICES.index(r[0]))]


def add_reply_request(con, message_id, body):
    """답장의 기타 중 시간표 밖 요청(예: 실습 조교 배치)을 기타 요청(other_request, PENDING)으로 남긴다. -> 새 id
    조교는 희망 입력의 기타 요청과 같이 pending_other_requests 로 보고 confirm_other_request 로 '확인함'을 누른다.
    기타(ETC)를 고른 답장이어야 하고, 답장당 하나."""
    try:
        row = con.execute("SELECT kind FROM message WHERE id=?", (message_id,)).fetchone()
        if row is None or row[0] != "REPLY":
            raise ValueError(f"교수 답장이 아닙니다: 메시지 {message_id}")
        if con.execute("SELECT 1 FROM reply_choice WHERE message_id=? AND choice='ETC'", (message_id,)).fetchone() is None:
            raise ValueError(f"기타를 고르지 않은 답장입니다: 메시지 {message_id}")
        if not (body and body.strip()):
            raise ValueError("기타 요청 내용이 비어 있습니다")
        if con.execute("SELECT 1 FROM other_request WHERE message_id=?", (message_id,)).fetchone():
            raise ValueError(f"이 답장의 기타 요청은 이미 있습니다: 메시지 {message_id}")
        cur = con.execute("INSERT INTO other_request(message_id, body) VALUES (?,?)", (message_id, body))
        con.commit()
        return cur.lastrowid
    except Exception:
        con.rollback()
        raise


def manual_place(con, proposal_id, user_id, rows, lock=True):
    """[따로 연락](OFFLINE)한 안건의 분반을 조교가 교수와 정한 칸에 직접 놓는다. -> 새 시간표 id (kind='TA_EDIT')
    rows: [(분반, 회차, 칸 id, 강의실 id), ...]  수업이 차지하는 칸마다 한 행 (assignment 와 같은 모양).
    - 안건이 OFFLINE 이고 조교(role='TA')만. 대상 분반 = 안건의 분반(없으면 과목의 모든 분반), 대상 분반마다 한 행 이상.
    - 그 학기 최신 시간표를 복사해 대상 분반만 바꾸고, 분반 배정 상태 MANUAL, lock 이면 고정(locked=1). 안건 → RESOLVED.
    - 같은 칸·같은 강의실은 DB 가 막는다(ValueError). 그 밖의 하드 규칙(교수 겹침·불가 칸·정원·채플·전필 겹침)은 막지 않는다:
      교수와 직접 합의한 결과이므로 저장하고, 서버가 solver_core.check_timetable 로 어긴 규칙을 받아 조교에게 경고로 보여 준다."""
    try:
        u = con.execute("SELECT role FROM user WHERE id=?", (user_id,)).fetchone()
        if u is None or u[0] != "TA":
            raise ValueError(f"조교만 수동 배치할 수 있습니다: 사용자 {user_id}")
        p = _proposal(con, proposal_id)
        if p["status"] != "OFFLINE":
            raise ValueError(f"[따로 연락]한 안건만 수동 배치합니다: 안건 {proposal_id} 상태 "
                             f"'{PROPOSAL_LABELS.get(p['status'], p['status'])}'({p['status']})")
        cid = p["course_id"]
        term = con.execute("SELECT t.term_id FROM proposal p JOIN timetable t ON t.id = p.timetable_id WHERE p.id=?",
                           (proposal_id,)).fetchone()[0]
        base = con.execute("SELECT MAX(id) FROM timetable WHERE term_id=?", (term,)).fetchone()[0]
        secs = [p["section_no"]] if p["section_no"] is not None else \
            [r[0] for r in con.execute("SELECT section_no FROM course_section WHERE course_id=? ORDER BY 1", (cid,))] or [1]
        rows = [tuple(r) for r in rows]
        if not rows:
            raise ValueError("놓을 칸이 없습니다")
        for sec, ss, sid, room in rows:
            if sec not in secs:
                raise ValueError(f"이 안건의 분반이 아닙니다: {sec}분반 (대상 {secs})")
            if con.execute("SELECT 1 FROM time_slot WHERE id=?", (sid,)).fetchone() is None:
                raise ValueError(f"없는 칸: {sid}")
            if con.execute("SELECT 1 FROM room WHERE id=?", (room,)).fetchone() is None:
                raise ValueError(f"없는 강의실: {room}")
        missing = [s_ for s_ in secs if not any(r[0] == s_ for r in rows)]
        if missing:
            raise ValueError(f"놓을 칸이 없는 분반이 있습니다: {missing}")
        tt = con.execute("""INSERT INTO timetable(term_id, round_id, kind, parent_id, created_by)
                            VALUES (?,?,'TA_EDIT',?,?)""", (term, p["round_id"], base, user_id)).lastrowid
        con.execute("""INSERT INTO timetable_section(timetable_id, course_id, section_no, planned_enrollment, status, locked)
                       SELECT ?, course_id, section_no, planned_enrollment, status, locked FROM timetable_section
                       WHERE timetable_id=? AND NOT (course_id=? AND section_no IN (%s))""" % ",".join("?" * len(secs)),
                    (tt, base, cid, *secs))
        for s_ in secs:
            enr = con.execute("""SELECT COALESCE((SELECT planned_enrollment FROM timetable_section
                                                 WHERE timetable_id=? AND course_id=? AND section_no=?),
                                                (SELECT enrollment FROM course_section WHERE course_id=? AND section_no=?))""",
                              (base, cid, s_, cid, s_)).fetchone()[0]
            con.execute("""INSERT INTO timetable_section(timetable_id, course_id, section_no, planned_enrollment, status, locked)
                           VALUES (?,?,?,?,'MANUAL',?)""", (tt, cid, s_, enr, int(bool(lock))))
        con.execute("""INSERT INTO assignment SELECT ?, course_id, section_no, session_no, slot_id, room_id FROM assignment
                       WHERE timetable_id=? AND NOT (course_id=? AND section_no IN (%s))""" % ",".join("?" * len(secs)),
                    (tt, base, cid, *secs))
        for sec, ss, sid, room in rows:
            try:
                con.execute("INSERT INTO assignment VALUES (?,?,?,?,?,?)", (tt, cid, sec, ss, sid, room))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"같은 시간에 이미 쓰는 강의실이거나 같은 칸이 두 번 들어갔습니다: 칸 {sid}, 강의실 {room} ({e})") from None
        con.execute("UPDATE proposal SET status='RESOLVED' WHERE id=?", (proposal_id,))
        con.commit()
        return tt
    except Exception:
        con.rollback()
        raise


def set_lock(con, timetable_id, course_id, section_no, locked):
    """분반 고정을 걸거나 푼다 (timetable_section.locked). 고정된 분반은 이 시간표에서 이어 푸는 모든 풀이에서 움직이지 않는다."""
    try:
        n = con.execute("UPDATE timetable_section SET locked=? WHERE timetable_id=? AND course_id=? AND section_no=?",
                        (int(bool(locked)), timetable_id, course_id, section_no)).rowcount
        if n == 0:
            raise ValueError(f"없는 분반 배정: 시간표 {timetable_id} 과목 {course_id} {section_no}분반")
        con.commit()
    except Exception:
        con.rollback()
        raise
