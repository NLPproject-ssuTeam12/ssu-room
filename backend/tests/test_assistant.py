"""AI 도우미 키워드 기준선 개발용 테스트 (실제 데이터 data/private/real 사용).

여기 질문은 개발 중 동작 확인용이다. 평가 문장(eval/labels/)은 사람이 따로 쓴다.
실행: python -m pytest backend/tests -q
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data" / "private" / os.environ.get("DATA_SET", "real")
if not (DATA / "sections.json").exists():
    pytest.skip(f"{DATA} 에 데이터가 없어 건너뜀", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.nlp import assistant  # noqa: E402
from backend.app.nlp.assistant import read_question, run_assistant  # noqa: E402
from backend.app.store import store  # noqa: E402


@pytest.fixture()
def client():
    c = TestClient(app)
    assert c.post("/reset").status_code == 200
    yield c
    c.post("/reset")


def sid_of(name: str, num: str, retake: bool = False) -> str:
    """과목명 + 분반 번호(코드 끝 두 자리) → 분반 id. 하나로 정해져야 한다."""
    hits = [s for s in store.list_sections()
            if s.name == name and s.code[-2:] == num and (not retake or (s.division and "재수강" in s.division))]
    assert len(hits) == 1, (name, num, [s.id for s in hits])
    return hits[0].id


# 앞 대화: 자료구조 02분반 이야기를 했다
HIST = [
    {"role": "user", "text": "자료구조 언제야?"},
    {"role": "assistant", "text": "자료구조 02분반 지금 배정: 목 13:30~16:15", "section_id": None},
]
# 앞 대화: 분반 id를 직접 받았다 (확률및통계)
HIST_ID = lambda: [{"role": "assistant", "text": "…", "section_id": sid_of("확률및통계", "02")}]  # noqa: E731

# (질문, 앞 대화, 의도, (과목, 번호, 재수강) 또는 None, 요일, 시각, 되묻기 여부)
CASES = [
    # explain
    ("디지털시스템입문 재수강 분반 왜 밀렸어?", None, "explain", ("디지털시스템입문", "03", True), [], None, False),
    ("자료구조 언제야?", None, "explain", ("자료구조", "02", False), [], None, False),
    ("운체 2분반 어디서 해?", None, "explain", ("운영체제", "02", False), [], None, False),            # 줄임말
    ("자연어처리 01분반 왜 이 시간이야?", None, "explain", ("자연언어처리", "01", False), [], None, False),  # 흔한 오타
    ("데이터 통신과 네트워크 02분반 언제야", None, "explain", ("데이터통신과네트워크", "02", False), [], None, False),  # 띄어쓰기
    ("인공지능 보안 왜 밀렸어", None, "explain", ("인공지능보안", "01", False), [], None, False),         # 띄어쓰기
    ("2150164203 왜 밀렸어", None, "explain", ("디지털시스템입문", "03", True), [], None, False),        # 과목 코드
    ("그 강의 왜 밀렸어?", "HIST_ID", "explain", ("확률및통계", "02", False), [], None, False),           # 그 강의
    # status
    ("지금 현황 알려줘", None, "status", None, [], None, False),
    ("조율 중인 분반 몇 개야?", None, "status", None, [], None, False),
    ("남은 분반 있어?", None, "status", None, [], None, False),
    ("어디까지 진행됐어?", None, "status", None, [], None, False),
    # what_if
    ("확통을 월·수 13:30으로 옮기면 어때?", None, "what_if", ("확률및통계", "02", False), ["월", "수"], "13:30", False),
    ("이산 수학 01분반 화목 1시 반으로 바꾸면?", None, "what_if", ("이산수학", "01", False), ["화", "목"], "13:30", False),  # 오후 해석
    ("수요일 15시를 비우면?", None, "what_if", None, ["수"], "15:00", False),
    ("21303 못 쓰면 어떻게 돼?", None, "what_if", None, [], None, False),
    ("그 강의 목요일 오후 3시로 옮기면 될까?", HIST, "what_if", ("자료구조", "02", False), ["목"], "15:00", False),  # 아까 그거
    # move
    ("확통 월수 10시 반으로 옮겨줘", None, "move", ("확률및통계", "02", False), ["월", "수"], "10:30", False),
    ("확률및통계 금요일 저녁으로 바꿔줘", None, "move", ("확률및통계", "02", False), ["금"], "18:00", False),
    ("웹프 재수강 정보관으로 옮겨줘", None, "move", ("웹프로그래밍", "03", True), [], None, False),
    ("그거 21305로 옮겨줘", HIST, "move", ("자료구조", "02", False), [], None, False),
    ("리눅스 활용 화·목 오후 4시 반으로 옮겨줘", None, "move", ("리눅스활용", "01", False), ["화", "목"], "16:30", False),
    # out_of_scope
    ("점심 뭐 먹지?", None, "out_of_scope", None, [], None, False),
    ("오늘 날씨 어때", None, "out_of_scope", None, [], None, False),
    ("안녕하세요", None, "out_of_scope", None, [], None, False),
    ("회의록 요약해줘", None, "out_of_scope", None, [], None, False),
    # 되묻기
    ("알고리즘 왜 밀렸어?", None, "explain", None, [], None, True),           # 분반 5개
    ("인공지능 왜 밀렸어", None, "explain", None, [], None, True),            # 과목 후보 2개
    ("알고리즘 09분반 왜 밀렸어", None, "explain", None, [], None, True),      # 없는 분반 번호
    ("확통 옮겨줘", None, "move", ("확률및통계", "02", False), [], None, True),  # 어디로?
    ("그 강의 왜 밀렸어?", None, "explain", None, [], None, True),             # 앞 대화 없음
    ("옮겨줘", None, "move", None, [], None, True),
]


@pytest.mark.parametrize("text,hist,intent,sec,days,start,ask", CASES, ids=[c[0] for c in CASES])
def test_read_question(text, hist, intent, sec, days, start, ask):
    history = HIST_ID() if hist == "HIST_ID" else (hist or [])
    cmd = read_question(text, history, store)
    assert cmd.intent == intent
    assert cmd.section_id == (sid_of(*sec) if sec else None)
    assert cmd.days == days
    assert cmd.day == (days[0] if days else None)
    assert cmd.start == start
    assert bool(cmd.ask_back) == ask, cmd.ask_back


def test_intent_counts():
    from collections import Counter
    n = Counter(c[2] for c in CASES)
    assert len(CASES) >= 25
    assert all(n[i] >= 4 for i in ("explain", "move", "what_if", "status", "out_of_scope")), n


def test_room_and_building():
    c = read_question("그거 21305로 옮겨줘", HIST, store)
    assert c.room == "정보과학관 21305"
    c = read_question("웹프 재수강 정보관으로 옮겨줘", [], store)
    assert c.room is None and c.building == "정보과학관"
    c = read_question("21303 못 쓰면 어떻게 돼?", [], store)
    assert c.room == "정보과학관 21303"


def test_professor_alias():
    c = read_question("교수45 자료구조 언제야", [], store)
    assert c.professor == "교수45" and c.section_id == sid_of("자료구조", "02")


@pytest.mark.parametrize("text,start", [
    ("확통 월요일 13시 반으로 옮기면?", "13:30"),
    ("확통 월요일 1시 반으로 옮기면?", "13:30"),     # 1~7시는 오후
    ("확통 월요일 3시로 옮기면?", "15:00"),
    ("확통 월요일 오전 10시로 옮기면?", "10:30"),    # 가장 가까운 칸
    ("확통 월요일 8시로 옮기면?", "09:00"),
    ("확통 월요일 저녁 7시로 옮기면?", "19:30"),
    ("확통 월요일 12:00으로 옮기면?", "12:00"),
    ("확통 월요일 오후로 옮기면?", "13:30"),
])
def test_time_parsing(text, start):
    assert read_question(text, [], store).start == start


def test_llm_not_implemented(client):
    with pytest.raises(NotImplementedError):
        read_question("현황", [], store, method="llm")
    r = client.post("/assistant", json={"text": "현황 알려줘", "method": "llm"})
    assert r.status_code == 501


# ---------- run_assistant / API ----------

def test_answers_by_intent(client):
    r = client.post("/assistant", json={"text": "지금 현황 알려줘"})
    assert r.status_code == 200 and "희망 수집" in r.json()["answer"]
    client.post("/draft")

    j = client.post("/assistant", json={"text": "지금 현황 알려줘"}).json()
    assert "조율 중 분반 3개" in j["answer"] and "MANUAL" in j["answer"]

    j = client.post("/assistant", json={"text": "디지털시스템입문 재수강 분반 왜 밀렸어?"}).json()
    assert "밀린 이유" in j["answer"] and j["needs_apply"] is False
    assert j["section_id"] == sid_of("디지털시스템입문", "03", True)

    j = client.post("/assistant", json={"text": "프로그래밍기초2 2분반 왜 이 시간이야?"}).json()
    assert "조교 직접 배정" in j["answer"]

    j = client.post("/assistant", json={"text": "프기2 2분반 월요일로 옮겨줘"}).json()
    assert "조교 직접 배정" in j["answer"] and j["proposal_id"] is None

    j = client.post("/assistant", json={"text": "수요일 15시를 비우면?"}).json()
    assert j["changes"] and j["proposal_id"] is None and "위반" in j["answer"]

    j = client.post("/assistant", json={"text": "점심 뭐 먹지?"}).json()
    assert j["answer"] == "시간표 편성·조율 관련 질문만 도울 수 있어요."

    j = client.post("/assistant", json={"text": "알고리즘 왜 밀렸어?"}).json()
    assert "몇 분반" in j["answer"] and j["command"]["ask_back"]


def test_answers_have_no_seniority_words(client):
    client.post("/draft")
    for q in ("디지털시스템입문 재수강 분반 왜 밀렸어?", "확통 월수 10시 반으로 옮겨줘", "지금 현황 알려줘"):
        ans = client.post("/assistant", json={"text": q}).json()["answer"]
        for w in ("연차", "선임", "우선순위", "임용"):
            assert w not in ans


def test_what_if_does_not_change_timetable(client):
    client.post("/draft")
    before = client.get("/timetable").json()
    j = client.post("/assistant", json={"text": "확통을 월·수 13:30으로 옮기면 어때?"}).json()
    assert j["proposal_id"] is None and j["needs_apply"] is False
    assert j["changes"][0]["note"] == "옮김" and "월 13:30" in j["changes"][0]["after"]
    assert client.get("/timetable").json() == before


def test_move_then_apply(client):
    client.post("/draft")
    sid = sid_of("확률및통계", "02")
    before = client.get("/timetable").json()

    j = client.post("/assistant", json={"text": "확통 월수 10시 반으로 옮겨줘"}).json()
    assert j["needs_apply"] is True and j["proposal_id"]
    assert j["changes"][0]["section_id"] == sid
    assert client.get("/timetable").json() == before          # 적용 전에는 그대로

    pid = j["proposal_id"]
    assert client.post("/assistant/apply", json={"proposal_id": pid}).status_code == 422
    assert client.post("/assistant/apply", json={"proposal_id": pid, "reason": "  "}).status_code == 422
    assert client.post("/assistant/apply", json={"proposal_id": "nope", "reason": "x"}).status_code == 404

    r = client.post("/assistant/apply", json={"proposal_id": pid, "reason": "교수님 전화 요청"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["reason"] == "교수님 전화 요청"
    a = next(x for x in client.get("/timetable").json()["assignments"] if x["section_id"] == sid)
    assert [(b["day"], b["start"]) for b in a["blocks"]] == [("월", "10:30"), ("수", "10:30")]
    rec = store.decisions[-1]
    assert rec["action"] == "assistant_move" and rec["reason"] == "교수님 전화 요청" and rec["section_id"] == sid

    # 한 번 쓴 제안은 다시 못 쓴다
    assert client.post("/assistant/apply", json={"proposal_id": pid, "reason": "x"}).status_code == 404


def test_apply_after_timetable_changed_409(client):
    client.post("/draft")
    p1 = client.post("/assistant", json={"text": "확통 월수 10시 반으로 옮겨줘"}).json()["proposal_id"]
    p2 = client.post("/assistant", json={"text": "리눅스 활용 화·목 오후 4시 반으로 옮겨줘"}).json()["proposal_id"]
    assert client.post("/assistant/apply", json={"proposal_id": p1, "reason": "a"}).status_code == 200
    r = client.post("/assistant/apply", json={"proposal_id": p2, "reason": "b"})
    assert r.status_code == 409 and "바뀌었" in r.json()["detail"]


def test_apply_in_final_409(client):
    client.post("/draft")
    pid = client.post("/assistant", json={"text": "확통 월수 10시 반으로 옮겨줘"}).json()["proposal_id"]
    client.post("/finalize")
    r = client.post("/assistant/apply", json={"proposal_id": pid, "reason": "늦은 요청"})
    assert r.status_code == 409
    # 확정 뒤에는 move 제안도 만들지 않는다
    j = client.post("/assistant", json={"text": "확통 월수 12시로 옮겨줘"}).json()
    assert j["proposal_id"] is None and "확정" in j["answer"]


def test_reset_clears_proposals(client):
    client.post("/draft")
    pid = client.post("/assistant", json={"text": "확통 월수 10시 반으로 옮겨줘"}).json()["proposal_id"]
    client.post("/reset")
    assert assistant.get_proposal(pid) is None


def test_history_from_previous_answer(client):
    """화면은 응답의 section_id를 history에 넣어 다음 질문에 보낸다."""
    client.post("/draft")
    j = client.post("/assistant", json={"text": "자료구조 언제야?"}).json()
    hist = [{"role": "user", "text": "자료구조 언제야?"},
            {"role": "assistant", "text": j["answer"], "section_id": j["section_id"]}]
    j2 = client.post("/assistant", json={"text": "그 강의 금요일로 옮기면?", "history": hist}).json()
    assert j2["command"]["section_id"] == j["section_id"]
    assert j2["command"]["intent"] == "what_if"
