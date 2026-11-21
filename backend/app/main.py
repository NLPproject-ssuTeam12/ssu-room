"""SSU:room FastAPI 서버 (백엔드 ③).

실행 (저장소 루트에서):
    uvicorn backend.app.main:app --reload --port 8000

배정·조율 함수는 engine.py에서만 가져온다 (진짜가 없으면 가짜).
상태는 store.py(메모리)에 둔다. 단계: COLLECT → DRAFT → ROUND(1~3) → FINAL.
조교가 [확인]·[수정]·[현재대로 유지]를 누르기 전에는 어떤 처리안도 시간표에 반영하지 않는다.
"""

import logging
import os
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import engine
from .contracts import Label, Timetable, Wish, dump
from .nlp import assistant
from .store import MAX_ROUND, store

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="SSU:room", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
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


# ---------- 요청 모양 ----------

class ReplyIn(BaseModel):
    text: str
    method: Literal["keyword", "llm"] = "keyword"


class DecideIn(BaseModel):
    action: Literal["confirm", "edit", "keep"]
    reason: Optional[str] = None
    choice: Optional[Label] = None   # edit일 때 조교가 고른 안


class AssistantIn(BaseModel):
    text: str
    history: List[dict] = []         # [{"role": "user"|"assistant", "text": "...", "section_id": 선택}]
    method: Literal["keyword", "llm"] = "keyword"


class ApplyIn(BaseModel):
    proposal_id: str
    reason: Optional[str] = None


# ---------- 도우미 ----------

def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


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
    out = dict(item)
    out["name"] = sec.name if sec else None
    out["professor"] = sec.professor if sec else None
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
    }


# ---------- 기본 자료 ----------

@app.get("/sections")
def get_sections():
    return store.list_sections()


@app.get("/rooms")
def get_rooms():
    return store.list_rooms()


@app.get("/wishes")
def get_wishes():
    return {"wishes": store.list_wishes(), "professors": store.professors}


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
    store.save_wish(wish)
    return {"saved": wish}


# ---------- 초안 ----------

@app.post("/draft")
def post_draft():
    if store.stage != "COLLECT":
        raise _conflict(f"초안은 수집 단계(COLLECT)에서 한 번만 만듭니다. 지금 단계: {store.stage}")
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
        "violations": len(engine.check_rules(tt)),
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
def post_message(section_id: str):
    item = _coord_target(section_id)
    sec = store.get_section(section_id)
    text = engine.write_message(sec, store.get_wish(section_id), item["alternatives"],
                                store.round_no, item["reason"])
    issues = [dump(i) for i in engine.check_message(text)]
    sent = not issues   # 검사에 걸리면 보내지 않는다
    rec = store.add_message(section_id, text, issues, sent)
    if sent:
        store.update_coord(section_id, state="SENT", message=text)
    return rec


@app.post("/coord/{section_id}/reply")
def post_reply(section_id: str, body: ReplyIn):
    item = _coord_target(section_id)
    if item["state"] == "OPEN":
        raise _conflict("먼저 조율 메시지를 보내야 답장을 받을 수 있습니다.")
    parsed = engine.parse_reply(body.text, method=body.method)
    proposal = engine.match_conditions(parsed, item["alternatives"])
    rec = store.add_reply(section_id, body.text, body.method, parsed, proposal)
    store.update_coord(section_id, state="PROPOSED", proposal=proposal, last_parse=parsed)
    return rec


@app.post("/coord/{section_id}/decide")
def post_decide(section_id: str, body: DecideIn):
    item = _coord_target(section_id)

    if body.action == "keep":
        rec = store.add_decision(section_id, "keep", body.reason, None)
        store.update_coord(section_id, state="KEPT")
        return {"decision": rec, "coord": _coord_out(store.get_coord(section_id))}

    if body.action == "edit":
        if not (body.reason and body.reason.strip()):
            raise HTTPException(status_code=422, detail="수정하려면 사유(reason)를 적어야 합니다.")
        if body.choice is None:
            raise HTTPException(status_code=422, detail="수정하려면 고를 안(choice: A|B|C)을 적어야 합니다.")
        alt = next((a for a in item["alternatives"] if a.label == body.choice), None)
        if alt is None:
            raise HTTPException(status_code=422, detail=f"{body.choice}안이 없습니다.")
    else:  # confirm
        proposal = item["proposal"]
        if proposal is None:
            raise _conflict("아직 처리안이 없습니다. 답장을 먼저 넣으세요.")
        if proposal.action != "MOVE" or proposal.alternative is None:
            raise _conflict("처리안에 옮길 안이 없습니다. [수정]이나 [현재대로 유지]를 고르세요.")
        alt = proposal.alternative

    tt = _normalize(engine.reassign(store.timetable, section_id, alt))
    tt.status = store.timetable.status
    for a in tt.assignments:
        if a.section_id == section_id:
            a.status, a.reason = "DONE", None
    store.set_timetable(tt)
    rec = store.add_decision(section_id, body.action, body.reason, dump(alt))
    store.update_coord(section_id, state="RESOLVED")
    return {"decision": rec, "coord": _coord_out(store.get_coord(section_id)),
            "violations": len(engine.check_rules(tt))}


# ---------- 차수·확정 ----------

@app.post("/rounds/next")
def post_next_round():
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
            cond = c["last_parse"].conditions if c["last_parse"] is not None else None
            store.update_coord(c["section_id"], round_no=store.round_no, state="OPEN",
                               message=None, proposal=None,
                               alternatives=engine.make_alternatives(c["section_id"], cond))
    else:
        raise _conflict(f"다음 차수로 갈 수 없는 단계입니다: {store.stage}")
    open_items = [c["section_id"] for c in store.list_coord() if c["state"] != "RESOLVED"]
    return {"stage": store.stage, "round_no": store.round_no, "open": open_items}


@app.post("/finalize")
def post_finalize():
    if store.stage not in ("DRAFT", "ROUND"):
        raise _conflict(f"확정할 수 없는 단계입니다: {store.stage}")
    store.set_stage("FINAL")
    left = [a.section_id for a in store.timetable.assignments if a.status == "COORD"]
    return {"stage": store.stage, "round_no": store.round_no, "unresolved": left,
            "violations": len(engine.check_rules(store.timetable))}


@app.post("/reset")
def post_reset():
    store.reset()
    assistant.clear_proposals()
    return {"stage": store.stage}


# ---------- AI 도우미 ----------

@app.post("/assistant")
def post_assistant(body: AssistantIn):
    """조교 질문 → 의도·정보 → 배정 함수 호출 → 설명. move는 제안만 만들고 반영하지 않는다."""
    try:
        cmd = assistant.read_question(body.text, body.history, store, method=body.method)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="언어 모델(llm) 도우미는 다음 단계에서 구현합니다. method=keyword를 쓰세요.")
    out = assistant.run_assistant(cmd, store)
    return {"command": dump(cmd), "section_id": cmd.section_id, **out}


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
    tt = _normalize(engine.reassign(store.timetable, sid, alt))
    tt.status = store.timetable.status
    store.set_timetable(tt)
    rec = store.add_decision(sid, "assistant_move", body.reason.strip(), dump(alt))
    item = store.get_coord(sid)
    if item is not None and item["state"] not in ("RESOLVED",):
        store.update_coord(sid, state="RESOLVED")   # 조교가 직접 옮겼으므로 이 분반 조율은 끝
    assistant.pop_proposal(body.proposal_id)
    return {"decision": rec, "summary": prop["summary"], "violations": len(engine.check_rules(tt))}


# ---------- 다음 단계에서 구현 ----------


@app.get("/export.xlsx")
def get_export():
    raise HTTPException(status_code=501, detail="엑셀 내보내기는 다음 단계에서 구현합니다.")
