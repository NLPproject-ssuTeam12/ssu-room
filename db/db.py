"""DB 연결 함수. 서버·솔버·테스트는 sqlite3.connect를 직접 쓰지 말고 이것으로 연결한다.
SQLite는 외래키 검사가 연결마다 꺼진 채로 시작하므로 연결할 때마다 켠다."""
import sqlite3


def connect(path="ssuroom.db"):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


# ---------------------------------------------------------------- 서버 단계
PHASES = ["COLLECTING", "ROUND1", "ROUND2", "FINAL"]
PHASE_LABELS = {"COLLECTING": "희망 수집", "ROUND1": "1차 조율", "ROUND2": "2차 조율", "FINAL": "확정"}


def get_phase(con, term_id):
    """지금 단계. -> dict(phase='ROUND1', label='1차 조율', changed_at=...)"""
    row = con.execute("SELECT phase, phase_changed_at FROM term WHERE id=?", (term_id,)).fetchone()
    if row is None:
        raise ValueError(f"없는 학기: {term_id}")
    return dict(phase=row[0], label=PHASE_LABELS[row[0]], changed_at=row[1])


def set_phase(con, term_id, to_phase, user_id=None, force=False):
    """단계를 바꾸고 기록을 남긴다. 기본은 다음 단계로 한 칸씩만(희망 수집 → 1차 조율 → 2차 조율 → 확정).
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
    """조교가 아직 확인하지 않은 기타 요청. -> [(other_request_id, 과목 id, 교수 id, 본문)]"""
    return con.execute("""SELECT o.id, r.course_id, r.professor_id, o.body
                          FROM other_request o JOIN course_response r ON r.id = o.response_id
                          WHERE r.round_id=? AND o.status='PENDING' ORDER BY o.id""", (round_id,)).fetchall()


def confirm_other_request(con, other_request_id, user_id, memo=None):
    """조교가 '확인함'을 누른다."""
    n = con.execute("""UPDATE other_request SET status='CONFIRMED', confirmed_by=?, confirmed_at=datetime('now'),
                       ta_memo=COALESCE(?, ta_memo) WHERE id=?""", (user_id, memo, other_request_id)).rowcount
    if n == 0:
        raise ValueError(f"없는 기타 요청: {other_request_id}")
    con.commit()
