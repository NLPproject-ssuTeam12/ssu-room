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
    DAYS, LATE_SLOT, STARTS, AssistantCommand, Block, Day, alternative, block_room, dump, late_penalty,
    no_long_at_1800,
)
from .aliases import BUILDING_ALIAS, COURSE_ALIAS, alias_table_text, course_alias_hits
from .llm import LLMUnavailable, generate_json, load_prompt

# ---------- 모양 ----------


class AssistantQuery(AssistantCommand):
    days: List[Day] = []                 # "월·수" 처럼 여러 요일. day = days[0]
    building: Optional[str] = None       # 강의실 없이 건물만 말했을 때
    method: Literal["keyword", "llm"] = "keyword"
    fallback: bool = False               # 언어 모델이 실패해서 키워드 방식으로 대신 처리했으면 True
    fallback_reason: Optional[str] = None   # 그 이유 (언어 모델 호출·형식 오류 문구 그대로)


# ---------- 사전 ----------

# 줄임말 표는 aliases.py 한 곳에 둔다 (키워드·언어 모델 두 방식이 같이 쓴다)

RE_EXPLAIN = re.compile(r"왜|이유|어째서|밀렸|밀린\s*이유|언제|어디(?!까지)")
RE_STATUS = re.compile(r"현황|남은|남았|몇\s*개|몇\s*분반|어디까지|진행|상태|몇\s*차|조율\s*중인\s*(분반|과목|강의)?\s*(몇|목록|있)")
# 답장·회신을 묻는 말은 '언제·어디'가 있어도 현황이다 ("회신 언제 와?")
RE_STATUS_FIRST = re.compile(r"답장|회신|몇\s*차(?!시)")
RE_WHATIF = re.compile(r"옮기면|바꾸면|넣으면|비우면|빼면|당기면|미루면|못\s*쓰면|쓰면|하면|가면|면\s*어때|면\s*어떨까"
                       r"|되나|될까|돼\?|괜찮을까|가능할까|가능해\?|어때|겹쳐|겹치|겹칠|문제\s*없|자리\s*(있|없|남)|비어\s*있|빌까")
RE_MOVE = re.compile(r"옮겨|바꿔|넣어|이동해|이동시켜|배정해|변경해|옮기자|바꾸자|당겨|미뤄|빼\s*줘|빼\s*주세요")
# 시간표 밖 일 (수강신청·메일·식사 등). 시간표 말이 섞여 있어도 이것이 먼저다
RE_OUT = re.compile(r"수강\s*신청|이\s*메일|메일|문자\s*(보내|돌려)|점심\s*(뭐|메뉴|먹)|학식|식당|날씨|회식|성적|출석|휴가|월급")
# "A 말고 B": 뒤(B)가 목표
RE_NOT = re.compile(r"말고|대신에?|아니고")
RE_PRONOUN = re.compile(r"그\s*강의|그\s*수업|그\s*과목|그\s*분반|아까\s*그거|그거|그것|거기")

_DAY_TOKEN = re.compile(
    r"(?<![가-힣])((?:[월화수목금](?:\s*[·,/와과랑및]\s*)?)+?)(?:요일|욜)?"
    r"(?:에는|에|은|는|이|도|로|으로|만|부터|까지|랑)?(?![가-힣])"
)
_TIME_HM = re.compile(r"(오전|오후|저녁|밤)?\s*(\d{1,2}):(\d{2})")
_TIME_SI = re.compile(r"(오전|오후|저녁|밤)?\s*(\d{1,2})\s*시\s*(반|(\d{1,2})\s*분)?(?!\s*(전|이전|까지))")
# 때를 가리키는 말 → 그 안의 교시 (긴 말 먼저). 교시가 하나면 그대로 받고, 여럿이면 되묻는다
_TIME_WORD = {"늦은오후": ["16:30"], "오전": ["09:00", "10:30"],
              "오후": ["13:30", "15:00", "16:30"], "저녁": ["18:00", "19:30"], "밤": ["19:30"]}


def _norm(text: str) -> str:
    return re.sub(r"[\s\[\]()·\-_/,.]", "", text).lower()


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _choose(slots: List[str]) -> str:
    """되묻는 말: "13:30과 15:00 중 언제로 할까요?" """
    if len(slots) == 1:
        return f"{slots[0]}으로 할까요?"
    if len(slots) == 2:
        return f"{slots[0]}과 {slots[1]} 중 언제로 할까요?"
    return f"{', '.join(slots)} 중 언제로 할까요?"


def _block_text(b: Block) -> str:
    s = _to_min(b.start)
    e = s + 75 * b.slots + 15 * (b.slots - 1)
    return f"{b.day} {b.start}~{_to_hhmm(e)}"


def _place_text(blocks: List[Block], room: Optional[str] = None) -> str:
    """수업마다 강의실이 같으면 "화 13:30~14:45 / 목 13:30~14:45 · 문화관 03407",
    다르면 "화 13:30~14:45 문화관 03407 / 목 13:30~14:45 정보과학관 21304".
    room을 주면 모든 수업을 그 강의실로 본다 (Block.room이 비었을 때도 room)."""
    rooms = [room or b.room for b in blocks]
    if len(set(rooms)) > 1:
        return " / ".join(f"{_block_text(b)} {r or '강의실 미정'}" for b, r in zip(blocks, rooms))
    one = rooms[0] if rooms else room
    return f"{' / '.join(_block_text(b) for b in blocks) or '시간 없음'} · {one or '강의실 미정'}"


def _asg_text(a) -> str:
    """배정 하나를 글로 (수업마다 그 수업의 강의실)."""
    if not a.blocks:
        return _place_text([], a.room)
    return _place_text([b.model_copy(update={"room": block_room(a, b)}) for b in a.blocks])


def section_label(sec) -> str:
    label = f"{sec.code[-2:]}분반"
    return f"{label}{' ' + sec.division if sec.division else ''}"


def section_title(sec) -> str:
    return f"{sec.name} {section_label(sec)}"


# 숫자 끝 글자 읽는 소리의 받침: 영·일·이·삼·사·오·육·칠·팔·구 (0은 십·백처럼 받침 있음)
_DIGIT_JONG = {"0": "o", "1": "ㄹ", "2": "", "3": "o", "4": "", "5": "", "6": "o", "7": "ㄹ", "8": "ㄹ", "9": ""}


def _jong(word: str) -> str:
    """끝 글자 받침: '' 없음, 'ㄹ', 'o' 그 밖. '09:00'처럼 정각은 '9시'로 읽어 받침 없음."""
    w = word.rstrip()
    if not w or w.endswith(":00"):
        return ""
    ch = w[-1]
    if ch in _DIGIT_JONG:
        return _DIGIT_JONG[ch]
    if "가" <= ch <= "힣":
        j = (ord(ch) - 0xAC00) % 28
        return "" if j == 0 else ("ㄹ" if j == 8 else "o")
    return ""


def _j(word: str, josa: str) -> str:
    """word + 받침에 맞는 조사. josa = 은 / 을 / 이 / 과 / 으로 ('은(는)'처럼 둘 다 쓰지 않으려고, 11/26 전체 시연)."""
    jong = _jong(word)
    if josa == "으로":
        return word + ("로" if jong in ("", "ㄹ") else "으로")
    pair = {"은": ("은", "는"), "을": ("을", "를"), "이": ("이", "가"), "과": ("과", "와")}[josa]
    return word + (pair[0] if jong else pair[1])


# 조율 안건 상태를 화면과 같은 말로 (OFFLINE·KEPT 같은 영어 값을 그대로 보이지 않는다)
_STATE_TEXT = {"OPEN": "메시지 보내기 전", "SENT": "답장 기다림", "PROPOSED": "처리안 확인 기다림",
               "RESOLVED": "반영됨", "KEPT": "지금 자리 유지", "HOLD": "조교 선택 대기", "NO_OPTION": "대안 없음",
               "OFFLINE": "따로 연락 중", "NEXT": "다음 차수로"}
_DONE_STATES = ("RESOLVED", "KEPT")


# ---------- 정보 뽑기 ----------

def _extract_days(text: str) -> List[str]:
    days: List[str] = []
    for m in _DAY_TOKEN.finditer(text):
        for ch in m.group(1):
            if ch in DAYS and ch not in days:
                days.append(ch)
    return days


def _read_time(text: str) -> Tuple[Optional[str], Optional[str]]:
    """시각 표현 → (교시 시작 시각, 되물을 말). 키워드·언어 모델 버전이 같이 쓴다.
    교시 시작(09:00·10:30·…·19:30)과 딱 맞으면 그 시각. 맞지 않거나("2시") 때만 말하면("오후로")
    가장 가까운 교시로 바꾸지 않고 되묻는다. 시각이 없으면 (None, None)."""
    text = text or ""
    m = _TIME_HM.search(text)
    if m:
        ampm, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
    else:
        m = _TIME_SI.search(text)
        if m:
            ampm, h = m.group(1), int(m.group(2))
            mi = 30 if m.group(3) == "반" else int(m.group(4) or 0)
        else:
            t = re.sub(r"\s+", "", text)
            for word, slots in _TIME_WORD.items():
                if word in t:
                    if len(slots) == 1:
                        return slots[0], None
                    name = "늦은 오후" if word == "늦은오후" else word
                    return None, f"{name} 교시는 {_choose(slots)}"
            return None, None
    if ampm in ("오후", "저녁", "밤") and h < 12:
        h += 12
    elif ampm is None and 1 <= h <= 7:
        h += 12           # "1시 반" = 13:30
    said = h * 60 + mi
    hhmm = _to_hhmm(said)
    if hhmm in STARTS:
        return hhmm, None
    before = [x for x in STARTS if _to_min(x) < said][-1:]
    after = [x for x in STARTS if _to_min(x) > said][:1]
    return None, f"{hhmm}은 교시 시작 시각이 아니에요. {_choose(before + after)}"


def _match_course(norm_text: str, names: List[str]) -> Tuple[List[str], str]:
    """과목명 찾기 → (후보 이름들, 지운 뒤 남은 글). 후보가 둘 이상이면 되묻는다."""
    by_norm = {_norm(n): n for n in names}
    # 1) 과목명 전체 (긴 것 먼저: '네트워크보안' > '네트워크')
    for key in sorted(by_norm, key=len, reverse=True):
        if key and key in norm_text:
            return [by_norm[key]], norm_text.replace(key, " ", 1)
    # 2) 줄임말 (aliases.py, 여러 과목을 가리키면 후보 여럿 → 되묻기)
    hits, rest = course_alias_hits(norm_text, names, _norm)
    if hits:
        return hits, rest
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
            bases = sorted({s.code[:-2] for s in secs})
            if len(bases) > 1:   # 같은 이름 과목이 둘 이상 (과목 코드가 다름) → 코드·학과·학년을 같이 보여 준다
                opts = ", ".join(f"{s.code} {section_label(s)}({_course_tag(s)}, {s.professor or '담당 미정'})"
                                 for s in sorted(secs, key=lambda s: s.code))
                ask = f"{_j(cands[0], '이')} 과목 코드가 다른 과목 {len(bases)}개에 있어요. 어느 과목·몇 분반인가요? ({opts})"
            else:
                def opt(s):   # 학교 과목번호 대신 담당과 지금 시간으로 구분한다
                    a = _assignment(store, s.id)
                    return f"{section_label(s)}({s.professor or '담당 미정'}{', ' + _asg_text(a) if a and a.blocks else ''})"
                opts = ", ".join(opt(s) for s in secs)
                ask = f"{_j(cands[0], '은')} 분반이 {len(secs)}개예요. 몇 분반인가요? ({opts})"
    elif pronoun:
        section_id = _history_section(history or [], store)
        if section_id is None:
            ask = "어느 분반을 말씀하시는지 알려 주세요. (예: 알고리즘 02분반)"
    elif professor:
        mine = [s for s in sections if s.professor == professor]
        if len(mine) == 1:
            section_id = mine[0].id
    return section_id, ask


def _course_tag(sec) -> str:
    """같은 이름 과목을 가르는 말: 학과(이수구분 뒤쪽)·학년."""
    dept = (sec.category or "").partition("-")[2] or (sec.category or "")
    year = f"{sec.year}학년" if sec.year else "전체 학년"
    return " ".join(x for x in (dept, year) if x)


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
              room: Optional[str], building: Optional[str], ask: Optional[str], store,
              time_ask: Optional[str] = None) -> Optional[str]:
    """되묻기 규칙 (키워드·언어 모델 버전 공통, 코드로 판단).
    time_ask = _read_time이 낸 시각 되묻기 ("2시", "오후"처럼 교시가 정해지지 않음)."""
    has_target = bool(days or start or room or building or time_ask)
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
        if not ask and intent in ("move", "what_if") and time_ask:
            ask = time_ask
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
    # "A 말고 B": 뒤쪽 글이 목표. 과목·요일·시각은 뒤쪽에서 먼저 찾는다
    target = RE_NOT.split(raw)[-1] if RE_NOT.search(raw) else raw

    # --- 분반 ---
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", raw)
    code_hits = [s for s in sections if m and s.code == m.group(1)]
    if code_hits:
        cands, rest = [], norm.replace(m.group(1), " ")
    else:
        cands, rest = _match_course(_norm(target), names) if target is not raw else ([], norm)
        if not cands:
            cands, rest = _match_course(norm, names)
    professor = None
    pm = re.search(r"교수\s*0?(\d{1,2})", raw)
    if pm:
        professor = f"교수{int(pm.group(1)):02d}"
    section_id, ask = _pick_section(cands, rest, professor, code_hits[0].id if code_hits else None,
                                    bool(RE_PRONOUN.search(raw)), history, store)

    # --- 요일·시각·강의실 (과목명을 뺀 글에서) ---
    rest_raw = target
    if section_id:
        sec = store.get_section(section_id)
        rest_raw = re.sub(r"\s*".join(map(re.escape, sec.name.replace(" ", ""))), " ", target)
    for abbr in sorted(COURSE_ALIAS, key=len, reverse=True):
        rest_raw = re.sub(re.escape(abbr), " ", rest_raw, flags=re.I)
    rest_raw = re.sub(r"\d{1,2}\s*분반|재수강", " ", rest_raw)
    days = _extract_days(rest_raw)
    start, time_ask = _read_time(rest_raw)

    rm = re.search(r"(?<!\d)(\d{5})(?!\d)", raw)
    room, building, room_ask = _find_room(rm.group(1) if rm else None, norm, store)
    ask = ask or room_ask

    # --- 의도 ---
    has_target = bool(days or start or room or building or time_ask)
    has_entity = bool(section_id or cands or has_target or professor or RE_PRONOUN.search(raw))
    if RE_OUT.search(raw):
        intent = "out_of_scope"       # 시간표 밖 일이 먼저. 뽑은 교수·과목 정보는 그대로 남긴다
    elif RE_STATUS_FIRST.search(raw):
        intent = "status"
    elif RE_EXPLAIN.search(raw):
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

    ask = _ask_back(intent, section_id, days, start, room, building, ask, store, time_ask)
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
    time_text: str = ""         # 질문에 나온 시각 표현 그대로 ("2시", "1시 반", "오후", "13:30"). 코드가 교시로 읽는다
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


def _said_courses(texts: List[str], names: List[str]) -> set:
    """질문·앞 대화 글에서 _match_course로 찾히는 과목들."""
    found = set()
    for t in texts:
        if t:
            found |= set(_match_course(_norm(t), names)[0])
    return found


def _said_building(building: str, texts: List[str]) -> Optional[str]:
    """모델이 준 건물이 질문·앞 대화에 (별칭으로라도) 나올 때만 그 건물."""
    b = BUILDING_ALIAS.get(_norm(building or ""))
    if not b:
        return None
    aliases = [a for a, x in BUILDING_ALIAS.items() if x == b]
    return b if any(a in _norm(t) for t in texts if t for a in aliases) else None


def _from_llm(r: _AssistantLLM, raw: str, history: Optional[List[dict]], store) -> AssistantQuery:
    """언어 모델 답 → AssistantQuery. 질문·앞 대화에 없는 과목·건물·강의실, 없는 요일·교수는 버리고,
    시각 읽기·분반 연결·되묻기는 키워드 버전과 같은 코드가 한다."""
    sections = store.list_sections()
    names = sorted({s.name for s in sections})
    texts = [raw] + [(h.get("text") or "") for h in (history or [])]
    course = (r.course or "").strip()
    cands = [course] if course in names else (_match_course(_norm(course), names)[0] if course else [])
    said = _said_courses(texts, names)
    cands = [c for c in cands if c in said]       # 질문·앞 대화에서 찾히지 않는 과목은 지어낸 것으로 보고 버린다
    pm = re.search(r"교수\s*0?(\d{1,2})", r.professor or "")
    professor = f"교수{int(pm.group(1)):02d}" if pm else None
    if professor and not any(s.professor == professor for s in sections):
        professor = None
    num = re.sub(r"\D", "", r.section_no or "")[:2]
    rest = (f"{int(num):02d}분반" if num and int(num) > 0 else "") + (" 재수강" if r.retake else "")
    pronoun = r.from_history or bool(RE_PRONOUN.search(raw))
    section_id, ask = _pick_section(cands, rest, professor, None, pronoun and not cands, history, store)

    days = [d for d in dict.fromkeys((x or "").strip()[:1] for x in r.days) if d in DAYS]
    time_text = (r.time_text or "").strip()
    if time_text and _norm(time_text) not in _norm(raw):   # 질문에 없는 시각 표현은 버린다
        time_text = ""
    start, time_ask = _read_time(time_text)
    room_no = re.sub(r"\D", "", r.room_no or "")
    if room_no and room_no not in raw:      # 질문에 없는 번호는 지어낸 것으로 보고 버린다
        room_no = ""
    building = _said_building(r.building, texts)
    room, found_building, room_ask = _find_room(room_no or None, _norm(building or ""), store)
    ask = ask or room_ask
    ask = _ask_back(r.intent, section_id, days, start, room, found_building, ask, store, time_ask)
    return AssistantQuery(
        intent=r.intent, section_id=section_id, professor=professor,
        day=days[0] if days else None, days=days, start=start,
        room=room, building=found_building, ask_back=ask, method="llm",
    )


def _read_question_llm(text: str, history: Optional[List[dict]], store) -> AssistantQuery:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("빈 질문")
    names = sorted({s.name for s in store.list_sections()})
    prompt = (load_prompt("assistant")
              .replace("<<ALIASES>>", alias_table_text(names, _norm))
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
    return (f"{_j(section_title(sec), '은')} 주 2회 수업이에요. {day}요일과 묶을 요일을 하나 더 알려 주세요. "
            f"(예: {pair})")


# ---------- 실행 ----------

_KIND_TEXT = {"UNPLACED": "못 놓음", "MISMATCH": "희망에서 어긋남", "PARTIAL": "일부 어긋남"}
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
    out = [Block(day=b.day, start=b.start, slots=b.slots, room=b.room) for b in cur]   # 수업마다 강의실 유지
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


def _pick_room(cmd: AssistantQuery, store, a) -> Optional[str]:
    """바꿀 강의실. None = 수업마다 지금 강의실 그대로, 값 = 분반의 모든 수업을 그 강의실로."""
    if cmd.room:
        return cmd.room
    if cmd.building:
        current = [block_room(a, b) for b in a.blocks]
        if current and all(r and r.startswith(cmd.building + " ") for r in current):
            return None
        sec = store.get_section(cmd.section_id) if cmd.section_id else None
        need_lab = sec is not None and sec.lab_need == "MUST"
        size = (sec.enrollment or 0) if sec else 0
        rooms = [r for r in store.list_rooms() if r.building == cmd.building
                 and (r.is_lab or not need_lab) and (r.capacity is None or r.capacity >= size)]
        return rooms[0].id if rooms else None
    return None


STUB_NOTE = "(가짜 엔진 결과예요. 실제 계산은 DB 모드(SSUROOM_ENGINE=solver)에서 해요.)"


def _db():
    """DB 모드면 DBMode, 아니면 None (dbmode 가 main 을 거쳐 이 모듈을 부르므로 함수 안에서 가져온다)."""
    from .. import dbmode
    return dbmode.active()


def _run_what_if(tt, change: dict) -> dict:
    """DB 모드: 하윤 엔진으로 복사본에서 계산(dbmode.what_if). 메모리 모드: 가짜 엔진 + 가짜 표시."""
    db = _db()
    if db is not None:
        return dict(db.what_if(change), real=True)
    res = engine.what_if(tt, change)
    return dict(res, supported=True, real=False, feasible=res["violations"] == 0, rules=[], moved=[], unplaced=[],
                option=None, clash=None, note="")


def _rule_lines(res: dict, by_title) -> List[str]:
    out = []
    if res.get("clash"):
        out.append(res["clash"])
    for r in res.get("rules", [])[:5]:
        who = ", ".join(by_title(x) for x in (r.get("section_ids") or ([r["section_id"]] if r.get("section_id") else [])))
        out.append(f"{r['rule']}: {who + ' ' if who else ''}({r['detail']})")
    return out


def _explain(cmd: AssistantQuery, store) -> dict:
    sec = store.get_section(cmd.section_id)
    title = section_title(sec)
    a = _assignment(store, sec.id)
    lines = []
    if sec.shape == "MANUAL":
        lines.append(f"{_j(title, '은')} 조교 직접 배정 분반이에요(수업 모양이 주 2회·주 1회 연강이 아님). 자동 배정·조율 대상이 아니에요.")
    if a is None:
        if store.timetable is None:
            lines.append("아직 초안이 없어 배정 자리가 없어요. 초안을 만든 뒤 다시 물어봐 주세요.")
        return _result(" ".join(lines) or f"{title}의 배정 정보가 없어요.")

    lines.append(f"{title} 지금 배정: {_asg_text(a)}.")
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
    db = _db()
    if db is not None and sec.shape != "MANUAL":
        # DB 모드: 하윤 check_timetable 로 이 분반이 낀 하드 규칙 위반
        cid, no = db.section_key(sec.id)
        vs = [v for v in db.violations() if v["course_id"] == cid and v["section_no"] == no]
        lines.append(f"규칙 위반 {len(vs)}건" + (f": {', '.join(v['rule'] for v in vs)}." if vs else "이에요."))
        item = store.get_coord(sec.id)
        if item and item.get("kind"):
            lines.append(f"조율 대상 종류: {_KIND_TEXT.get(item['kind'], item['kind'])}.")
    if a.status == "COORD":
        item = store.get_coord(sec.id)
        state = _STATE_TEXT.get(item["state"], item["state"]) if item else ""
        if store.stage == "FINAL":
            lines.append(f"조율이 끝나지 않아 임시 자리로 확정했어요{f' (마지막 상태: {state})' if state else ''}. "
                         f"밀린 이유: {a.reason or '기록 없음'}")
        else:
            lines.append(f"조율 중이에요{f' ({state})' if state else ''}. 밀린 이유: {a.reason or '기록 없음'}")
    elif a.status == "DONE":
        lines.append("배정이 끝난 분반이에요.")
    return _result(" ".join(lines))


def _status(store) -> dict:
    """현황. 상태는 화면과 같은 우리말로, 지금 자리 유지(KEPT)도 끝난 것으로 센다 (11/26 전체 시연)."""
    secs = store.list_sections()
    manual = sum(1 for s in secs if s.shape == "MANUAL")
    if store.stage == "COLLECT":
        return _result(f"지금은 희망 수집 단계예요. 아직 초안이 없어요. "
                       f"분반 {len(secs)}개 중 조교 직접 배정 {manual}개.")
    items = store.list_coord()
    done = [c for c in items if c["state"] in _DONE_STATES]
    left = [c for c in items if c["state"] not in _DONE_STATES]

    def count(cs):
        n = {}
        for c in cs:
            k = _STATE_TEXT.get(c["state"], c["state"])
            n[k] = n.get(k, 0) + 1
        return ", ".join(f"{k} {v}" for k, v in n.items())

    head = {"DRAFT": "초안이 나왔어요.", "FINAL": "시간표를 확정했어요."}.get(
        store.stage, f"지금은 {store.round_no}차 조율 중이에요.")
    if not items:
        text = f"{head} 조율 대상은 없어요. 조교 직접 배정 {manual}개."
    elif store.stage == "FINAL":
        text = (f"{head} 조율 대상 {len(items)}개 중 끝난 것 {len(done)}개"
                f"{f'({count(done)})' if done else ''}, 임시 자리로 확정 {len(left)}개. 조교 직접 배정 {manual}개.")
    else:
        text = (f"{head} 조율 대상 {len(items)}개 중 끝난 것 {len(done)}개"
                f"{f'({count(done)})' if done else ''}, 남은 것 {len(left)}개"
                f"{f'({count(left)})' if left else ''}. 조교 직접 배정 {manual}개.")

    def note(c):
        sec = store.get_section(c["section_id"])
        state = _STATE_TEXT.get(c["state"], c["state"])
        if store.stage == "FINAL":
            state = f"임시 자리로 확정 (마지막: {state})"
        who = sec.professor if sec and sec.professor else "담당 미정"
        rnd = f" · {c['round_no']}차" if c.get("round_no") and store.stage != "FINAL" else ""
        return f"{who} · {state}{rnd}"

    rows = [{"section_id": c["section_id"], "name": section_title(store.get_section(c["section_id"])),
             "before": None, "after": None, "note": note(c)} for c in left]
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
                "before": _asg_text(a) if a else None, "after": after, "note": note}

    # 분반 없이: 시간 비우기 / 강의실 못 씀
    if not cmd.section_id:
        if cmd.room:
            change = {"kind": "room_off", "room": cmd.room}
            what = f"{_j(cmd.room, '을')} 못 쓰면"
        else:
            change = {"kind": "free", "day": cmd.days[0], "start": cmd.start}
            what = f"{_j(cmd.days[0] + ' ' + cmd.start, '을')} 비우면"
        res = _run_what_if(tt, change)
        if not res["supported"]:
            return _result(res["note"] or "이 가정은 아직 계산할 수 없어요.")
        if not res["real"]:
            changed = [s for s in res["changed"] if s in by_id]
            rows = [row(s, "다시 배정 필요", "영향 받음") for s in changed]
            return _result(f"{what} 분반 {len(changed)}개가 자리를 옮겨야 해요. 그때 규칙 위반은 {res['violations']}건이에요. "
                           f"(미리 보기만 했고 시간표는 그대로예요.) {STUB_NOTE}", rows)
        if not res["changed"]:
            return _result(f"{what} 영향 받는 분반이 없어요. {res['note']}".strip())
        moved = {m["section_id"]: m for m in res["moved"]}
        rows = [row(s, moved[s]["after"] if s in moved else ("놓을 자리 없음" if s in res["unplaced"] else "그대로"),
                    "옮김" if s in moved else ("못 놓음" if s in res["unplaced"] else "영향 없음"))
                for s in res["changed"] if s in by_id]
        lines = [f"{what} 분반 {len(res['changed'])}개를 엔진이 다시 놓아 봤어요: 옮겨짐 {len(moved)}개, "
                 f"놓을 자리 없음 {len(res['unplaced'])}개, 새 규칙 위반 {res['violations']}건."]
        lines += _rule_lines(res, lambda s: section_title(store.get_section(s)) if store.get_section(s) else s)
        lines.append("(복사본에서 계산만 했고 시간표는 그대로예요.)")
        return _result(" ".join(lines), rows)

    sec = store.get_section(cmd.section_id)
    title = section_title(sec)
    if sec.shape == "MANUAL":
        return _result(f"{_j(title, '은')} 조교 직접 배정 분반이라 도우미가 옮기지 않아요. 시간표에서 직접 정해 주세요.")
    if as_move and store.stage == "FINAL":
        return _result("시간표가 이미 확정됐어요. 확정 뒤에는 옮길 수 없어요.")
    a = by_id.get(sec.id)
    if a is None:
        return _result(f"{_j(title, '은')} 시간표에 없어요.")
    blocks, ask = _new_blocks(a.blocks, cmd)
    if ask:
        return _result(ask)
    room = _pick_room(cmd, store, a)
    if room:
        blocks = [b.model_copy(update={"room": room}) for b in blocks]
    else:
        blocks = [b.model_copy(update={"room": b.room or a.room}) for b in blocks]
    if [dump(b) for b in blocks] == [dump(b.model_copy(update={"room": block_room(a, b)})) for b in a.blocks]:
        return _result(f"{_j(title, '은')} 이미 그 자리예요: {_asg_text(a)}.")
    why_not, chapel_note = _forbidden(blocks, sec, store.get_wish(sec.id), store.fixed_blocks)
    if why_not:   # 교수 불가 시간·채플·18:00 연강으로는 옮기지 않는다 (미리 보기도 하지 않음)
        return _result(f"{_j(title, '을')} {_j(_place_text(blocks), '으로')}는 옮기지 않아요. {why_not}")

    change = {"kind": "move", "section_id": sec.id, "day": blocks[0].day, "start": blocks[0].start,
              "room": room, "blocks": [dump(b) for b in blocks]}
    res = _run_what_if(tt, change)
    if not res["supported"]:
        return _result(res["note"] or "이 가정은 아직 계산할 수 없어요.")
    others = [s for s in res["changed"] if s != sec.id and s in by_id]
    rows = [row(sec.id, _place_text(blocks), "옮김")]
    rows += [row(s, "겹침 → 다시 배정 필요", "영향 받음") for s in others]

    lines = [f"{_j(title, '을')} {_j(_place_text(blocks), '으로')} 옮기면"]
    if res["real"]:
        name = lambda s: section_title(store.get_section(s)) if store.get_section(s) else s   # noqa: E731
        if res["feasible"]:
            lines.append("규칙 위반 없이 놓을 수 있어요.")
        else:
            lines.append(f"그대로는 놓을 수 없어요. 새 규칙 위반 {res['violations']}건.")
            lines += _rule_lines(res, name)
            opt = res.get("option")
            if opt:
                ms = opt["alternative"]["meetings"]
                where = " / ".join(f"{DAYS[m['day']]} {m['start']}~{m['end']} {m['room']}" for m in ms)
                lines.append(f"규칙을 지키며 그 시각에 놓는 안: {where}" +
                             (f" (같이 움직이는 수업 {len(opt['moves'])}개)" if opt["moves"] else "") + ".")
            else:
                lines.append("규칙을 지키며 그 시각에 놓는 안도 엔진이 찾지 못했어요.")
            if as_move and opt and not opt["moves"] and not res["violations"]:
                # 요청한 강의실만 그 시간에 차 있고, 엔진이 같은 요일·시각에 다른 강의실로 규칙을 지키는 안을 찾음
                # (다른 수업을 움직이지 않음) → 그 안으로 제안한다. 엔진 안은 apply_option 이 받는다
                from ..contracts import meetings_to_blocks, Meeting
                blocks, _ = meetings_to_blocks([Meeting(**m) for m in opt["alternative"]["meetings"]])
                rows = [row(sec.id, _place_text(blocks), "옮김 (엔진이 고른 강의실)")]
                lines.append("요청한 강의실 대신 이 안으로 제안해요.")
            elif as_move:   # 새 위반이 생기거나 다른 수업까지 움직여야 하는 안은 [적용]해도 거부되므로 제안을 만들지 않는다
                return _result(" ".join(lines), rows)
    else:
        lines.append(f"같이 바뀌어야 하는 다른 분반 {len(others)}개, 규칙 위반 {res['violations']}건이에요. {STUB_NOTE}")
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
        "alternative": alternative("A", blocks),   # 수업마다 강의실 (Meeting.room)
        "base": timetable_key(tt),
        "summary": f"{title}: {_asg_text(a)} → {_place_text(blocks)}",
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
