"""SSU:room FastAPI 서버 (백엔드 ③).

실행 (저장소 루트에서):
    uvicorn backend.app.main:app --reload --port 8000

배정·조율 함수는 engine.py에서만 가져온다 (진짜가 없으면 가짜).
상태: 기본(메모리 모드)은 store.py(메모리). SSUROOM_ENGINE=solver 면 DB 모드: 하윤 DB가 기준이고(dbmode.py),
바꾸는 요청 뒤마다 DB 내용으로 store를 다시 채운다. 단계: COLLECT → DRAFT → ROUND(1~3) → FINAL.
조교가 [확인]·[수정]·[현재대로 유지]를 누르기 전에는 어떤 처리안도 시간표에 반영하지 않는다.
"""

import logging
import os
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import dbmode, engine, export
from .contracts import (
    Alternative, Key, Timetable, Violation, Wish, fix_conditions, dump, meetings_to_blocks, parse, set_place,
)
from .nlp import assistant
from .store import MAX_ROUND, store

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

log = logging.getLogger("uvicorn.error")

# 화면(Vite) 주소 허용 (CORS). 기본은 이 컴퓨터의 화면만.
DEFAULT_ORIGINS = ["http://localhost:5173"]
# 사설망(192.168.x.x · 10.x.x.x · 172.16~31.x.x)의 5173 포트만 (컴퓨터 2대 시연: 다른 컴퓨터가 A의IP:5173 으로 들어옴)
LAN_ORIGIN_REGEX = (r"http://(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
                    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):5173")


def lan_enabled() -> bool:
    """SSUROOM_LAN=1(true·yes·on)이면 같은 사설망의 다른 컴퓨터 화면도 허용."""
    return (os.environ.get("SSUROOM_LAN") or "").strip().lower() in ("1", "true", "yes", "on")


def cors_settings() -> dict:
    """CORSMiddleware 설정. 환경 변수가 없으면 지금과 같다(http://localhost:5173 만).
    - SSUROOM_LAN=1: 사설망 주소의 5173 포트 추가 (allow_origin_regex). 다른 주소·포트는 막힘
    - SSUROOM_CORS="http://주소:포트,http://주소2:포트": 그 목록 추가 (사설망이 아닌 주소일 때)
    "*"(모두 허용)는 쓰지 않는다."""
    extra = [o.strip().rstrip("/") for o in (os.environ.get("SSUROOM_CORS") or "").split(",")
             if o.strip() and o.strip() != "*"]
    out = dict(allow_origins=list(dict.fromkeys(DEFAULT_ORIGINS + extra)), allow_methods=["*"], allow_headers=["*"])
    if lan_enabled():
        out["allow_origin_regex"] = LAN_ORIGIN_REGEX
    return out


app = FastAPI(title="SSU:room", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    **cors_settings(),
)

MANUAL_MSG = "조교 직접 배정 분반입니다. 자동 배정·조율 대상이 아닙니다."


@app.on_event("startup")
def _log_sources() -> None:
    src = engine.sources()
    real = [n for n, s in src.items() if s != "stub"]
    log.info("SSU:room 데이터 묶음: %s", os.environ.get("DATA_SET", "real"))
    log.info("engine 함수: 진짜 %d개, 가짜 %d개", len(real), len(src) - len(real))
    for name, s in src.items():
        log.info("  %-18s %s", name, s)
    engine_warnings = engine.load_warnings()
    if engine_warnings:
        bar = "!" * 72
        log.warning(bar)
        log.warning("!! 진짜 모듈이 있는데 불러오지 못해 가짜 함수를 쓰고 있습니다 (%d개)", len(engine_warnings))
        for w in engine_warnings:
            log.warning("!! %s", w)
        log.warning(bar)
    for w in store.load_warnings:
        log.warning("데이터 읽기: %s", w)
    db = dbmode.active()
    if db is not None:
        db.sync(store)
        log.info("DB 모드: 하윤 DB에 상태를 저장합니다 (분반 %d개)", len(store.sections))


# ---------- 요청 모양 ----------

class MessageIn(BaseModel):
    method: Optional[Literal["keyword", "llm"]] = None   # None = 서버 기본(SSUROOM_NLP)


Choice = Literal["A", "B", "C", "ETC", "KEEP"]


class ReplyIn(BaseModel):
    text: str = ""
    # 교수 답장 화면에서 누른 값 (하나 이상, 여러 개 가능). ETC = 기타(글 필수), KEEP = 지금 자리 그대로
    choices: Optional[List[Choice]] = None
    choice: Optional[Literal["A", "B", "C", "none"]] = None   # 예전 화면 값 (choices가 있으면 choices를 쓴다)
    method: Optional[Literal["keyword", "llm"]] = None   # None = 서버 기본(SSUROOM_NLP)


class DecideIn(BaseModel):
    # confirm [확인] / edit [수정] / keep [현재대로 유지] / offline [따로 연락]
    action: Literal["confirm", "edit", "keep", "offline"]
    reason: Optional[str] = None
    choice: Optional[Key] = None   # edit일 때 조교가 고른 안


class MeetingIn(BaseModel):
    day: int                        # 0=월 … 4=금
    start: str
    end: str
    room: str


class ManualIn(BaseModel):
    """[따로 연락] 뒤 조교가 교수와 정한 자리. 그 분반은 고정된다."""
    meetings: List[MeetingIn]
    reason: Optional[str] = None


class AssistantIn(BaseModel):
    text: str
    history: List[dict] = []         # [{"role": "user"|"assistant", "text": "...", "section_id": 선택}]
    method: Optional[Literal["keyword", "llm"]] = None   # None = 서버 기본(SSUROOM_NLP)


class SettingsIn(BaseModel):
    reveal_opponent: Optional[bool] = None   # 조율 메시지에 상대 교수 이름 알리기


class ApplyIn(BaseModel):
    proposal_id: str
    reason: Optional[str] = None


class RequestConfirmIn(BaseModel):
    memo: Optional[str] = None      # 조교 메모 (예: "실습 조교 배정 완료")


class HoldIn(BaseModel):
    send: bool = True               # True = [보내기] (OPEN), False = 보내지 않음 (KEPT)


class PairIn(BaseModel):
    """분반 연강·교차 (같은 교수가 한 과목의 분반을 둘 이상 맡을 때, 과목 단위로 한 번)."""
    section_id: str                 # 그 과목의 분반 하나 (교수 확인용)
    mode: Literal["NONE", "BACK_TO_BACK", "CROSS"]
    order: Optional[List[str]] = None   # 붙일 분반 id, 교수가 적은 순서. 없으면 맡은 분반 전부


class RoundIn(BaseModel):
    method: Optional[Literal["keyword", "llm"]] = None   # DB 모드에서 자동으로 보내는 조율 메시지 방식. None = SSUROOM_NLP


# ---------- 도우미 ----------

def nlp_default() -> str:
    """서버 기본 해석 방식: 환경 변수 SSUROOM_NLP (keyword | llm). 없거나 다른 값이면 keyword."""
    v = (os.environ.get("SSUROOM_NLP") or "").strip().lower()
    return v if v in ("keyword", "llm") else "keyword"


def _nlp(method: Optional[str]) -> str:
    """요청에 method 가 오면 그것, 없으면(None) 서버 기본(SSUROOM_NLP). 조율 메시지·답장 해석·자동 메시지·AI 도우미 공통.
    llm 이 막히면(429·503·키 없음) 각 함수가 키워드로 대신 처리하고 응답에 method·fallback 을 남긴다."""
    return method if method in ("keyword", "llm") else nlp_default()


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


def _db():
    """DB 모드면 DBMode (SSUROOM_ENGINE=solver), 아니면 None."""
    return dbmode.active()


def _db_call(fn, *args, **kwargs):
    """DB 모드 함수 호출. 하윤 함수의 거부(ValueError)와 서버 거부(DBModeError)는 409, 끝나면 store를 DB로 다시 채운다."""
    db = _db()
    try:
        return fn(*args, **kwargs)
    except (ValueError, dbmode.DBModeError) as e:
        raise _conflict(str(e))
    finally:
        db.sync(store)


def _section_or_404(sid: str):
    sec = store.get_section(sid)
    if sec is None:
        raise HTTPException(status_code=404, detail=f"분반이 없습니다: {sid}")
    return sec


def _normalize(tt: Timetable) -> Timetable:
    """MANUAL 분반은 상태를 MANUAL로 고정하고, 빠졌으면 원래 자리로 다시 넣는다."""
    seen = set()
    for a in tt.assignments:
        seen.add(a.section_id)
        m = store.manual_assignments.get(a.section_id)
        if m is not None:
            a.status, a.reason = "MANUAL", m.reason
    for sid, m in store.manual_assignments.items():
        if sid not in seen:
            tt.assignments.append(m)
    return tt


def _coord_out(item: dict) -> dict:
    sec = store.get_section(item["section_id"])
    # 조건(prev/next_conditions, 처리안·답장 해석 안)은 요일별 교시 모양으로 내보낸다
    out = fix_conditions(jsonable_encoder(item))
    out["name"] = sec.name if sec else None
    out["professor"] = sec.professor if sec else None
    return out


def _with_alternative(tt: Timetable, sid: str, alt: Alternative) -> Timetable:
    """그 분반만 대안 자리로 바꾼 사본 (다른 분반은 그대로). 반영하지 않는다."""
    out = parse(Timetable, dump(tt))
    blocks, _ = meetings_to_blocks(alt.meetings)
    for a in out.assignments:
        if a.section_id == sid:
            set_place(a, blocks)   # 수업마다 강의실 유지
    return out


def _violations(tt: Optional[Timetable] = None) -> list:
    """하드 규칙 위반 목록 (Violation 모양: rule, section_ids, detail).
    DB 모드: 하윤 solver_core.check_timetable (지금 시간표 버전). 메모리 모드: 가짜 check_rules."""
    db = _db()
    if db is not None:
        return [Violation(**v) for v in db.violation_list()]
    return engine.check_rules(tt if tt is not None else store.timetable)


def _violations_after(sid: str, alt: Alternative) -> list:
    """그 분반을 대안 자리로 옮긴 '뒤' 시간표의 위반. DB 모드는 메모리 복사본에서 하윤 check_timetable
    (진짜 DB는 그대로), 메모리 모드는 가짜 check_rules."""
    db = _db()
    if db is not None:
        return [Violation(**v) for v in db.violations_after(sid, alt)]
    return engine.check_rules(_with_alternative(store.timetable, sid, alt))


def _unavailable(sid: str, alternatives) -> list:
    """그사이 다른 강의가 들어가서 못 쓰게 된 대안 키 (match_conditions의 unavailable).
    현재 시간표에 그 안을 넣어 보고, 이 분반이 낀 규칙 위반이 생기면 못 쓰는 안으로 본다."""
    if store.timetable is None:
        return []
    out = []
    for alt in alternatives:
        vs = _violations_after(sid, alt)
        if any(sid in v.section_ids for v in vs):
            out.append(alt.key)
    return out


def _coord_target(sid: str) -> dict:
    sec = _section_or_404(sid)
    if sec.shape == "MANUAL":
        raise _conflict(MANUAL_MSG)
    if store.stage != "ROUND":
        raise _conflict(f"조율은 차수 진행 중(ROUND)에만 할 수 있습니다. 지금 단계: {store.stage}")
    item = store.get_coord(sid)
    if item is None:
        raise _conflict(f"조율 대상 분반이 아닙니다: {sid}")
    if item["state"] in ("RESOLVED", "KEPT"):
        raise _conflict(f"이번 차수({store.round_no}차)에 이미 결정한 분반입니다.")
    return item


def _check_reply(body: ReplyIn, can_keep: bool) -> None:
    """답장 버튼·글 검사 (DB add_reply와 같은 규칙). 틀리면 422."""
    if body.choices is not None:
        picked = list(dict.fromkeys(body.choices))
        if not picked:
            raise HTTPException(status_code=422, detail="A·B·C·기타·지금 자리 그대로 중 하나 이상을 골라야 합니다.")
        if "ETC" in picked and not body.text.strip():
            raise HTTPException(status_code=422, detail="기타를 골랐으면 기타 내용을 적어야 합니다.")
        if "KEEP" in picked and set(picked) & {"A", "B", "C"}:
            raise HTTPException(status_code=422,
                                detail="'지금 자리 그대로'는 A·B·C와 같이 고를 수 없습니다 (혼자 또는 기타와만).")
        if "KEEP" in picked and not can_keep:
            raise HTTPException(status_code=422, detail="'지금 자리 그대로'는 이미 자리가 있는 분반에서만 고를 수 있습니다.")
    elif not body.text.strip() and body.choice is None:
        raise HTTPException(status_code=422, detail="누른 값(choices)이나 답장 글(text)이 있어야 합니다.")


# ---------- 상태 ----------

@app.get("/health")
def health():
    return {
        "ok": True,
        "data_set": os.environ.get("DATA_SET", "real"),
        "stage": store.stage,
        "round_no": store.round_no,
        "engine": engine.sources(),
        "load_warnings": engine.load_warnings() + store.load_warnings,
        "nlp": nlp_default(),                                   # 서버 기본 해석 방식 (요청에 method 가 없을 때)
        "gemini_key": bool(os.environ.get("GEMINI_API_KEY")),   # 키가 있는지만 (값은 내보내지 않는다)
        "lan": lan_enabled(),                                   # 같은 사설망의 다른 컴퓨터 화면 허용 (SSUROOM_LAN)
    }


# ---------- 학과 설정 ----------

@app.get("/settings")
def get_settings():
    return store.get_settings()


@app.post("/settings")
def post_settings(body: SettingsIn):
    """보낸 칸만 바꾼다. 모든 단계에서 바꿀 수 있고, 다음에 쓰는 조율 메시지부터 적용된다."""
    fields = {k: v for k, v in dump(body).items() if v is not None}
    return store.update_settings(**fields)


# ---------- 기본 자료 ----------

@app.get("/sections")
def get_sections():
    return store.list_sections()


@app.get("/rooms")
def get_rooms():
    return store.list_rooms()


@app.get("/wishes")
def get_wishes():
    """희망 + 분반 연강·교차(pairs). pairs 한 줄은 POST /wishes/pair 에 보내는 모양과 같다 (section_id, mode, order)."""
    if _db():
        pairs = _db().pair_requests()
    else:
        pairs = [{"section_id": sid, **v} for sid, v in getattr(store, "pairs", {}).items()]
    # 희망마다 분반 수강 인원(enrollment)을 같이 보인다. 따로 안 넣은 분반은 분반 정보(/sections)의 인원
    wishes = [w.model_copy(update={"enrollment": w.enrollment if w.enrollment is not None else
                                   (store.get_section(w.section_id).enrollment if store.get_section(w.section_id) else None)})
              for w in store.list_wishes()]
    # 기타 글의 확인 상태 (PENDING | CONFIRMED | null = 기타 글 없음)
    status = {r["section_id"]: r["status"] for r in _requests() if r["source"] == "wish"}
    out = [dict(dump(w), note_status=status.get(w.section_id)) for w in wishes]
    return {"wishes": out, "professors": store.professors, "pairs": pairs}


def _requests(status: Optional[str] = None) -> List[dict]:
    return _db().requests(status) if _db() else store.list_requests(status)


# ---------- 기타 요청 (조교 확인) ----------

@app.get("/requests")
def get_requests(status: Optional[Literal["PENDING", "CONFIRMED"]] = None):
    """교수가 '기타'에 쓴 요청 (희망 입력 = wish, 조율 답장 기타의 시간표 밖 요청 = reply). 미확인 먼저.
    조교가 읽고 [확인함]을 누른다. 배정 엔진은 읽지 않는다."""
    return _requests(status)


@app.post("/requests/{request_id}/confirm")
def post_request_confirm(request_id: int, body: Optional[RequestConfirmIn] = None):
    """[확인함]. 이미 확인한 요청은 메모만 바꾼다. 없는 id 는 404."""
    memo = body.memo if body else None
    if _db():
        try:
            return _db_call(_db().confirm_request, request_id, memo)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"기타 요청이 없습니다: {request_id}")
    rec = store.confirm_request(request_id, memo)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"기타 요청이 없습니다: {request_id}")
    return rec


@app.post("/wishes")
def post_wish(wish: Wish):
    # 형식 검사(칸 이름, 값 종류 등)는 Wish 모델이 한다. 틀리면 422.
    sec = _section_or_404(wish.section_id)
    if store.stage != "COLLECT":
        raise _conflict(f"희망은 수집 단계(COLLECT)에서만 받습니다. 지금 단계: {store.stage}")
    if wish.professor is None:
        wish.professor = sec.professor
    elif sec.professor is not None and wish.professor != sec.professor:
        raise HTTPException(status_code=422, detail="이 분반의 담당 교수가 아닙니다.")
    # 5명 단위 검사는 인원을 바꿀 때만. GET /wishes 로 받은 지금 값을 그대로 되돌려 보내면 통과 (11/27 안전장치).
    # 인원이 비어 있는(NULL) 분반에 처음 넣는 값은 검사한다
    if wish.enrollment is not None and wish.enrollment != sec.enrollment and wish.enrollment % 5:
        raise HTTPException(status_code=422, detail="수강 인원은 5명 단위로 적어 주세요.")
    if _db():
        _db_call(_db().save_wish, wish)
        return {"saved": store.get_wish(wish.section_id) or wish}
    store.save_wish(wish)
    return {"saved": store.get_wish(wish.section_id)}


@app.post("/wishes/pair")
def post_pair(body: PairIn):
    """분반 연강·교차 요청 (교수 입력 필터). DB 모드는 하윤 set_pair_request, 메모리 모드는 기록만."""
    _section_or_404(body.section_id)
    if store.stage != "COLLECT":
        raise _conflict(f"희망은 수집 단계(COLLECT)에서만 받습니다. 지금 단계: {store.stage}")
    if _db():
        order = _db_call(_db().set_pair, body.section_id, body.mode, body.order)
        return {"section_id": body.section_id, "mode": body.mode, "order": order}
    pairs = dict(getattr(store, "pairs", {}))
    if body.mode == "NONE":            # 상관없음 = 지움 (DB set_pair_request 와 같게)
        pairs.pop(body.section_id, None)
    else:
        pairs[body.section_id] = {"mode": body.mode, "order": body.order or []}
    store.pairs = pairs
    return {"section_id": body.section_id, "mode": body.mode, "order": body.order or []}


# ---------- 초안 ----------

@app.post("/draft")
def post_draft():
    if store.stage != "COLLECT":
        raise _conflict(f"초안은 수집 단계(COLLECT)에서 한 번만 만듭니다. 지금 단계: {store.stage}")
    if _db():
        r = _db_call(_db().draft)
        count: dict = {}
        for a in store.timetable.assignments:
            count[a.status] = count.get(a.status, 0) + 1
        kinds: dict = {}
        for o in r["opened"]:
            kinds[o["status"]] = kinds.get(o["status"], 0) + 1
        return {"stage": store.stage, "assignments": len(store.timetable.assignments), "status_count": count,
                "coord": [c["section_id"] for c in store.list_coord()], "coord_status": kinds,
                "solver": {k: r[k] for k in ("status", "seconds", "unplaced", "unsupported")},
                "violations": len(_violations())}
    tt, delayed = engine.make_draft(store.list_sections(), store.list_wishes(), store.list_rooms())
    tt = _normalize(tt)
    tt.status = "DRAFT"
    store.set_timetable(tt)

    by_id = {a.section_id: a for a in tt.assignments}
    for sid in delayed:
        sec = store.get_section(sid)
        if sec is None or sec.shape == "MANUAL":
            continue
        a = by_id.get(sid)
        store.open_coord(sid, a.reason if a else None, engine.make_alternatives(sid))
    store.set_stage("DRAFT")

    status_count = {}
    for a in tt.assignments:
        status_count[a.status] = status_count.get(a.status, 0) + 1
    return {
        "stage": store.stage,
        "assignments": len(tt.assignments),
        "status_count": status_count,
        "coord": [c["section_id"] for c in store.list_coord()],
        "violations": len(_violations(tt)),
    }


@app.get("/timetable")
def get_timetable():
    if store.timetable is None:
        raise _conflict("아직 초안이 없습니다. POST /draft 를 먼저 부르세요.")
    return {"stage": store.stage, "round_no": store.round_no, **dump(store.timetable)}


# ---------- 조율 ----------

@app.get("/coord")
def get_coord():
    return [_coord_out(c) for c in store.list_coord()]


@app.post("/coord/{section_id}/message")
def post_message(section_id: str, body: Optional[MessageIn] = None):
    item = _coord_target(section_id)
    if not item["alternatives"]:
        raise _conflict("대안이 없어 조율 메시지를 쓸 수 없습니다. [수정]이나 [현재대로 유지]로 정해 주세요.")
    method = _nlp(body.method if body else None)
    inp = store.message_input(section_id)
    msg = engine.write_message(inp, method)
    issues = list(engine.check_message(msg.text, inp))
    sent = not issues   # 검사에 걸리면 보내지 않는다
    if _db():
        _db_call(_db().send_message, section_id, msg.text, sent)
        return store.add_message(section_id, msg, issues, sent)
    rec = store.add_message(section_id, msg, issues, sent)
    if sent:
        store.update_coord(section_id, state="SENT", message=msg.text)
    return rec


@app.post("/coord/{section_id}/hold")
def post_hold(section_id: str, body: HoldIn):
    """일부만 어긋난 분반(HOLD): 조교가 [보내기](send=true → OPEN, 이어서 /message) 또는 보내지 않음(KEPT). DB 모드."""
    _section_or_404(section_id)
    if not _db():
        raise _conflict("조교 선택 대기(HOLD)는 DB 모드(SSUROOM_ENGINE=solver)에서만 있습니다.")
    _db_call(_db().release_hold, section_id, body.send)
    return {"coord": _coord_out(store.get_coord(section_id))}


@app.post("/coord/{section_id}/ack")
def post_ack(section_id: str):
    """대안이 없는 분반(NO_OPTION): 조교가 확인 → 따로 연락(OFFLINE) → /manual. DB 모드."""
    _section_or_404(section_id)
    if not _db():
        raise _conflict("대안 없음(NO_OPTION)은 DB 모드(SSUROOM_ENGINE=solver)에서만 있습니다.")
    _db_call(_db().ack_no_option, section_id)
    return {"coord": _coord_out(store.get_coord(section_id))}


@app.post("/coord/{section_id}/reply")
def post_reply(section_id: str, body: ReplyIn):
    item = _coord_target(section_id)
    if item["state"] == "OPEN":
        raise _conflict("먼저 조율 메시지를 보내야 답장을 받을 수 있습니다.")
    can_keep = store.current_label(section_id) is not None
    _check_reply(body, can_keep)
    alts = item["alternatives"]
    parsed = engine.parse_reply(body.text, body.choice, choices=body.choices, alternatives=alts,
                                message=item["message"] or "", method=_nlp(body.method), can_keep=can_keep)
    if _db():
        # DB는 누른 값이 하나 이상 있어야 받는다(add_reply). 예전 값은 바꿔 넣는다: 안 → 그 안, 모두 어려움·글만 → 기타
        choices = list(dict.fromkeys(body.choices or ([body.choice] if body.choice in ("A", "B", "C") else ["ETC"])))
        if "ETC" in choices and not body.text.strip():
            raise HTTPException(status_code=422, detail="기타를 골랐으면 기타 내용을 적어야 합니다.")
        db = _db()
        pid, mid = _db_call(db.add_reply, section_id, body.text, choices)
        # 그사이 못 쓰게 된 안은 [확인] 때 엔진 pick_best 가 가린다
        proposal = engine.match_conditions(parsed, alts, store.round_no, [])
        model = "keyword" if parsed.method == "keyword" else os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        _db_call(db.save_interpretation, pid, mid, parsed, proposal, model)
        return store.add_reply(section_id, body.text, choices, parsed.method, parsed, proposal, [])
    unavailable = _unavailable(section_id, alts)
    proposal = engine.match_conditions(parsed, alts, store.round_no, unavailable)
    rec = store.add_reply(section_id, body.text, body.choices or body.choice, parsed.method, parsed, proposal,
                          unavailable)
    store.update_coord(section_id, state="PROPOSED", proposal=proposal, last_parse=parsed)
    return rec


@app.post("/coord/{section_id}/decide")
def post_decide(section_id: str, body: DecideIn):
    item = _coord_target(section_id)
    if _db():
        if body.action == "edit":
            if not (body.reason and body.reason.strip()):
                raise HTTPException(status_code=422, detail="수정하려면 사유(reason)를 적어야 합니다.")
            if body.choice is None:
                raise HTTPException(status_code=422, detail="수정하려면 고를 안(choice: A|B|C)을 적어야 합니다.")
        r = _db_call(_db().decide, section_id, body.action, body.reason, body.choice)
        rec =store.add_decision(section_id, r["action"], body.reason, r.get("applied"))
        out = {"decision": rec, "coord": _coord_out(store.get_coord(section_id))}
        if r.get("timetable_id"):
            out["violations"] = len(_violations())
        return out

    if item["state"] == "OFFLINE":
        raise _conflict("따로 연락 중인 분반입니다. 정한 자리를 POST /coord/{분반}/manual 로 넣으세요.")
    proposal = item["proposal"]
    # [확인]인데 처리안이 '지금 자리 그대로'면 [현재대로 유지]와 같다
    if body.action == "keep" or (body.action == "confirm" and proposal is not None and proposal.action == "keep"):
        rec = store.add_decision(section_id, "keep", body.reason, None)
        store.update_coord(section_id, state="KEPT")
        return {"decision": rec, "coord": _coord_out(store.get_coord(section_id))}

    if body.action == "offline":
        # [따로 연락]: 시스템 밖에서 교수와 정한 뒤 POST /coord/{분반}/manual 로 넣는다
        rec = store.add_decision(section_id, "offline", body.reason, None)
        store.update_coord(section_id, state="OFFLINE")
        return {"decision": rec, "coord": _coord_out(store.get_coord(section_id))}

    if body.action == "edit":
        if not (body.reason and body.reason.strip()):
            raise HTTPException(status_code=422, detail="수정하려면 사유(reason)를 적어야 합니다.")
        if body.choice is None:
            raise HTTPException(status_code=422, detail="수정하려면 고를 안(choice: A|B|C)을 적어야 합니다.")
        alt = next((a for a in item["alternatives"] if a.key == body.choice), None)
        if alt is None:
            raise HTTPException(status_code=422, detail=f"{body.choice}안이 없습니다.")
    else:  # confirm
        if proposal is None:
            raise _conflict("아직 처리안이 없습니다. 답장을 먼저 넣으세요.")
        if proposal.action == "next":
            # 조건을 넣어 다음 차수로. 시간표는 바꾸지 않고, 확인된 조건만 다음 차수 대안에 쓴다.
            rec = store.add_decision(section_id, "confirm_next", body.reason, dump(proposal.conditions))
            store.update_coord(section_id, state="NEXT", next_conditions=proposal.conditions)
            return {"decision": rec, "coord": _coord_out(store.get_coord(section_id))}
        if proposal.action != "move" or proposal.key is None:
            raise _conflict(f"조교가 직접 정해야 하는 처리안입니다 (action={proposal.action}). "
                            "[수정]·[현재대로 유지]·[따로 연락]을 고르세요.")
        alt = next((a for a in item["alternatives"] if a.key == proposal.key), None)
        if alt is None:
            raise _conflict(f"처리안의 {proposal.key}안이 대안 목록에 없습니다.")

    tt = _normalize(engine.reassign(store.timetable, section_id, alt))
    tt.status = store.timetable.status
    for a in tt.assignments:
        if a.section_id == section_id:
            a.status, a.reason = "DONE", None
    store.set_timetable(tt)
    rec = store.add_decision(section_id, body.action, body.reason, dump(alt))
    store.update_coord(section_id, state="RESOLVED")
    return {"decision": rec, "coord": _coord_out(store.get_coord(section_id)),
            "violations": len(_violations(tt))}


@app.post("/coord/{section_id}/manual")
def post_manual(section_id: str, body: ManualIn):
    """[따로 연락]한 분반을 조교가 교수와 정한 자리에 직접 놓는다. 그 분반은 MANUAL(고정).
    규칙 위반은 막지 않고 경고(warnings)로 돌려준다."""
    _section_or_404(section_id)
    item = store.get_coord(section_id)
    if item is None or item["state"] != "OFFLINE":
        raise _conflict("[따로 연락]한 분반만 직접 놓을 수 있습니다.")
    if not body.meetings:
        raise HTTPException(status_code=422, detail="놓을 수업(meetings)이 없습니다.")
    alt = Alternative(key="A", meetings=[dump(m) for m in body.meetings])
    if _db():
        _tt, warn = _db_call(_db().manual_place, section_id, [dump(m) for m in body.meetings], body.reason)
        rec = store.add_decision(section_id, "manual", body.reason, dump(alt))
        return {"decision": rec, "coord": _coord_out(store.get_coord(section_id)),
                "violations": len(warn), "warnings": warn}
    blocks, _ = meetings_to_blocks(alt.meetings)
    tt = parse(Timetable, dump(store.timetable))
    for a in tt.assignments:
        if a.section_id == section_id:
            set_place(a, blocks)
            a.status, a.reason = "MANUAL", "조교 수동 배치 (따로 연락)"
    store.set_timetable(tt)
    rec = store.add_decision(section_id, "manual", body.reason, dump(alt))
    store.update_coord(section_id, state="RESOLVED")
    vs = [v for v in _violations(tt) if section_id in v.section_ids]
    return {"decision": rec, "coord": _coord_out(store.get_coord(section_id)),
            "violations": len(vs), "warnings": [dump(v) for v in vs]}


# ---------- 차수·확정 ----------

@app.post("/rounds/next")
def post_next_round(body: Optional[RoundIn] = None):
    if _db():
        # DB 모드: 다음 차수를 열고(2·3차는 NEXT 안건을 이어받아 조건을 쌓은 대안), 보내기 전(OPEN) 안건은
        # 조율 메시지를 자동으로 보낸다 (11/25 결정: 못 놓음·어긋남은 자동, 일부 어긋남(HOLD)·대안 없음은 조교 화면)
        no, opened = _db_call(_db().next_round)
        sent = []
        for c in store.list_coord():
            if c["state"] == "OPEN" and c["round_no"] == no:
                post_message(c["section_id"], MessageIn(method=_nlp(body.method if body else None)))
                sent.append(c["section_id"])
        _db().sync(store)
        open_items = [c["section_id"] for c in store.list_coord() if c["state"] not in ("RESOLVED", "KEPT")]
        return {"stage": store.stage, "round_no": store.round_no, "open": open_items, "sent": sent,
                "next_opened": opened}
    if store.stage == "DRAFT":
        store.set_stage("ROUND", round_no=1)
        for c in store.list_coord():
            store.update_coord(c["section_id"], round_no=1)
    elif store.stage == "ROUND":
        if store.round_no >= MAX_ROUND:
            raise _conflict(f"최대 {MAX_ROUND}차까지입니다. 남은 분반은 조교가 정해 확정(POST /finalize)하세요.")
        store.set_stage("ROUND", round_no=store.round_no + 1)
        for c in store.list_coord():
            if c["state"] == "RESOLVED":
                continue
            # 조교가 [확인]한 조건(처리안 next)만 쓴다. 확인 안 한 답장 해석은 반영하지 않는다.
            cond = c.get("next_conditions")
            store.update_coord(c["section_id"], round_no=store.round_no, state="OPEN",
                               message=None, proposal=None, prev_conditions=cond, next_conditions=None,
                               alternatives=engine.make_alternatives(c["section_id"], cond))
    else:
        raise _conflict(f"다음 차수로 갈 수 없는 단계입니다: {store.stage}")
    open_items = [c["section_id"] for c in store.list_coord() if c["state"] != "RESOLVED"]
    return {"stage": store.stage, "round_no": store.round_no, "open": open_items}


@app.post("/finalize")
def post_finalize():
    if store.stage not in ("DRAFT", "ROUND"):
        raise _conflict(f"확정할 수 없는 단계입니다: {store.stage}")
    if _db():
        _db_call(_db().finalize)
        left = [a.section_id for a in store.timetable.assignments if a.status == "COORD"]
        return {"stage": store.stage, "round_no": store.round_no, "unresolved": left,
                "violations": len(_violations())}
    store.set_stage("FINAL")
    left = [a.section_id for a in store.timetable.assignments if a.status == "COORD"]
    return {"stage": store.stage, "round_no": store.round_no, "unresolved": left,
            "violations": len(_violations(store.timetable))}


@app.post("/reset")
def post_reset():
    assistant.clear_proposals()
    if _db():
        _db_call(_db().reset)
        return {"stage": store.stage}
    store.reset()
    return {"stage": store.stage}


# ---------- AI 도우미 ----------

@app.post("/assistant")
def post_assistant(body: AssistantIn):
    """조교 질문 → 의도·정보 → 배정 함수 호출 → 설명. move는 제안만 만들고 반영하지 않는다.
    method="llm"이 실패하면 키워드 방식으로 대신 처리하고 command.fallback=True (fallback_reason에 이유)."""
    cmd = assistant.read_question(body.text, body.history, store, method=_nlp(body.method))
    out = assistant.run_assistant(cmd, store)
    res = {"command": dump(cmd), "section_id": cmd.section_id, **out}
    prop = assistant.get_proposal(out.get("proposal_id")) if out.get("proposal_id") else None
    if prop is not None and store.timetable is not None:
        # 옮기기 제안: '옮긴 뒤' 시간표 기준 위반 (DB 모드는 복사본에서 하윤 check_timetable, 메모리 모드는 가짜)
        vs = _violations_after(prop["section_id"], prop["alternative"])
        prop["violations"] = len(vs)
        res["violations"] = len(vs)
        res["violation_list"] = [dump(v) for v in vs]
    return res


@app.post("/assistant/apply")
def post_assistant_apply(body: ApplyIn):
    """도우미 제안(move)을 반영한다. 사유 필수. 수정 기록에 남긴다."""
    if not (body.reason and body.reason.strip()):
        raise HTTPException(status_code=422, detail="적용하려면 사유(reason)를 적어야 합니다.")
    prop = assistant.get_proposal(body.proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail=f"제안이 없습니다: {body.proposal_id}")
    if store.stage == "FINAL":
        raise _conflict("시간표가 확정(FINAL)되어 적용할 수 없습니다.")
    if store.timetable is None:
        raise _conflict("아직 초안이 없습니다.")
    if assistant.timetable_key(store.timetable) != prop["base"]:
        assistant.pop_proposal(body.proposal_id)
        raise _conflict("제안을 만든 뒤 시간표가 바뀌었습니다. 도우미에게 다시 물어봐 주세요.")

    sid, alt = prop["section_id"], prop["alternative"]
    if _db():
        _db_call(_db().assistant_apply, sid, alt, body.reason.strip())
        rec = store.add_decision(sid, "assistant_move", body.reason.strip(), dump(alt))
        assistant.pop_proposal(body.proposal_id)
        return {"decision": rec, "summary": prop["summary"], "violations": len(_violations())}
    tt = _normalize(engine.reassign(store.timetable, sid, alt))
    tt.status = store.timetable.status
    store.set_timetable(tt)
    rec = store.add_decision(sid, "assistant_move", body.reason.strip(), dump(alt))
    item = store.get_coord(sid)
    if item is not None and item["state"] not in ("RESOLVED",):
        store.update_coord(sid, state="RESOLVED")   # 조교가 직접 옮겼으므로 이 분반 조율은 끝
    assistant.pop_proposal(body.proposal_id)
    return {"decision": rec, "summary": prop["summary"], "violations": len(_violations(tt))}


# ---------- 엑셀 내보내기 ----------


@app.get("/export.xlsx")
def get_export():
    """확정(FINAL) 시간표를 엑셀로. MANUAL 분반 포함. 가상/가명 데이터, SAP 실제 양식이 아닌 제안 양식."""
    if store.stage != "FINAL" or store.timetable is None:
        raise _conflict(f"확정(FINAL)한 뒤에 내보낼 수 있습니다. 지금 단계: {store.stage}")
    data = export.write_xlsx(export.timetable_rows(_normalize(parse(Timetable, dump(store.timetable))),
                                                   store.list_sections()))
    return Response(content=data, media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="ssuroom_timetable.xlsx"'})
