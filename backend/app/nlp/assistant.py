"""AI 도우미 — 키워드 기준선 (백엔드 ③, 김대원).

조교 질문 → read_question → AssistantCommand(의도·정보) → run_assistant → 배정 함수 호출 → 설명.
- 배정은 engine의 함수만 쓴다. 도우미는 시간표를 직접 바꾸지 않는다.
- move는 '제안'으로만 저장한다. 조교가 POST /assistant/apply 를 눌러야 반영된다.
- 설명에 연차·우선순위 이유, 다른 교수의 기타 요청은 쓰지 않는다.
- method="llm"(언어 모델 버전): 언어 모델은 의도와 과목명·요일·시각 같은 정보만 뽑는다.
  분반 연결·되묻기·이동 가능 여부는 키워드 버전과 같은 코드가 정한다. 실패하면 키워드 방식으로 대신 처리한다.

contracts.AssistantCommand에는 요일이 하나(day)뿐이고 건물 칸이 없어서,
여기서는 그 하위 모양 AssistantQuery(days, building 추가)를 쓴다.
문하윤 schemas.py가 오면 두 칸을 넣어 달라고 할 것.
"""

import re
import uuid
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from .. import engine
from ..contracts import (
    DAYS, LATE_SLOT, STARTS, AssistantCommand, Block, Day, alternative, dump, late_penalty, no_long_at_1800,
)
from .llm import LLMUnavailable, generate_json, load_prompt

# ---------- 모양 ----------


class AssistantQuery(AssistantCommand):
    days: List[Day] = []                 # "월·수" 처럼 여러 요일. day = days[0]
    building: Optional[str] = None       # 강의실 없이 건물만 말했을 때
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False               # 언어 모델이 실패해서 키워드 방식으로 대신 처리했으면 True
    fallback_reason: Optional[str] = None   # 그 이유 (언어 모델 호출·형식 오류 문구 그대로)


# ---------- 사전 ----------

# 줄임말 → 실제 과목명 (몇 개만)
ABBR: Dict[str, str] = {
    "자구": "자료구조",
    "운체": "운영체제",
    "os": "운영체제",
    "컴네": "컴퓨터네트워크",
    "데통": "데이터통신과네트워크",
    "인입": "인공지능입문",
    "디시입": "디지털시스템입문",
    "확통": "확률및통계",
    "웹프": "웹프로그래밍",
    "모프": "모바일프로그래밍",
    "시프": "시스템프로그래밍",
    "캡디": "캡스톤디자인",
    "고캡": "고급캡스톤디자인",
    "클컴": "클라우드컴퓨팅",
    "소분설": "소프트웨어분석및설계",
    "자연어처리": "자연언어처리",
    "nlp": "자연언어처리",
    "머신": "머신러닝",
    "프기1": "프로그래밍기초1",
    "프기2": "프로그래밍기초2",
}

BUILDING_ALIAS: Dict[str, str] = {
    "정보과학관": "정보과학관",
    "정보관": "정보과학관",
    "문화관": "문화관",
    "전산관": "전산관",
    "벤처중소기업센터": "벤처중소기업센터",
    "벤처관": "벤처중소기업센터",
}

RE_EXPLAIN = re.compile(r"왜|이유|어째서|밀렸|밀린\s*이유|언제|어디(?!까지)")
RE_STATUS = re.compile(r"현황|남은|남았|몇\s*개|몇\s*분반|어디까지|진행|상태|몇\s*차|조율\s*중인\s*(분반|과목|강의)?\s*(몇|목록|있)")
RE_WHATIF = re.compile(r"옮기면|바꾸면|넣으면|비우면|빼면|못\s*쓰면|쓰면|하면|가면|면\s*어때|면\s*어떨까|되나|될까|돼\?|괜찮을까|가능할까|가능해\?|어때")
RE_MOVE = re.compile(r"옮겨|바꿔|넣어|이동해|이동시켜|배정해|변경해|옮기자|바꾸자")
RE_PRONOUN = re.compile(r"그\s*강의|그\s*수업|그\s*과목|그\s*분반|아까\s*그거|그거|그것|거기")

_DAY_TOKEN = re.compile(
    r"(?<![가-힣])((?:[월화수목금](?:\s*[·,/와과랑및]\s*)?)+?)(?:요일|욜)?"
    r"(?:에는|에|은|는|이|도|로|으로|만|부터|까지|랑)?(?![가-힣])"
)
_TIME_HM = re.compile(r"(오전|오후|저녁|밤)?\s*(\d{1,2}):(\d{2})")
_TIME_SI = re.compile(r"(오전|오후|저녁|밤)?\s*(\d{1,2})\s*시\s*(반|(\d{1,2})\s*분)?(?!\s*(전|이전|까지))")
_TIME_WORD = {"오전": "09:00", "오후": "13:30", "저녁": "18:00", "밤": "19:30"}


def _norm(text: str) -> str:
    return re.sub(r"[\s\[\]()·\-_/,.]", "", text).lower()


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _snap(minutes: int) -> str:
    """가장 가까운 시작 칸 (같으면 이른 쪽)."""
    return min(STARTS, key=lambda s: (abs(_to_min(s) - minutes), _to_min(s)))


def _block_text(b: Block) -> str:
    s = _to_min(b.start)
    e = s + 75 * b.slots + 15 * (b.slots - 1)
    return f"{b.day} {b.start}~{_to_hhmm(e)}"


def _place_text(blocks: List[Block], room: Optional[str]) -> str:
    return f"{' / '.join(_block_text(b) for b in blocks) or '시간 없음'} · {room or '강의실 미정'}"


def section_label(sec) -> str:
    label = f"{sec.code[-2:]}분반"
    return f"{label}{' ' + sec.division if sec.division else ''}"


def section_title(sec) -> str:
    return f"{sec.name} {section_label(sec)}"


# ---------- 정보 뽑기 ----------

def _extract_days(text: str) -> List[str]:
    days: List[str] = []
    for m in _DAY_TOKEN.finditer(text):
        for ch in m.group(1):
            if ch in DAYS and ch not in days:
                days.append(ch)
    return days


def _extract_time(text: str) -> Optional[str]:
    m = _TIME_HM.search(text)
    if m:
        ampm, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
    else:
        m = _TIME_SI.search(text)
        if m:
            ampm, h = m.group(1), int(m.group(2))
            mi = 30 if m.group(3) == "반" else int(m.group(4) or 0)
        else:
            for word, start in _TIME_WORD.items():
                if word in text:
                    return start
            return None
    if ampm in ("오후", "저녁", "밤") and h < 12:
        h += 12
    elif ampm is None and 1 <= h <= 7:
        h += 12           # "1시 반" = 13:30
    return _snap(h * 60 + mi)


def _match_course(norm_text: str, names: List[str]) -> Tuple[List[str], str]:
    """과목명 찾기 → (후보 이름들, 지운 뒤 남은 글). 후보가 둘 이상이면 되묻는다."""
    by_norm = {_norm(n): n for n in names}
    # 1) 과목명 전체 (긴 것 먼저: '네트워크보안' > '네트워크')
    for key in sorted(by_norm, key=len, reverse=True):
        if key and key in norm_text:
            return [by_norm[key]], norm_text.replace(key, " ", 1)
    # 2) 줄임말
    for abbr in sorted(ABBR, key=len, reverse=True):
        if abbr in norm_text and _norm(ABBR[abbr]) in by_norm:
            return [ABBR[abbr]], norm_text.replace(abbr, " ", 1)
    # 3) 일부 일치: 과목명 앞부분 3글자 이상이 질문에 있음
    best, hits = 0, []
    for key, name in by_norm.items():
        for n in range(len(key), 2, -1):
            if key[:n] in norm_text:
                if n > best:
                    best, hits = n, [name]
                elif n == best:
                    hits.append(name)
                break
    if hits:
        stem = next(k for k in by_norm if by_norm[k] == hits[0])[:best]
        return sorted(set(hits)), norm_text.replace(stem, " ", 1)
    return [], norm_text


def _match_number(rest: str) -> Tuple[Optional[str], bool]:
    """분반 번호 → ('02', 재수강 여부)."""
    retake = "재수강" in rest
    for pat in (r"(\d{1,2})분반", r"(?<!\d)(\d{1,2})반(?!\d)", r"(?<![\d:])(0[1-9])(?![\d:시])"):
        m = re.search(pat, rest)
        if m:
            return f"{int(m.group(1)):02d}", retake
    return None, retake


def _history_section(history: List[dict], store) -> Optional[str]:
    names = sorted({s.name for s in store.list_sections()})
    for item in reversed(history or []):
        sid = item.get("section_id")
        if sid and store.get_section(sid):
            return sid
        text = item.get("text") or ""
        cands, rest = _match_course(_norm(text), names)
        if len(cands) == 1:
            secs = [s for s in store.list_sections() if s.name == cands[0]]
            num, retake = _match_number(rest)
            if num:
                secs = [s for s in secs if s.code[-2:] == num]
            if len(secs) == 1:
                return secs[0].id
    return None


def _pick_section(cands: List[str], rest: str, professor: Optional[str], code_sid: Optional[str],
                  pronoun: bool, history: Optional[List[dict]], store) -> Tuple[Optional[str], Optional[str]]:
    """과목 후보·분반 번호 글·교수·지시어 → (section_id, 되물을 말). 키워드·언어 모델 버전이 같이 쓴다.
    rest = 분반 번호를 찾을 글 (예: "02분반", "재수강")."""
    sections = store.list_sections()
    section_id, ask = None, None
    if code_sid:
        section_id = code_sid
    elif len(cands) > 1:
        ask = f"어느 과목인가요? 후보: {', '.join(cands)}"
    elif len(cands) == 1:
        secs = [s for s in sections if s.name == cands[0]]
        num, retake = _match_number(rest)
        if professor:
            secs = [s for s in secs if s.professor == professor] or secs
        if retake:
            secs = [s for s in secs if s.division and "재수강" in s.division]
        if num:
            picked = [s for s in secs if s.code[-2:] == num]
            if not picked:
                ask = (f"{cands[0]}에 {num}분반이 없어요. 있는 분반: "
                       f"{', '.join(section_label(s) for s in secs)}")
            secs = picked
        if len(secs) == 1:
            section_id = secs[0].id
        elif len(secs) > 1 and not ask:
            opts = ", ".join(f"{section_label(s)}({s.professor or '담당 미정'}, {s.code})" for s in secs)
            ask = f"{cands[0]}은(는) 분반이 {len(secs)}개예요. 몇 분반인가요? ({opts})"
    elif pronoun:
        section_id = _history_section(history or [], store)
        if section_id is None:
            ask = "어느 분반을 말씀하시는지 알려 주세요. (예: 알고리즘 02분반)"
    elif professor:
        mine = [s for s in sections if s.professor == professor]
        if len(mine) == 1:
            section_id = mine[0].id
    return section_id, ask


def _find_room(room_no: Optional[str], norm: str, store) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """강의실 번호(5자리) → (room id, 건물, 되물을 말). 방을 못 정하면 글에서 건물 이름을 찾는다."""
    room, building, ask = None, None, None
    if room_no:
        room = next((r.id for r in store.list_rooms() if r.room_no == room_no), None)
        if room is None:
            ask = f"{room_no} 강의실을 찾지 못했어요."
    if room is None:
        for alias, b in BUILDING_ALIAS.items():
            if alias in norm:
                building = b
                break
    return room, building, ask


def _ask_back(intent: str, section_id: Optional[str], days: List[str], start: Optional[str],
              room: Optional[str], building: Optional[str], ask: Optional[str], store) -> Optional[str]:
    """되묻기 규칙 (키워드·언어 모델 버전 공통, 코드로 판단)."""
    has_target = bool(days or start or room or building)
    if not ask:
        if intent == "explain" and not section_id:
            ask = "어느 분반을 말씀하시는지 알려 주세요. (예: 알고리즘 02분반)"
        elif intent == "move":
            if not section_id:
                ask = "어느 분반을 옮길까요? (예: 알고리즘 02분반)"
            elif not has_target:
                ask = "어디로 옮길까요? 요일·시각이나 강의실을 알려 주세요."
        elif intent == "what_if":
            if not section_id and not (start and days) and not room:
                ask = "무엇을 바꿔 볼까요? 분반과 옮길 시간, 또는 비울 시간(요일+시각)이나 못 쓰는 강의실을 알려 주세요."
            elif section_id and not has_target:
                ask = "어디로 옮겨 볼까요? 요일·시각이나 강의실을 알려 주세요."
        if not ask and intent in ("move", "what_if") and section_id and len(days) == 1:
            ask = _ask_pair_day(store.get_section(section_id), days[0])
    if intent == "out_of_scope":
        ask = None
    return ask


def read_question(text: str, history: Optional[List[dict]], store, method: str = "keyword") -> AssistantQuery:
    """조교 질문 + 앞 대화 → AssistantQuery. 정보가 모자라면 ask_back에 되물을 말을 넣는다.
    method="llm": 언어 모델이 의도·정보를 뽑고, 분반 연결·되묻기는 코드가 한다.
    언어 모델이 실패하면 키워드 방식으로 대신 처리하고 fallback=True."""
    if method == "llm":
        try:
            return _read_question_llm(text, history, store)
        except (LLMUnavailable, ValueError) as e:
            q = _read_question_keyword(text, history, store)
            q.fallback, q.fallback_reason = True, str(e) or type(e).__name__
            return q
    if method != "keyword":
        raise ValueError(f"method는 keyword 또는 llm: {method!r}")
    return _read_question_keyword(text, history, store)


def _read_question_keyword(text: str, history: Optional[List[dict]], store) -> AssistantQuery:
    raw = (text or "").strip()
    norm = _norm(raw)
    sections = store.list_sections()
    names = sorted({s.name for s in sections})

    # --- 분반 ---
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", raw)
    code_hits = [s for s in sections if m and s.code == m.group(1)]
    cands, rest = ([], norm.replace(m.group(1), " ")) if code_hits else _match_course(norm, names)
    professor = None
    pm = re.search(r"교수\s*0?(\d{1,2})", raw)
    if pm:
        professor = f"교수{int(pm.group(1)):02d}"
    section_id, ask = _pick_section(cands, rest, professor, code_hits[0].id if code_hits else None,
                                    bool(RE_PRONOUN.search(raw)), history, store)

    # --- 요일·시각·강의실 (과목명을 뺀 글에서) ---
    rest_raw = raw
    if section_id:
        sec = store.get_section(section_id)
        rest_raw = re.sub(r"\s*".join(map(re.escape, sec.name.replace(" ", ""))), " ", raw)
    for abbr in ABBR:
        rest_raw = re.sub(re.escape(abbr), " ", rest_raw, flags=re.I)
    rest_raw = re.sub(r"\d{1,2}\s*분반|재수강", " ", rest_raw)
    days = _extract_days(rest_raw)
    start = _extract_time(rest_raw)

    rm = re.search(r"(?<!\d)(\d{5})(?!\d)", raw)
    room, building, room_ask = _find_room(rm.group(1) if rm else None, norm, store)
    ask = ask or room_ask

    # --- 의도 ---
    has_target = bool(days or start or room or building)
    has_entity = bool(section_id or cands or has_target or professor or RE_PRONOUN.search(raw))
    if RE_EXPLAIN.search(raw):
        intent = "explain"
    elif RE_STATUS.search(raw):
        intent = "status"
    elif RE_WHATIF.search(raw) or (raw.endswith("?") and has_entity and not RE_MOVE.search(raw)):
        intent = "what_if"
    elif RE_MOVE.search(raw):
        intent = "move"
    else:
        intent = "out_of_scope"
    if intent == "what_if" and not has_entity:
        intent = "out_of_scope"

    ask = _ask_back(intent, section_id, days, start, room, building, ask, store)
    return AssistantQuery(
        intent=intent, section_id=section_id, professor=professor,
        day=days[0] if days else None, days=days, start=start,
        room=room, building=building, ask_back=ask,
    )


# ---------- 언어 모델 버전 ----------

class _AssistantLLM(BaseModel):
    """언어 모델이 돌려줄 모양. 분반 id는 받지 않는다 (코드가 과목명·번호로 찾는다)."""
    intent: Literal["explain", "move", "what_if", "status", "out_of_scope"]
    course: str = ""            # 과목명 (질문이나 앞 대화에 나온 것)
    section_no: str = ""        # 분반 번호 ("02"), 없으면 ""
    retake: bool = False        # 재수강 분반
    from_history: bool = False  # "그 강의"처럼 앞 대화의 분반을 가리킴
    professor: str = ""         # "교수03" 같은 가명
    days: List[str] = []        # ["월", "수"]
    start: str = ""             # 교시 시작 시각 ("13:30")
    room_no: str = ""           # 강의실 번호 (5자리)
    building: str = ""


def _history_text(history: Optional[List[dict]]) -> str:
    lines = []
    for h in (history or [])[-6:]:
        who = "조교" if h.get("role") == "user" else "도우미"
        lines.append(f"{who}: {(h.get('text') or '').strip()}")
    return "\n".join(lines) or "(없음)"


def _sections_text(store) -> str:
    rows = sorted(store.list_sections(), key=lambda s: (s.name, s.code))
    return "\n".join(f"{s.name} | {s.code[-2:]}분반{' ' + s.division if s.division else ''} | {s.professor or '담당 미정'}"
                     for s in rows)


def _from_llm(r: _AssistantLLM, raw: str, history: Optional[List[dict]], store) -> AssistantQuery:
    """언어 모델 답 → AssistantQuery. 없는 과목·교시·요일·교수·강의실은 버리고, 분반 연결과 되묻기는 코드가 한다."""
    sections = store.list_sections()
    names = sorted({s.name for s in sections})
    course = (r.course or "").strip()
    cands = [course] if course in names else (_match_course(_norm(course), names)[0] if course else [])
    pm = re.search(r"교수\s*0?(\d{1,2})", r.professor or "")
    professor = f"교수{int(pm.group(1)):02d}" if pm else None
    if professor and not any(s.professor == professor for s in sections):
        professor = None
    num = re.sub(r"\D", "", r.section_no or "")[:2]
    rest = (f"{int(num):02d}분반" if num and int(num) > 0 else "") + (" 재수강" if r.retake else "")
    pronoun = r.from_history or bool(RE_PRONOUN.search(raw))
    section_id, ask = _pick_section(cands, rest, professor, None, pronoun and not cands, history, store)

    days = [d for d in dict.fromkeys((x or "").strip()[:1] for x in r.days) if d in DAYS]
    start = (r.start or "").strip()
    start = start if start in STARTS else None
    room_no = re.sub(r"\D", "", r.room_no or "")
    if room_no and room_no not in raw:      # 질문에 없는 번호는 지어낸 것으로 보고 버린다
        room_no = ""
    room, building, room_ask = _find_room(room_no or None, _norm(r.building or ""), store)
    ask = ask or room_ask
    ask = _ask_back(r.intent, section_id, days, start, room, building, ask, store)
    return AssistantQuery(
        intent=r.intent, section_id=section_id, professor=professor,
        day=days[0] if days else None, days=days, start=start,
        room=room, building=building, ask_back=ask, method="llm",
    )


def _read_question_llm(text: str, history: Optional[List[dict]], store) -> AssistantQuery:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("빈 질문")
    prompt = (load_prompt("assistant")
              .replace("<<SECTIONS>>", _sections_text(store))
              .replace("<<HISTORY>>", _history_text(history))
              .replace("<<QUESTION>>", raw))
    return _from_llm(generate_json(prompt, _AssistantLLM), raw, history, store)


def _ask_pair_day(sec, day: str) -> Optional[str]:
    """주 2회 분반인데 요일을 하나만 말하면 묶을 요일을 되묻는다. 주 1회 연강·MANUAL 분반은 묻지 않는다."""
    if sec is None or sec.shape != "TWICE":
        return None
    i = DAYS.index(day)
    other = DAYS[i + 2] if i + 2 < len(DAYS) else DAYS[i - 2]
    pair = "·".join(sorted((day, other), key=DAYS.index))
    return (f"{section_title(sec)}은(는) 주 2회 수업이에요. {day}요일과 묶을 요일을 하나 더 알려 주세요. "
            f"(예: {pair})")


# ---------- 실행 ----------

_PROPOSALS: Dict[str, dict] = {}


def clear_proposals() -> None:
    _PROPOSALS.clear()


def get_proposal(pid: str) -> Optional[dict]:
    return _PROPOSALS.get(pid)


def pop_proposal(pid: str) -> Optional[dict]:
    return _PROPOSALS.pop(pid, None)


def timetable_key(tt) -> Optional[str]:
    """제안을 만든 뒤 시간표가 바뀌었는지 알아보는 열쇠."""
    return None if tt is None else repr(dump(tt)["assignments"])


def _result(answer: str, changes: Optional[list] = None, pid: Optional[str] = None) -> dict:
    return {"answer": answer, "proposal_id": pid, "changes": changes or [], "needs_apply": pid is not None}


def _assignment(store, sid: str):
    if store.timetable is None:
        return None
    return next((a for a in store.timetable.assignments if a.section_id == sid), None)


def _cells(b: Block) -> List[str]:
    if b.start not in STARTS:
        return []
    i = STARTS.index(b.start)
    return [f"{b.day}-{STARTS[j]}" for j in range(i, min(i + b.slots, len(STARTS)))]


def _new_blocks(cur: List[Block], cmd: AssistantQuery) -> Tuple[Optional[List[Block]], Optional[str]]:
    """옮길 자리 계산. (새 블록, 되물을 말)."""
    if not cur:
        return None, "지금 배정된 시간이 없어 옮길 자리를 계산할 수 없어요."
    days = cmd.days
    if len(days) > len(cur):
        return None, f"이 분반은 주 {len(cur)}번 수업이에요. 요일을 {len(cur)}개만 알려 주세요."
    out = [Block(day=b.day, start=b.start, slots=b.slots) for b in cur]
    if len(days) == len(cur):
        for b, d in zip(out, days):
            b.day = d
    elif len(days) == 1:          # 두 번 중 하나만 말함
        same = [b for b in out if b.day == days[0]]
        if not same:
            now = ", ".join(_block_text(b) for b in cur)
            return None, f"두 번 중 어느 수업을 {days[0]}요일로 옮길까요? (지금: {now}) 두 요일을 함께 말해 주세요."
        targets = same
    if cmd.start:
        for b in (targets if len(days) == 1 and len(cur) > 1 else out):
            if _to_min(cmd.start) + 75 * b.slots + 15 * (b.slots - 1) > _to_min("21:00"):
                return None, f"{cmd.start}에 시작하면 {b.slots}칸 수업이 너무 늦게 끝나요. 더 이른 시각을 알려 주세요."
            b.start = cmd.start
    return out, None


def _overlaps(b: Block, f: dict) -> bool:
    s0 = _to_min(b.start)
    s1 = s0 + 75 * b.slots + 15 * (b.slots - 1)
    return f.get("day") == b.day and _to_min(f["start"]) < s1 and s0 < _to_min(f["end"])


def _chapels(blocks: List[Block], fixed_blocks: List[dict], year: Optional[int]) -> Tuple[List[str], List[str]]:
    """이 분반이 옮길 자리와 겹치는 채플 → (막을 채플, 경고만 할 채플). 각각 '요일 시작~끝'.
    - 막음: AI대학(AI소프트웨어학부·정보보호학과) 대상 채플이고, 분반 학년이 그 채플 대상 학년과 같을 때
    - 경고: 모든 단과대학이 고르는 채플(대상이 애매), 또는 학년이 정해지지 않은 분반(year 없음)의 AI대학 채플
    - 다른 학과 채플은 보지 않는다"""
    block, warn = [], []
    for f in fixed_blocks:
        if f.get("kind") != "채플" or not any(_overlaps(b, f) for b in blocks):
            continue
        scope, years = f.get("scope"), f.get("years") or []
        text = f"{f['day']} {f['start']}~{f['end']}"
        if scope == "AI대학" and year is not None and year in years:
            block.append(text)
        elif scope == "AI대학" and year is None:
            warn.append(text)
        elif scope == "전체" and (not years or year is None or year in years):
            warn.append(text)
    order = lambda t: (DAYS.index(t[0]), t[2:])   # 요일 순
    return sorted(set(block), key=order), sorted(set(warn), key=order)


def _forbidden(blocks: List[Block], sec, wish, fixed_blocks: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """(옮기면 안 되는 이유, 경고). 교수 불가 시간 → 채플(대상 학년) → 18:00 연강 순으로 본다."""
    blocked = [c for b in blocks for c in _cells(b) if wish and wish.cells.get(c) == "BLOCK"]
    if blocked:
        return f"교수 불가 시간({', '.join(blocked)})이에요. 다른 시간을 알려 주세요.", None
    block, warn = _chapels(blocks, fixed_blocks, sec.year)
    if block:
        return (f"{sec.year}학년 채플 시간({', '.join(block)})과 겹쳐요. 그 시간은 비워 둬야 해요. "
                "다른 시간을 알려 주세요."), None
    if not no_long_at_1800(blocks):
        return "18:00에 시작하는 연강은 없어요(20:45에 끝나요). 더 이른 시각을 알려 주세요.", None
    note = (f"채플 시간({', '.join(warn)})과 겹쳐요. 대상 학년이 정해지지 않은 채플이라 막지는 않았어요. "
            "조교님이 확인해 주세요.") if warn else None
    return None, note


def _pick_room(cmd: AssistantQuery, store, current: Optional[str]) -> Optional[str]:
    if cmd.room:
        return cmd.room
    if cmd.building:
        if current and current.startswith(cmd.building + " "):
            return current
        sec = store.get_section(cmd.section_id) if cmd.section_id else None
        need_lab = sec is not None and sec.lab_need == "MUST"
        size = (sec.enrollment or 0) if sec else 0
        rooms = [r for r in store.list_rooms() if r.building == cmd.building
                 and (r.is_lab or not need_lab) and (r.capacity is None or r.capacity >= size)]
        return rooms[0].id if rooms else current
    return current


def _explain(cmd: AssistantQuery, store) -> dict:
    sec = store.get_section(cmd.section_id)
    title = section_title(sec)
    a = _assignment(store, sec.id)
    lines = []
    if sec.shape == "MANUAL":
        lines.append(f"{title}은(는) 조교 직접 배정 분반이에요(수업 모양이 주 2회·주 1회 연강이 아님). 자동 배정·조율 대상이 아니에요.")
    if a is None:
        if store.timetable is None:
            lines.append("아직 초안이 없어 배정 자리가 없어요. 초안을 만든 뒤 다시 물어봐 주세요.")
        return _result(" ".join(lines) or f"{title}의 배정 정보가 없어요.")

    lines.append(f"{title} 지금 배정: {_place_text(a.blocks, a.room)}.")
    if sec.shape != "MANUAL":
        wish = store.get_wish(sec.id)
        if wish is None or not wish.cells:
            lines.append("이 분반은 희망 칸 정보가 없어요.")
        else:
            used = [c for b in a.blocks for c in _cells(b)]
            blocked = [c for c in used if wish.cells.get(c) == "BLOCK"]
            outside = [c for c in used if wish.cells.get(c) is None]
            if blocked:
                lines.append(f"교수 불가 칸({', '.join(blocked)})에 걸려 있어요.")
            elif outside:
                lines.append(f"희망 칸 밖({', '.join(outside)})이에요. 불가 칸은 아니에요.")
            else:
                lines.append("모두 교수 희망 칸 안이에요.")
    if a.status == "COORD":
        item = store.get_coord(sec.id)
        state = {"OPEN": "메시지 보내기 전", "SENT": "답장 기다림", "PROPOSED": "처리안 확인 기다림",
                 "RESOLVED": "반영됨", "KEPT": "현재대로 유지"}.get(item["state"], item["state"]) if item else ""
        lines.append(f"조율 중이에요{f' ({state})' if state else ''}. 밀린 이유: {a.reason or '기록 없음'}")
    elif a.status == "DONE":
        lines.append("배정이 정해진 상태(DONE)예요.")
    return _result(" ".join(lines))


def _status(store) -> dict:
    secs = store.list_sections()
    manual = sum(1 for s in secs if s.shape == "MANUAL")
    stage_name = {"COLLECT": "희망 수집", "DRAFT": "초안", "ROUND": "조율", "FINAL": "확정"}[store.stage]
    if store.stage == "COLLECT":
        return _result(f"지금은 {stage_name} 단계예요. 아직 초안이 없어요. "
                       f"분반 {len(secs)}개 중 조교 직접 배정(MANUAL) {manual}개.")
    items = store.list_coord()
    open_items = [c for c in items if c["state"] not in ("RESOLVED",)]
    waiting = sum(1 for c in items if c["state"] == "SENT")
    proposed = sum(1 for c in items if c["state"] == "PROPOSED")
    not_sent = sum(1 for c in items if c["state"] == "OPEN")
    rnd = f" {store.round_no}차" if store.stage == "ROUND" else ""
    text = (f"지금은 {stage_name}{rnd} 단계예요. 조율 중 분반 {len(open_items)}개"
            f" (메시지 전 {not_sent}, 답장 기다림 {waiting}, 처리안 확인 기다림 {proposed}),"
            f" 반영 끝 {len(items) - len(open_items)}개. 조교 직접 배정(MANUAL) {manual}개.")
    rows = [{"section_id": c["section_id"], "name": section_title(store.get_section(c["section_id"])),
             "before": None, "after": None, "note": c["state"]} for c in open_items]
    return _result(text, rows)


def _what_if(cmd: AssistantQuery, store, as_move: bool) -> dict:
    if store.timetable is None:
        return _result("아직 초안이 없어요. 초안을 만든 뒤 물어봐 주세요.")
    tt = store.timetable
    by_id = {a.section_id: a for a in tt.assignments}

    def row(sid, after, note):
        a = by_id.get(sid)
        sec = store.get_section(sid)
        return {"section_id": sid, "name": section_title(sec) if sec else sid,
                "before": _place_text(a.blocks, a.room) if a else None, "after": after, "note": note}

    # 분반 없이: 시간 비우기 / 강의실 못 씀
    if not cmd.section_id:
        if cmd.room:
            change = {"kind": "room_off", "room": cmd.room}
            what = f"{cmd.room}을(를) 못 쓰면"
        else:
            change = {"kind": "free", "day": cmd.days[0], "start": cmd.start}
            what = f"{cmd.days[0]} {cmd.start}을(를) 비우면"
        res = engine.what_if(tt, change)
        changed = [s for s in res["changed"] if s in by_id]
        rows = [row(s, "다시 배정 필요", "영향 받음") for s in changed]
        return _result(f"{what} 분반 {len(changed)}개가 자리를 옮겨야 해요. 그때 규칙 위반은 {res['violations']}건이에요. "
                       "(미리 보기만 했고 시간표는 그대로예요.)", rows)

    sec = store.get_section(cmd.section_id)
    title = section_title(sec)
    if sec.shape == "MANUAL":
        return _result(f"{title}은(는) 조교 직접 배정 분반이라 도우미가 옮기지 않아요. 시간표에서 직접 정해 주세요.")
    if as_move and store.stage == "FINAL":
        return _result("시간표가 이미 확정됐어요. 확정 뒤에는 옮길 수 없어요.")
    a = by_id.get(sec.id)
    if a is None:
        return _result(f"{title}은(는) 시간표에 없어요.")
    blocks, ask = _new_blocks(a.blocks, cmd)
    if ask:
        return _result(ask)
    room = _pick_room(cmd, store, a.room)
    if [dump(b) for b in blocks] == [dump(b) for b in a.blocks] and room == a.room:
        return _result(f"{title}은(는) 이미 그 자리예요: {_place_text(a.blocks, a.room)}.")
    why_not, chapel_note = _forbidden(blocks, sec, store.get_wish(sec.id), store.fixed_blocks)
    if why_not:   # 교수 불가 시간·채플·18:00 연강으로는 옮기지 않는다 (미리 보기도 하지 않음)
        return _result(f"{title}을(를) {_place_text(blocks, room)}(으)로는 옮기지 않아요. {why_not}")

    change = {"kind": "move", "section_id": sec.id, "day": blocks[0].day, "start": blocks[0].start,
              "room": room, "blocks": [dump(b) for b in blocks]}
    res = engine.what_if(tt, change)
    others = [s for s in res["changed"] if s != sec.id and s in by_id]
    rows = [row(sec.id, _place_text(blocks, room), "옮김")]
    rows += [row(s, "겹침 → 다시 배정 필요", "영향 받음") for s in others]

    lines = [f"{title}을(를) {_place_text(blocks, room)}(으)로 옮기면"]
    lines.append(f"같이 바뀌어야 하는 다른 분반 {len(others)}개, 규칙 위반 {res['violations']}건이에요.")
    if late_penalty(blocks):
        lines.append(f"{LATE_SLOT} 교시는 다른 방법이 없을 때만 쓰는 늦은 교시예요(큰 감점).")
    if chapel_note:
        lines.append(chapel_note)

    if not as_move:
        lines.append("(미리 보기만 했어요. 옮기려면 '옮겨줘'라고 말해 주세요.)")
        return _result(" ".join(lines), rows)

    pid = uuid.uuid4().hex[:12]
    _PROPOSALS[pid] = {
        "proposal_id": pid,
        "section_id": sec.id,
        "alternative": alternative("A", blocks, room),
        "base": timetable_key(tt),
        "summary": f"{title}: {_place_text(a.blocks, a.room)} → {_place_text(blocks, room)}",
        "violations": res["violations"],
    }
    lines.append("아직 반영하지 않았어요. [적용]을 누르고 사유를 적으면 반영돼요.")
    return _result(" ".join(lines), rows, pid)


def run_assistant(cmd: AssistantCommand, store) -> dict:
    """AssistantCommand → 배정 함수 호출 → {answer, proposal_id, changes, needs_apply}."""
    if cmd.ask_back:
        return _result(cmd.ask_back)
    if cmd.intent == "out_of_scope":
        return _result("시간표 편성·조율 관련 질문만 도울 수 있어요.")
    if cmd.intent == "status":
        return _status(store)
    if cmd.intent == "explain":
        return _explain(cmd, store)
    q = cmd if isinstance(cmd, AssistantQuery) else AssistantQuery(**dump(cmd), days=[cmd.day] if cmd.day else [])
    return _what_if(q, store, as_move=(cmd.intent == "move"))
