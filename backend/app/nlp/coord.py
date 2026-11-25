"""조율 NLP (백엔드 2): 조율 메시지 작성·검사, 교수 답장 해석, 조건 대조.

    write_message(inp, method)          → Message      교수에게 보낼 조율 글
    check_message(text, inp)            → list[str]    글에서 걸린 문제 (빈 목록 = 보내도 됨)
    parse_reply(text, choice, choices=..., method) → ReplyParse 답장 → 판정·고른 안(선호 순서·순서 밝힘)·조건
    match_conditions(parse, alts, round)   → Proposal   조교에게 보여 줄 처리안

method="keyword"는 비교 기준(규칙)이고, method="llm"은 언어 모델을 쓴다.
언어 모델이 실패하거나 결과가 검사를 통과하지 못하면 키워드 방식으로 대신 처리하고 fallback=True로 표시한다.
check_message와 match_conditions는 항상 코드(규칙)로만 한다. 배정을 정하는 건 언어 모델이 아니다.

키워드 규칙은 화면 시안 v4(docs/prototype)의 parseReply·msgText·msgChecks·check를 옮긴 것이다.
프롬프트 예시 문장은 평가 문장과 겹치지 않게 따로 쓴다 (평가 문장은 팀원·지인이 직접 쓴다).
"""
import re
from typing import Literal

from pydantic import BaseModel

from .coord_models import (DAYN, SLOTS, Alternative, Conditions, EndBefore, Message, MessageInput,
                           PickCheck, Proposal, ReplyParse)
from .llm import LLMUnavailable, generate_json, load_prompt

Method = Literal["keyword", "llm"]

# 말로 하는 시간대 → 되는 교시(시작 시각). '늦은 오후'를 '오후'보다 먼저 찾는다 (11/21 팀 결정)
# 18:00 시작(19:15 종료)은 저녁이다. 답장을 쓴 사람들이 18:00을 '저녁'이라고 불렀다 (11/22)
SLOT_WORDS = {
    "늦은 오후": ["16:30"],
    "오전": ["09:00", "10:30"],
    "점심": ["12:00"],
    "저녁": ["18:00", "19:30"],
    "오후": ["13:30", "15:00", "16:30"],
}
MAX_ROUND = 3
EARLY_END_MIN = 15   # 고른 안이 종료 조건보다 이만큼 이내로만 늦게 끝나면 교수 재량(몇 분 일찍 마침)으로 보고 조건에서 뺀다 (11/22)
FORBIDDEN = re.compile(r"연차|임용|우선순위|경력|꼭 표시")
# 교수 화면: A·B·C·기타 중 하나 이상 골라야 보낼 수 있고 여러 개 골라도 된다. 기타는 글을 쓴다 (11/25 #17)
CLOSING = ("가능한 안을 모두 골라 주시고, 모두 어려우시면 기타를 골라 가능한 시간을 적어 주세요. "
           "회신 기한은 1주이며, 기한 전에 한 번 더 알려 드립니다.")
CHOICES = ("A", "B", "C", "ETC", "KEEP")   # KEEP = '지금 자리 그대로' (희망 밖에라도 놓인 분반만 화면에 보임, 11/25)


# ---------------- 표시 ----------------
def _mins(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def alt_label(a: Alternative) -> str:
    """예: '월·수 16:30~17:45 · 정보관 305', '수 13:30~16:15 연강 · 정보관 210'"""
    ms = a.meetings
    times = {(m.start, m.end) for m in ms}
    if len(times) == 1:
        s, e = ms[0].start, ms[0].end
        when = f"{'·'.join(DAYN[m.day] for m in ms)} {s}~{e}"
        if len(ms) == 1 and _mins(e) - _mins(s) > 75:
            when += " 연강"
    else:   # 주 2회인데 요일마다 시각이 다른 경우
        when = " / ".join(f"{DAYN[m.day]} {m.start}~{m.end}" for m in ms)
    rooms = {m.room for m in ms}
    where = ms[0].room if len(rooms) == 1 else " / ".join(f"{DAYN[m.day]} {m.room}" for m in ms)
    return f"{when} · {where}"


def _slot_name(slots: list[str]) -> str:
    return next((n for n, w in SLOT_WORDS.items() if w == slots), None) or "·".join(slots) + " 시작 수업"


def cond_label(k: Conditions) -> str:
    """예: '화·목요일', '오후', '화 오전, 목 오후', '수요일 17:00 전 종료'"""
    a = []
    ds = k.day_slots
    groups: dict[tuple, list[int]] = {}
    for d, s in ds.items():
        groups.setdefault(tuple(s), []).append(d)
    if len(groups) == 1 and set(ds) == set(range(5)) and next(iter(groups)):
        a.append(_slot_name(list(next(iter(groups)))))          # 요일 상관없이 그 교시
    else:
        for s, days in groups.items():
            when = "·".join(DAYN[d] for d in days)
            a.append(f"{when} {_slot_name(list(s))}" if s else f"{when}요일")
    by_time: dict[str, list[int]] = {}       # 같은 시각은 요일을 묶는다 ("매일 15:00 전 종료", "월·수요일 17:00 전 종료")
    for eb in k.end_before:
        by_time.setdefault(eb.time, []).append(eb.day)
    for t, days in by_time.items():
        days = sorted(set(days))
        when = "매일" if days == list(range(5)) else f"{'·'.join(DAYN[d] for d in days)}요일"
        a.append(f"{when} {t} 전 종료")
    return ", ".join(a)


# ---------------- 조율 메시지 ----------------
# 메시지 = 인사·제목 줄(틀) + 상황 설명 문단(틀 또는 언어 모델) + 대안 목록(틀) + 마지막 문장(틀).
# 언어 모델은 설명 문단 하나만 쓴다. 사람 평가(11/23)에서 언어 모델이 제목 줄을 "…조율"로 끊거나,
# 입력에 없는 이유("다른 과목이 배정되어")·틀린 대안 설명을 덧붙인 것이 나와서 나머지는 틀로 고정했다.
def _compose(inp: MessageInput, body: list[str]) -> str:
    L = [f"{inp.professor} 교수님, 안녕하세요. 학과사무실입니다.",
         f"{inp.term} {inp.course} 분반 시간표 {inp.round}차 조율 안내드립니다.", ""]
    L += body + [""]
    L += [f"{a.key}  {alt_label(a)}" for a in inp.alternatives]
    if inp.current:   # 희망 밖에라도 놓인 분반: 지금 자리를 알리고 그대로 두는 길도 준다 (11/25)
        L += ["", f"지금은 {inp.current}에 배정되어 있습니다. 그대로 괜찮으시면 '지금 자리 그대로'를 골라 주세요."]
    L += ["", CLOSING]
    return "\n".join(L)


def _knows_blocker(inp: MessageInput) -> bool:
    """겹친 상대를 서버가 알려 줬는가. 모르면 '겹친다'고 단정하지 않는다
    (배정 엔진은 상대를 알려 주지 않고, 밀린 이유가 실습실 부족·학년 규칙일 수도 있다. 11/24 하윤 점검 문서)."""
    return bool(inp.blocker_prof and inp.blocker_course)


def _template_body(inp: MessageInput) -> list[str]:
    if inp.round == 1:
        if not _knows_blocker(inp):
            return [f"희망하신 시간({inp.wish})에 배정하지 못해 아래 대안을 드립니다."]
        other = f"{inp.blocker_prof} 교수님의 {inp.blocker_course} 분반과" if inp.reveal else "다른 강의와"
        return [f"희망하신 시간({inp.wish})이 {other} 겹칩니다."]
    if inp.prev_conditions and not inp.prev_conditions.is_empty():
        first = f"지난 회신에서 주신 조건({cond_label(inp.prev_conditions)})을 반영해 대안을 다시 드립니다."
    else:
        first = "지난 차수 이후 바뀐 시간표를 반영해 대안을 다시 드립니다."
    return [first, f"처음 희망하신 시간: {inp.wish}"]


def _template(inp: MessageInput) -> str:
    return _compose(inp, _template_body(inp))


class _MessageLLM(BaseModel):
    text: str      # 상황 설명 문단 하나


_TIME = re.compile(r"\d{1,2}:\d{2}")
_ALT_TALK = re.compile(r"(?<![A-Za-z])[ABC](?![A-Za-z])")
_REASON = re.compile(r"때문|인해|사정|공사|수리|배정되|배정이\s*어려|배정하기\s*어려|사용\s*중|중복")
_REASON_LATER = re.compile(r"겹")      # 2·3차나 상대를 모르는 1차는 처음 희망이 왜 안 됐는지 입력에 없다


def check_body(body: str, inp: MessageInput) -> list[str]:
    """언어 모델이 쓴 설명 문단 검사. 하나라도 걸리면 틀 문장으로 보낸다."""
    p = []
    if not body.strip():
        return ["설명 문단이 비었음"]
    if re.search(r"[(\[<]\s*상대|<<|>>", body):
        p.append("설명 문단에 자리표시가 남음")
    if inp.round == 1 and inp.reveal and _knows_blocker(inp):
        if f"{inp.blocker_prof} 교수" not in body or inp.blocker_course not in body:
            p.append("1차인데 겹친 상대 교수·강의 이름이 빠지거나 바뀜")
    plain = body
    for name in (inp.course, inp.blocker_course or ""):     # "C프로그래밍 01" 같은 과목 이름 속 글자는 빼고 본다
        if name:
            plain = plain.replace(name, "")
    if _ALT_TALK.search(plain):
        p.append("설명 문단에서 대안 A·B·C를 따로 설명함")
    allowed = set(_TIME.findall(inp.wish))
    if inp.prev_conditions:
        allowed |= set(_TIME.findall(cond_label(inp.prev_conditions)))
    extra = sorted(set(_TIME.findall(body)) - allowed)
    if extra:
        p.append(f"설명 문단에 입력에 없는 시각을 씀 ({', '.join(extra)})")
    m = _REASON.search(body) or (_REASON_LATER.search(body) if inp.round > 1 or not _knows_blocker(inp) else None)
    if m:
        p.append(f"입력에 없는 이유를 덧붙임 ('{m.group(0)}')")
    return p


def write_message(inp: MessageInput, method: Method = "keyword") -> Message:
    if method == "keyword":
        return Message(text=_template(inp), method="keyword")
    if inp.round == 1 and not _knows_blocker(inp):
        situation = ("1차 조율. 희망 시간에 배정하지 못해 대안을 보낸다. 왜 못 했는지, 어느 강의와 겹치는지는 모른다. "
                     "'겹친다'는 말이나 다른 이유를 쓰지 않는다.")
    elif inp.round == 1:
        situation = (f"1차 조율. 희망 시간이 {inp.blocker_prof} 교수님의 {inp.blocker_course} 분반과 겹친다. 상대 교수와 강의 이름을 그대로 적는다."
                     if inp.reveal
                     else "1차 조율. 희망 시간이 다른 강의와 겹친다. 상대 교수 이름과 강의 이름은 적지 않는다 (학과 설정).")
    elif inp.prev_conditions and not inp.prev_conditions.is_empty():
        situation = (f"{inp.round}차 조율. 지난 회신에서 받은 조건({cond_label(inp.prev_conditions)})을 반영한 대안을 다시 보낸다. "
                     "조건은 \"조건(…)을\"처럼 괄호 안에 글자 그대로 적는다. 처음 희망도 다시 적는다. 처음 희망이 왜 안 됐는지는 모른다.")
    else:
        situation = (f"{inp.round}차 조율. 지난 차수 이후 바뀐 시간표를 반영한 대안을 다시 보낸다. "
                     "처음 희망도 다시 적는다. 처음 희망이 왜 안 됐는지는 모른다.")
    prompt = (load_prompt("write_message")
              .replace("<<PROFESSOR>>", inp.professor).replace("<<TERM>>", inp.term)
              .replace("<<COURSE>>", inp.course).replace("<<ROUND>>", str(inp.round))
              .replace("<<WISH>>", inp.wish).replace("<<SITUATION>>", situation))
    try:
        body = " ".join(generate_json(prompt, _MessageLLM).text.split())   # 한 문단으로
    except LLMUnavailable as e:
        return Message(text=_template(inp), method="keyword", fallback=True, problems=[str(e)])
    text = _compose(inp, [body])
    problems = check_body(body, inp) + check_message(text, inp)
    if problems:
        return Message(text=_template(inp), method="keyword", fallback=True, problems=problems)
    return Message(text=text, method="llm")


def check_message(text: str, inp: MessageInput) -> list[str]:
    """보내기 전에 코드로 검사한다. 하나라도 걸리면 보내지 않는다."""
    p = []
    m = FORBIDDEN.search(text)
    if m:
        p.append(f"연차·우선순위 이유를 썼음 ('{m.group(0)}')")
    for h in inp.hidden:
        if h.strip() and h.strip() in text:
            p.append("상대 교수의 사정(기타 요청)을 썼음")
    if not inp.reveal and inp.blocker_prof and f"{inp.blocker_prof} 교수" in text:
        p.append("상대 교수 이름을 썼음 (학과 설정: 알리지 않음)")
    if inp.course not in text:
        p.append("과목·분반 이름이 빠짐")
    if inp.wish not in text:
        p.append("본인 희망 시간이 빠지거나 바뀜")
    if inp.current and inp.current not in text:
        p.append("지금 배정된 자리가 빠지거나 바뀜")
    if not inp.alternatives:
        p.append("대안이 없음")
    lines = text.splitlines()
    for a in inp.alternatives:
        lab = alt_label(a)
        if not any(lab in ln and ln.lstrip().startswith(a.key) for ln in lines):
            p.append(f"{a.key}안이 빠지거나 바뀜")
    return p


# ---------------- 답장 해석 ----------------
_PICK = re.compile(r"(?<![A-Za-z])([ABC])(?![A-Za-z])")
_ORD = re.compile(r"(첫|두|세)\s*번째")
_ALL_NO = re.compile(r"(셋\s*다|모두|전부|다)\s*(어렵|안\s?되|안\s?돼|불가|힘들)")
_NO = re.compile(r"(어렵|안\s?되|안\s?돼|불가|힘들)")
_END = re.compile(r"([월화수목금])요?일?[은는]?\s*(\d{1,2})시\s*(?:전|이전|까지)")
# 요일 글자: 앞이 한글이 아니거나(또는 다른 요일 글자), 뒤가 구분 기호·'요'·다른 요일 글자·끝
_DAY = re.compile(r"(?:(?<![가-힣])|(?<=[월화수목금]))([월화수목금])(?=[·\s,/요월화수목금]|$)")
_NOT_DAY = re.compile(r"(?<![가-힣])([월화수목금])(?:요일)?(?:만|은|는|이나|도)?\s*(?:아니면|빼고|제외|말고|안\s*[돼되]|어렵|곤란|불가)")


def _hour(h: int) -> int:
    return h + 12 if h < 8 else h      # "5시" = 17시


# 글로 선호 순서를 밝히는 말 ("C가 좋고 안 되면 B", "A가 제일", "B 먼저")
_ORDER_WORD = re.compile(r"안\s*되면|어려우면|힘들면|제일|가장|먼저|우선|1순위|차선|그다음|그 다음|다음으로")


_KEEP_WORD = re.compile(r"(지금|현재)[^.!?\n]{0,10}?(그대로|대로)\s*(괜찮|좋|두|해|유지|가|할게|하겠|부탁)")


def _buttons(choice: str | None, choices: list[str] | None) -> tuple[list[str], bool, bool]:
    """화면에서 누른 값 → (누른 안 A·B·C 목록, A·B·C를 하나도 안 고름, '지금 자리 그대로'를 누름).
    choices = 새 화면(#17): A·B·C·ETC(기타)·KEEP(지금 자리 그대로) 중 하나 이상, 여러 개 가능. 기타만 누르면 A·B·C는 안 고른 것.
    choice = 예전 화면: 'A'/'B'/'C' 하나, 'none' = 모두 어려움, None = 안 누름. choices가 있으면 choices를 쓴다."""
    if choices:
        bad = [c for c in choices if c not in CHOICES]
        if bad:
            raise ValueError(f"누를 수 있는 값은 {CHOICES}: {bad}")
        keep = "KEEP" in choices
        btn = [c for c in dict.fromkeys(choices) if c in ("A", "B", "C")]
        return btn, not btn and not keep, keep
    if choice in ("A", "B", "C"):
        return [choice], False, False
    return [], choice == "none", False


def _order_picks(btn: list[str], text_picks: list[str], ordered: bool) -> list[str]:
    """버튼과 글에서 고른 안을 합친다. 버튼이 여럿이고 글로 순서를 밝혔으면 글 순서, 아니면 버튼이 앞 (예전 규칙)."""
    if ordered and len(btn) != 1:
        return list(dict.fromkeys([p for p in text_picks] + btn))
    return list(dict.fromkeys(btn + text_picks))


def _keyword_reply(text: str, btn: list[str], none: bool, keep: bool = False, can_keep: bool = False) -> ReplyParse:
    t = text or ""
    text_picks = list(dict.fromkeys(_PICK.findall(t) + [{"첫": "A", "두": "B", "세": "C"}[m] for m in _ORD.findall(t)]))
    keep = keep or (can_keep and not btn and not text_picks and bool(_KEEP_WORD.search(t)))
    if keep:   # 지금 자리 그대로 (버튼 또는 "지금 그대로 괜찮아요") → 처리안 keep. 고른 안은 참고로만 남긴다
        return ReplyParse(kind="수용", picks=list(dict.fromkeys(btn + text_picks)), keep=True, method="keyword")
    all_no = none or bool(_ALL_NO.search(t))
    ordered = len(set(text_picks) | set(btn)) >= 2 and bool(_ORDER_WORD.search(t))
    picks = [] if all_no else _order_picks(btn, text_picks, ordered)
    ordered = ordered and len(picks) >= 2
    k = Conditions()
    for d, h in _END.findall(t):
        k.end_before.append(EndBefore(day=DAYN.index(d), time=f"{_hour(int(h)):02d}:00"))
    if not picks:
        no_days = {DAYN.index(d) for d in _NOT_DAY.findall(t)}      # "목요일만 아니면" = 목 빼고 다 됨
        days = {DAYN.index(d) for d in _DAY.findall(t)} - no_days
        days = sorted(days or (set(range(5)) - no_days if no_days else set()))
        slots = next((list(w) for n, w in SLOT_WORDS.items() if n in t), [])
        # 키워드 규칙은 요일마다 다른 교시를 못 가린다 (비교 기준): 말한 요일 모두에 같은 교시
        k.day_slots = {d: slots for d in (days or (range(5) if slots else []))}
    if picks:
        kind = "조건부" if not k.is_empty() else "수용"
    else:
        kind = "거절" if all_no or _NO.search(t) else "확인 필요"
    return ReplyParse(kind=kind, picks=picks, ordered=ordered, conditions=k, method="keyword")


class _EndBeforeLLM(BaseModel):
    day: int
    time: str


class _DaySlotsLLM(BaseModel):
    day: int
    slots: list[str]       # 빈 목록 = 그 요일은 아무 교시나


class _ReplyLLM(BaseModel):
    kind: Literal["수용", "조건부", "거절", "확인 필요"]
    picks: list[Literal["A", "B", "C"]]
    ordered: bool = False  # 둘 이상 고르면서 어느 안을 더 원하는지 순서를 밝혔는가
    keep: bool = False     # 지금 배정된 자리를 그대로 원하는가
    day_slots: list[_DaySlotsLLM] = []
    end_before: list[_EndBeforeLLM] = []
    rooms: list[str] = []  # 고른 안을 이 강의실에서 해 달라는 요청 (번호). 이미 그 방인지는 코드가 대안과 대조한다
    note: str = ""        # 그 밖에 조교가 확인할 요청 (장비·정원·빈 시간·다른 교시로 조정 희망). 조교에게 그대로 보여 준다


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ROOM_NO = re.compile(r"\d{3,5}")
_ROOM_HINT = re.compile(r"강의실|호실|계단식|\d{3,5}")   # 처리안 문구에 '도우미로 강의실 바꾸기' 안내를 붙일지


def _room_note(rooms: list[str], alt: Alternative | None, note: str) -> str:
    """강의실 요청을 고른 안과 대조한다. 이미 그 방이면 할 일이 없으니 요청을 지우고, 아니면 note에 남긴다.
    충족 여부는 대안에 적힌 강의실 번호로만 판단한다 (계단식·장비·정원은 알 수 없어 note로 둔다)."""
    want = {n for x in rooms for n in _ROOM_NO.findall(x)}
    if not want or alt is None:
        return note
    if all(set(_ROOM_NO.findall(m.room)) & want for m in alt.meetings):
        return "" if any(n in note for n in want) else note   # 모델이 note에도 같은 방을 적었으면 같이 지운다
    if any(n in note for n in want):
        return note
    return (note + " / " if note else "") + f"강의실 {'·'.join(sorted(want))} 요청"


def _from_llm(r: _ReplyLLM, btn: list[str], none: bool, alts: list[Alternative], text: str = "",
              keep: bool = False, can_keep: bool = False) -> ReplyParse:
    """언어 모델 답을 검사하고 ReplyParse로 바꾼다. 모양이 이상하면 ValueError.
    btn = 화면에서 누른 A·B·C, none = A·B·C를 하나도 안 고름 (기타만 또는 예전 '모두 어려움'),
    keep = '지금 자리 그대로'를 누름, can_keep = 지금 자리가 있는 분반이라 글의 "지금 그대로"도 받을 수 있음."""
    keys = [a.key for a in alts]
    text_picks = [p for p in dict.fromkeys(r.picks) if not keys or p in keys]
    if keep or (can_keep and r.keep and not btn and not text_picks):
        note = r.note.strip()[:100]
        return ReplyParse(kind="조건부" if note else "수용", picks=list(dict.fromkeys(btn + text_picks)), keep=True,
                          note=note, method="llm")
    picks = [] if none else _order_picks(btn, text_picks, r.ordered)
    ordered = r.ordered and len(picks) >= 2
    day_slots: dict[int, list[str]] = {}
    for e in r.day_slots:
        if not 0 <= e.day <= 4 or any(x not in SLOTS for x in e.slots):
            raise ValueError("요일·교시 형식")
        if e.day in day_slots and (not day_slots[e.day] or not e.slots):
            day_slots[e.day] = []                         # 같은 요일이 두 번 나오고 한쪽이 '아무 교시나'
        else:
            day_slots[e.day] = sorted(set(day_slots.get(e.day, [])) | set(e.slots), key=SLOTS.index)
    if day_slots and not (_DAY.search(text) or "평일" in text):   # '화목'·'수금'처럼 붙여 쓴 요일도 요일로 본다
        # 답장에 요일이 없는데 요일을 골라 넣었으면 지어낸 것으로 보고, 교시만 다섯 요일에 둔다
        slots = sorted({s for v in day_slots.values() for s in v}, key=SLOTS.index)
        day_slots = {d: slots for d in range(5)} if slots else {}
    ebs = []
    for e in r.end_before:
        if not (0 <= e.day <= 4 and _HHMM.match(e.time)):
            raise ValueError("종료 조건 형식")
        ebs.append(EndBefore(day=e.day, time=e.time))
    first = next((a for a in alts if picks and a.key == picks[0]), None)
    if first:   # "17:45 종료인데 17:30에 끝낼 수 있으면" → 교수님이 수업 안에서 정할 일. 조건으로 받으면 고른 안이 탈락한다
        ebs = [e for e in ebs if not any(m.day == e.day and 0 < _mins(m.end) - _mins(e.time) <= EARLY_END_MIN
                                         for m in first.meetings)]
    k = Conditions(day_slots=day_slots, end_before=ebs)
    note = _room_note(r.rooms, first, r.note.strip())[:100]
    kind = r.kind
    if btn and kind == "확인 필요":
        # 화면 버튼으로 안을 골랐으면 그 안을 받아들인 것 (가이드 ①). 글이 짧거나 애매해도 버튼을 따른다
        kind = "조건부" if not k.is_empty() or note else "수용"
    elif kind in ("수용", "조건부"):
        kind = "확인 필요" if not picks else ("조건부" if not k.is_empty() or note else "수용")
    elif picks:           # 거절인데 안을 골랐다고 하면 모순 (버튼 A + "사실 다 안 돼요" 등)
        kind = "확인 필요"
    if none and kind in ("수용", "조건부", "확인 필요"):
        kind = "거절"
    return ReplyParse(kind=kind, picks=picks, ordered=ordered, conditions=k, note=note, method="llm")


def _choice_text(btn: list[str], none: bool, choices: list[str] | None) -> str:
    if choices:
        etc = "기타(글로 적음)" if "ETC" in choices else ""
        keep = "지금 자리 그대로" if "KEEP" in choices else ""
        abc = ", ".join(f"{c}안" for c in btn)
        if not btn:
            return ", ".join(x for x in (keep, etc) if x) + " — A·B·C는 고르지 않음"
        return (", ".join(x for x in (abc, keep, etc) if x)
                + (" (여러 개 누름, 누른 순서는 선호 순서가 아님)" if len(btn) > 1 else ""))
    if none:
        return "모두 어려움"
    return f"{btn[0]}안" if btn else "누르지 않음"


def parse_reply(text: str, choice: str | None = None, *, choices: list[str] | None = None,
                alternatives: list[Alternative] | None = None, message: str = "",
                method: Method = "keyword", can_keep: bool = False) -> ReplyParse:
    """교수 답장 → 판정·고른 안·조건.
    choices = 새 화면(#17)에서 누른 값: 'A'·'B'·'C'·'ETC'(기타)·'KEEP'(지금 자리 그대로) 중 하나 이상, 여러 개 가능.
      기타만 누르면 A·B·C는 안 고른 것.
    choice = 예전 화면 값 ('A'/'B'/'C', 'none' = 모두 어려움, None = 안 누름). choices가 있으면 choices를 쓴다.
    can_keep = 이 분반에 지금 배정된 자리가 있음 (희망 밖에라도 놓인 분반). True일 때만 글의 "지금 그대로 괜찮아요"를
      '지금 자리 그대로'로 읽는다. 자리가 없는 분반(못 놓음)은 False (11/25)."""
    btn, none, keep = _buttons(choice, choices)
    can_keep = can_keep or keep
    if method == "keyword":
        return _keyword_reply(text, btn, none, keep, can_keep)
    alts = alternatives or []
    prompt = (load_prompt("parse_reply")
              .replace("<<MESSAGE>>", message or "(없음)")
              .replace("<<ALTERNATIVES>>", "\n".join(f"{a.key}  {alt_label(a)}" for a in alts) or "(없음)")
              .replace("<<CHOICE>>", _choice_text(btn, none, choices))
              .replace("<<REPLY>>", text or "(빈 답장)"))
    try:
        return _from_llm(generate_json(prompt, _ReplyLLM), btn, none, alts, text, keep, can_keep)
    except (LLMUnavailable, ValueError) as e:
        reason = _fallback_reason(e)
        r = _keyword_reply(text, btn, none, keep, can_keep)
        r.fallback, r.fallback_reason = True, reason
        # 키워드 규칙은 거절·보류를 수용으로 잘못 읽을 때가 있다 (평가의 위험 오류). 모델이 막혀 넘어왔는데
        # 글만 보고 수용·조건부가 나오면 확인 필요로 낮추고 추정은 note에 남긴다. 화면 버튼(A/B/C)을 눌렀으면 그대로 둔다 (11/22)
        if r.kind in ("수용", "조건부") and not btn and not keep:
            r = r.model_copy(update={"kind": "확인 필요", "picks": [], "ordered": False, "conditions": Conditions(),
                                     "note": f"AI 해석 실패({reason}). 키워드 추정: {''.join(r.picks)} {r.kind}"})
        return r


def _fallback_reason(e: Exception) -> str:
    s = f"{type(e).__name__} {e}"
    for code, name in (("429", "429 요청 제한"), ("503", "503 과부하"), ("500", "500 서버 오류")):
        if code in s:
            return name
    if "API_KEY" in s or "키 없" in s:
        return "키 없음"
    if "timeout" in s.lower():
        return "시간 초과"
    if isinstance(e, ValueError) or "형식" in s:
        return "형식 오류"
    return "호출 실패"


# ---------------- 조건 대조 ----------------
def _fits(a: Alternative, k: Conditions) -> tuple[bool, str]:
    for e in k.end_before:
        for m in a.meetings:
            if m.day == e.day and _mins(m.end) > _mins(e.time):
                return False, f"{DAYN[m.day]}요일 {m.end} 종료 → {e.time} 전 종료 조건과 어긋남"
    ds = k.day_slots
    if ds:
        days = [m.day for m in a.meetings]
        if len(ds) >= 2:       # 그 요일들 안에서만
            ok, checked = all(d in ds for d in days), a.meetings
        else:                  # 요일 하나: 그 요일이 들어가면 되고, 다른 하루는 자유
            (d0,) = ds
            ok, checked = d0 in days, [m for m in a.meetings if m.day == d0]
        if not ok:
            return False, f"{'·'.join(DAYN[d] for d in days)}요일 → 가능한 때({cond_label(Conditions(day_slots=ds))})와 어긋남"
        for m in checked:
            allowed = ds[m.day]
            used = [s for s in SLOTS if _mins(m.start) <= _mins(s) < _mins(m.end)]   # 연강은 두 칸
            if allowed and any(s not in allowed for s in used):
                return False, (f"{DAYN[m.day]} {m.start}~{m.end} → {DAYN[m.day]}요일 가능 교시"
                               f"({_slot_name(allowed)})와 어긋남")
    return True, "조건과 맞음" if not k.is_empty() else "고른 안"


def match_conditions(parse: ReplyParse, alternatives: list[Alternative], round: int,
                     unavailable: list[str] = ()) -> Proposal:
    """unavailable = 그사이 다른 강의가 들어가서 못 쓰는 안 (배정 엔진이 알려 준다).
    여러 안을 골랐으면 조건에 맞는 첫 안을 처리안으로 낸다. 서버가 배정 엔진 pick_best를 쓰면
    picks 순서와 parse.ordered(respect_order)를 넘겨 엔진이 최종으로 고른다 (11/25 #18)."""
    k = parse.conditions
    req = f" 교수님 요청: {parse.note}" if parse.note and not parse.fallback else ""
    if parse.keep:   # '지금 자리 그대로' → 바꿀 것 없음. 조교가 [현재대로 유지]로 끝낸다 (11/25)
        return Proposal(action="keep", text="교수님이 지금 자리를 그대로 원합니다. [현재대로 유지]를 누르면 끝납니다." + req)
    if parse.kind == "확인 필요":
        return Proposal(action="decide", text="답장을 확실히 읽지 못했습니다. [수정]으로 정하거나 [따로 연락]해 주세요."
                                              + (f" ({parse.note})" if parse.note else ""))
    if not parse.picks and k.is_empty():
        # 조건 없이 거절했거나 기타에 시간 얘기 없이 요청만 적음 → 다음 차수에 넘길 조건이 없다.
        # 시스템이 조건을 지어내지 않고 조교가 교수와 직접 정한다 (11/25 #17 [따로 연락])
        return Proposal(action="decide", text="되는 시간을 말하지 않고 거절했습니다. 교수님과 [따로 연락]해 정해 주세요." + req)
    if parse.picks:
        checks = []
        for key in parse.picks:
            a = next((x for x in alternatives if x.key == key), None)
            if not a:
                checks.append(PickCheck(key=key, ok=False, why="없는 안"))
                continue
            ok, why = _fits(a, k)
            if ok and key in unavailable:
                ok, why = False, "그사이 다른 강의가 들어감"
            checks.append(PickCheck(key=key, ok=ok, why=why))
        g = next((c for c in checks if c.ok), None)
        if g:
            a = next(x for x in alternatives if x.key == g.key)
            text = f"{g.key}안({alt_label(a)})으로 옮길까요?" + (f" 교수님 요청: {parse.note}" if parse.note else "")
            if parse.note and _ROOM_HINT.search(parse.note):
                # [수정]은 A·B·C 중에서만 고르므로 "같은 시간, 다른 방"은 AI 도우미로 바꾼다 (11/24 하윤 점검 문서)
                text += " (강의실만 바꾸려면 [확인] 뒤 AI 도우미에게 \"과목 건물 호수로\"처럼 말하면 됩니다)"
            return Proposal(action="move", key=g.key, conditions=k, checks=checks, text=text)
        if round < MAX_ROUND and not k.is_empty():
            return Proposal(action="next", conditions=k, checks=checks,
                            text="고른 안이 모두 조건과 어긋납니다. 조건을 넣어 다음 차수 대안을 만들까요?" + req)
        if round < MAX_ROUND:   # 조건 없이 고른 안이 모두 못 쓰게 됨 (그사이 다른 강의가 들어감 등)
            return Proposal(action="decide", checks=checks,
                            text="고른 안을 지금은 쓸 수 없습니다. [수정]으로 정하거나 교수님과 [따로 연락]해 주세요." + req)
        return Proposal(action="decide", conditions=k, checks=checks,
                        text=f"{MAX_ROUND}차라 더 묻지 않습니다. [수정]·[현재대로 유지]·[따로 연락] 중에서 정해 주세요." + req)
    if round >= MAX_ROUND:
        return Proposal(action="decide", conditions=k,
                        text=f"{MAX_ROUND}차라 더 묻지 않습니다. [수정]·[현재대로 유지]·[따로 연락] 중에서 정해 주세요." + req)
    return Proposal(action="next", conditions=k,
                    text=f"새 조건({cond_label(k)})으로 다음 차수 대안을 만들까요?" + req)
