"""DB 모드 (백엔드 ③, 김대원): 서버 상태를 문하윤 DB(db/schema.sql)에 둔다. SSUROOM_ENGINE=solver 일 때만 쓴다.

- DB가 기준이다. 바꾸는 요청(희망·초안·조율·차수·확정·도우미 적용)은 하윤 db.py·solver_core.py 함수로 DB에 쓰고,
  끝나면 sync()로 메모리 store(store.py)를 DB 모양 그대로 다시 채운다. 읽는 요청과 AI 도우미는 지금처럼 store를 읽는다.
- 하윤 파일은 고치지 않는다. 하윤 함수가 없는 곳만 서버가 직접 쓴다:
  조율 메시지 보내기(message 행 + 안건 OPEN → SENT), 분반 배정 상태 COORD 표시, /reset 때 조율·시간표 기록 지우기.
- 희망은 1차(희망 수집) round 의 응답이다. 2·3차 대안도 1차 round id 로 만든다
  (solver_core.fill_options 는 안건의 round id 로 응답을 읽어 2·3차에서는 희망·불가 칸을 못 봐서 쓰지 않는다. 하윤에게 알림).
- 단계: 서버 COLLECT/DRAFT/ROUND(1~3)/FINAL ↔ term.phase COLLECTING/ROUND1~3/FINAL + 시간표 유무.
  COLLECTING 인데 시간표가 있으면 DRAFT.
"""

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import engine
from .contracts import (
    DAYS, STARTS, Alternative, Assignment, Block, Room, Section, Timetable, Wish, conditions_json, dump, parse,
)
from .solver.adapter import (
    REPO_ROOT, RoomIndex, SectionMap, SlotIndex, SolverAdapter, assignments_from_db, configure, default_paths,
    load_haeyoon, option_to_alternative, solver_condition,
)

KEYS = ("A", "B", "C")
LABEL = {"수용": "ACCEPT", "조건부": "CONDITIONAL", "거절": "REJECT", "확인 필요": "UNCLEAR"}
PHASE_OF_ROUND = {1: "ROUND1", 2: "ROUND2", 3: "ROUND3"}
DRAFT_TIME_LIMIT = int(os.environ.get("SSUROOM_DRAFT_SECONDS", "60"))
ALT_TIME_LIMIT = int(os.environ.get("SSUROOM_ALT_SECONDS", "15"))


class DBModeError(Exception):
    """화면에 그대로 보여 줄 수 있는 거부 이유 (main 이 409로 바꾼다)."""


class DBMode:
    def __init__(self, con, mapping: dict, draft_time_limit: int = DRAFT_TIME_LIMIT, alt_time_limit: int = ALT_TIME_LIMIT):
        self.hdb, self.sc = load_haeyoon()
        self.con = con
        self.map = mapping
        self.term_id = mapping["term_id"]
        self.wish_round = mapping["round_id"]          # 희망 수집 = 1차 round
        self.ta_id = mapping.get("ta_id") or con.execute("SELECT id FROM user WHERE role='TA' ORDER BY id").fetchone()[0]
        self.prof_id: Dict[str, int] = {n: i for i, n in con.execute("SELECT id, name FROM user WHERE role='PROF'")}
        self.pairs = SectionMap({(v["course_id"], v["section_no"]): sid for sid, v in mapping["sections"].items()
                                 if not v.get("manual")})
        self.slots = SlotIndex(con, self.term_id)
        self.rooms = RoomIndex(con)
        self.draft_time_limit, self.alt_time_limit = draft_time_limit, alt_time_limit
        self.adapter = SolverAdapter(con, self.term_id, self.wish_round, self.pairs,
                                     draft_time_limit=draft_time_limit, alt_time_limit=alt_time_limit)
        configure(self.adapter)

    @classmethod
    def from_files(cls, db_path: Optional[Path] = None, map_path: Optional[Path] = None, **kw) -> "DBMode":
        d, m = default_paths()
        db_path, map_path = Path(db_path or d), Path(map_path or m)
        for f, how in ((db_path, "DB"), (map_path, "분반 대응표")):
            if not f.exists():
                raise RuntimeError(f"{how} 파일이 없습니다: {f}. 먼저 python backend/tools/seed_db.py 를 실행하세요.")
        con = sqlite3.connect(db_path, check_same_thread=False)   # 서버는 요청을 다른 스레드에서 처리
        con.execute("PRAGMA foreign_keys = ON")                     # 하윤 db.connect 와 같이
        return cls(con, json.loads(map_path.read_text(encoding="utf-8")), **kw)

    # ---------- 읽기 도우미 ----------

    def q(self, sql, args=()):
        return self.con.execute(sql, args)

    def phase(self) -> str:
        return self.hdb.get_phase(self.con, self.term_id)["phase"]

    def current_tt(self) -> Optional[int]:
        return self.q("SELECT MAX(id) FROM timetable WHERE term_id=?", (self.term_id,)).fetchone()[0]

    def round_id(self, no: int) -> Optional[int]:
        r = self.q("SELECT id FROM round WHERE term_id=? AND round_no=?", (self.term_id, no)).fetchone()
        return r[0] if r else None

    def stage(self) -> Tuple[str, int]:
        ph = self.phase()
        if ph == "FINAL":
            return "FINAL", max([int(p[-1]) for p in ("ROUND1", "ROUND2", "ROUND3") if self._was(p)] or [0])
        if ph.startswith("ROUND"):
            return "ROUND", int(ph[-1])
        return ("DRAFT" if self.current_tt() else "COLLECT"), 0

    def _was(self, phase: str) -> bool:
        return self.q("SELECT 1 FROM phase_log WHERE term_id=? AND to_phase=?", (self.term_id, phase)).fetchone() is not None

    def section_key(self, sid: str) -> Tuple[int, int]:
        return self.pairs.key(sid)

    def latest_proposal(self, sid: str) -> Optional[int]:
        cid, sec = self.section_key(sid)
        r = self.q("SELECT MAX(id) FROM proposal WHERE course_id=? AND section_no=?", (cid, sec)).fetchone()
        return r[0]

    def alternatives_of(self, pid: int) -> List[Alternative]:
        """안건의 대안 1·2·3번 → A·B·C (4번 이후는 pick_best 가 만든 안이라 교수에게 보내지 않음)."""
        cid = self.q("SELECT course_id FROM proposal WHERE id=?", (pid,)).fetchone()[0]
        out = []
        for oid, no in self.q("SELECT id, option_no FROM proposal_option WHERE proposal_id=? AND option_no<=3 "
                              "ORDER BY option_no", (pid,)):
            o = self.sc.load_option(self.con, oid)
            out.append(option_to_alternative(KEYS[no - 1], o, cid, self.slots, self.rooms))
        return out

    def option_id(self, pid: int, key: str) -> Optional[int]:
        r = self.q("SELECT id FROM proposal_option WHERE proposal_id=? AND option_no=?", (pid, KEYS.index(key) + 1)).fetchone()
        return r[0] if r else None

    # ---------- store 채우기 ----------

    def sections(self) -> List[Section]:
        lab = {(c, s): l for c, s, l in self.q("SELECT course_id, section_no, lab_requirement FROM course_response "
                                                  "WHERE round_id=?", (self.wish_round,))}
        enr = {(c, s): e for c, s, e in self.q("SELECT course_id, section_no, enrollment FROM course_section")}
        out = []
        for sid, v in self.map["sections"].items():
            weekly = sum(b["slots"] for b in v["blocks"]) if v.get("manual") else 2
            shape = v["shape"]
            out.append(Section(
                id=sid, code=v["code"], name=v["name"], division=v.get("division"), year=v.get("year"),
                category=v.get("category_orig") or v.get("category") or "",
                enrollment=enr.get((v.get("course_id"), v.get("section_no")), v.get("enrollment")),   # DB 값이 기준
                weekly_blocks=max(weekly, 1), professor=v.get("professor"),
                lab_need="MUST" if lab.get((v.get("course_id"), v.get("section_no"))) == "MUST" else "NONE",
                shape=shape if shape in ("TWICE", "ONCE_LONG", "MANUAL") else "MANUAL"))
        return out

    def room_list(self) -> List[Room]:
        info = self.map.get("rooms", {})
        out = []
        for rid, b, no, cap, lab in self.q("""SELECT r.id, b.name, r.room_no, r.capacity, r.is_lab
                                              FROM room r JOIN building b ON b.id = r.building_id ORDER BY b.name, r.room_no"""):
            name = f"{b} {no}"
            out.append(Room(id=name, building=b, room_no=no, capacity=cap, is_lab=bool(lab),
                            estimated=bool(info.get(name, {}).get("estimated"))))
        return out

    def wishes(self) -> List[Wish]:
        bld = dict(self.q("""SELECT p.professor_id, b.name FROM professor_building_pref p
                             JOIN building b ON b.id = p.building_id"""))
        notes = dict(self.q("SELECT response_id, body FROM other_request WHERE response_id IS NOT NULL"))
        enr = {(c, s): e for c, s, e in self.q("SELECT course_id, section_no, enrollment FROM course_section")}
        name_of = {i: n for n, i in self.prof_id.items()}
        out = []
        for rid, cid, sec, pid, lab, single in self.q(
                """SELECT r.id, r.course_id, r.section_no, r.professor_id, r.lab_requirement, r.single_day_pref
                   FROM course_response r JOIN course_section cs ON cs.course_id = r.course_id
                        AND cs.section_no = r.section_no AND cs.professor_id = r.professor_id
                   WHERE r.round_id=?""", (self.wish_round,)):
            sid = self.pairs.sid_of.get((cid, sec))
            if sid is None:
                continue
            cells = {}
            for slot, kind in self.q("SELECT slot_id, kind FROM response_slot WHERE response_id=?", (rid,)):
                d, _p, st, _e = self.slots.info[slot]
                if d in DAYS and st in STARTS:
                    cells[f"{d}-{st}"] = kind
            out.append(Wish(section_id=sid, professor=name_of.get(pid), cells=cells, lab=lab, single_day=single,
                            building=bld.get(pid), note=notes.get(rid, ""), enrollment=enr.get((cid, sec))))
        return out

    def manual_assignments(self) -> Dict[str, Assignment]:
        out = {}
        for sid, v in self.map["sections"].items():
            if v.get("manual"):
                blocks = [Block(day=b["day"], start=b["start"], slots=b["slots"], room=b.get("room")) for b in v["blocks"]]
                out[sid] = Assignment(section_id=sid, blocks=blocks, status="MANUAL",
                                      reason=f"조교 직접 배정 분반 ({v.get('manual_reason') or '자동 배정 대상 아님'})")
        return out

    def timetable(self, tt: Optional[int] = None) -> Optional[Timetable]:
        tt = tt or self.current_tt()
        if tt is None:
            return None
        start, ks = self.sc.load_assignment(self.con, tt)
        placed = assignments_from_db(start, ks, self.slots, self.rooms, self.pairs)
        status = {(c, s): (st, lk) for c, s, st, lk in self.q(
            "SELECT course_id, section_no, status, locked FROM timetable_section WHERE timetable_id=?", (tt,))}
        reasons = {}
        for pid, cid, sec, reason in self.q("SELECT id, course_id, section_no, reason FROM proposal ORDER BY id"):
            reasons[(cid, sec)] = reason
        out = []
        for (cid, sec), sid in sorted(self.pairs.sid_of.items()):
            a = placed.get(sid) or Assignment(section_id=sid, blocks=[], status="COORD",
                                              reason="솔버가 하드 규칙을 지키며 놓을 자리를 찾지 못함")
            st, _lk = status.get((cid, sec), ("DONE", 0))
            if a.blocks:
                a.status = "MANUAL" if st == "MANUAL" else ("COORD" if st == "COORD" else "DONE")
            a.reason = reasons.get((cid, sec)) if a.status == "COORD" else (
                "조교 수동 배치 (따로 연락)" if a.status == "MANUAL" else None)
            out.append(a)
        stage, _ = self.stage()
        return Timetable(status="DRAFT" if stage in ("COLLECT", "DRAFT") else stage, assignments=out)

    def coord_items(self, store) -> Dict[str, dict]:
        """분반마다 가장 최근 안건 → 조율 목록 항목 (메모리 모드와 같은 칸 + proposal_id·kind·round_no·current)."""
        from .contracts import Proposal, ReplyParse
        items = {}
        for pid, rid, cid, sec, reason, st, kind in self.q(
                """SELECT p.id, p.round_id, p.course_id, p.section_no, p.reason, p.status, p.target_kind
                   FROM proposal p WHERE p.id IN (SELECT MAX(id) FROM proposal GROUP BY course_id, section_no)
                   ORDER BY p.id"""):
            sid = self.pairs.sid_of.get((cid, sec))
            if sid is None:
                continue
            rno = self.q("SELECT round_no FROM round WHERE id=?", (rid,)).fetchone()[0]
            msg = self.q("""SELECT body FROM message WHERE proposal_id=? AND kind<>'REPLY' AND delivery_status='SENT'
                            ORDER BY id DESC LIMIT 1""", (pid,)).fetchone()
            ri = self.q("""SELECT ri.extracted_json FROM message m JOIN reply_interpretation ri ON ri.message_id = m.id
                           WHERE m.proposal_id=? AND m.kind='REPLY' ORDER BY m.id DESC LIMIT 1""", (pid,)).fetchone()
            ex = json.loads(ri[0]) if ri and ri[0] else {}
            carried = self.hdb.carried_conditions(self.con, pid)
            items[sid] = {
                "section_id": sid, "proposal_id": pid, "kind": kind, "reason": reason, "round_no": rno, "state": st,
                "alternatives": self.alternatives_of(pid),
                "message": msg[0] if msg else None,
                "proposal": parse(Proposal, ex["proposal"]) if ex.get("proposal") else None,
                "last_parse": parse(ReplyParse, ex["parse"]) if ex.get("parse") else None,
                "next_conditions": self.hdb.confirmed_conditions(self.con, pid) if st == "NEXT" else None,
                "prev_conditions": parse_conditions(carried),
                "current": None,
            }
        return items

    def sync(self, store) -> None:
        """DB → 메모리 store. 바꾸는 요청 뒤마다 부른다."""
        store.sections = {s.id: s for s in self.sections()}
        store.rooms = {r.id: r for r in self.room_list()}
        store.wishes = {w.section_id: w for w in self.wishes()}
        store.manual_assignments = self.manual_assignments()
        store.professors = {p: {"sections": sorted(s.id for s in store.sections.values() if s.professor == p)}
                            for p in sorted(self.prof_id)}
        store.stage, store.round_no = self.stage()
        tt = self.timetable()
        if tt is not None:
            have = {a.section_id for a in tt.assignments}
            tt.assignments += [m for sid, m in store.manual_assignments.items() if sid not in have]
        store.timetable = tt
        store.coord = self.coord_items(store)
        for sid, item in store.coord.items():
            item["current"] = store.current_label(sid) if item["kind"] != "UNPLACED" else None
        store.fixed_blocks = getattr(store, "fixed_blocks", [])
        self.adapter.timetable_id = self.current_tt()

    # ---------- 희망 입력 ----------

    def save_wish(self, wish: Wish) -> None:
        cid, sec = self.section_key(wish.section_id)
        pid = self.prof_id.get(wish.professor or "")
        if pid is None:
            raise DBModeError(f"교수가 없습니다: {wish.professor}")
        try:
            old = self.q("SELECT id FROM course_response WHERE round_id=? AND course_id=? AND section_no=? AND professor_id=?",
                         (self.wish_round, cid, sec, pid)).fetchone()
            if old:
                self.q("DELETE FROM response_slot WHERE response_id=?", (old[0],))
                self.q("DELETE FROM other_request WHERE response_id=?", (old[0],))
                self.q("DELETE FROM request_item WHERE response_id=?", (old[0],))
                self.q("DELETE FROM course_response WHERE id=?", (old[0],))
            rid = self.q("""INSERT INTO course_response(round_id, course_id, section_no, professor_id, lab_requirement,
                                                        single_day_pref, submitted_at) VALUES (?,?,?,?,?,?,datetime('now'))""",
                         (self.wish_round, cid, sec, pid, wish.lab, "MUST" if wish.single_day == "MUST" else "NONE")).lastrowid
            for cell, kind in wish.cells.items():
                d, _, st = cell.partition("-")
                self.q("INSERT INTO response_slot(response_id, slot_id, kind) VALUES (?,?,?)",
                       (rid, self.slots.id_of[(d, st)], kind))
            if wish.note.strip():
                self.q("INSERT INTO other_request(response_id, body) VALUES (?,?)", (rid, wish.note.strip()))
            if wish.enrollment is not None:   # 분반 수강 인원 (하윤 db.py 에 함수가 없어 서버가 직접 바꾼다)
                self.q("UPDATE course_section SET enrollment=? WHERE course_id=? AND section_no=?",
                       (wish.enrollment, cid, sec))
            self.q("DELETE FROM professor_building_pref WHERE professor_id=?", (pid,))
            if wish.building:
                b = self.q("SELECT id FROM building WHERE name=?", (wish.building,)).fetchone()
                if b is None:
                    raise DBModeError(f"없는 건물입니다: {wish.building}")
                self.q("INSERT INTO professor_building_pref(professor_id, building_id) VALUES (?,?)", (pid, b[0]))
            self.q("""INSERT INTO round_invite(round_id, professor_id, status, responded_at) VALUES (?,?, 'RESPONDED', datetime('now'))
                      ON CONFLICT(round_id, professor_id) DO UPDATE SET status='RESPONDED', responded_at=datetime('now')""",
                   (self.wish_round, pid))
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    def set_pair(self, sid: str, mode: str, order: Optional[List[str]] = None) -> List[str]:
        """분반 연강·교차 (과목 단위로 한 번). order = 붙일 분반 id, 교수가 적은 순서."""
        cid, _ = self.section_key(sid)
        prof = self.q("SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?",
                      (cid, self.section_key(sid)[1])).fetchone()[0]
        secs = [self.section_key(x)[1] for x in order] if order else None
        got = self.hdb.set_pair_request(self.con, self.wish_round, cid, prof, mode, secs)
        return [self.pairs.sid_of[(cid, s)] for s in got]

    def pair_requests(self) -> List[dict]:
        """분반 연강·교차 (pair_request + pair_request_section, 희망 수집 차수) → POST /wishes/pair 모양.
        section_id = 붙일 분반 중 첫 분반(교수가 적은 순서), order = 붙일 분반 id 순서."""
        out = []
        for pid, cid, mode in self.q("SELECT id, course_id, mode FROM pair_request WHERE round_id=? ORDER BY id",
                                     (self.wish_round,)).fetchall():
            order = [self.pairs.sid_of.get((cid, sec)) for (sec,) in self.q(
                "SELECT section_no FROM pair_request_section WHERE request_id=? ORDER BY seq", (pid,))]
            order = [x for x in order if x]
            if order:
                out.append(dict(section_id=order[0], mode=mode, order=order))
        return out

    # ---------- 초안 ----------

    def draft(self) -> dict:
        r = self.sc.solve(self.con, self.term_id, self.wish_round, time_limit=self.draft_time_limit)
        tt = r.get("timetable_id")
        if tt is None:
            raise DBModeError(f"솔버가 초안을 만들지 못했습니다 (status={r.get('status')})")
        opened = self.sc.open_coord_proposals(self.con, self.term_id, self.wish_round, tt, n=3,
                                              time_limit=self.alt_time_limit)
        for o in opened:   # 조율 중인 분반은 배정 상태 COORD (하윤 README: 안 풀렸는지는 이것으로 판단)
            self.q("UPDATE timetable_section SET status='COORD' WHERE timetable_id=? AND course_id=? AND section_no=?",
                   (tt, o["course_id"], o["section_no"]))
        self.con.commit()
        return dict(status=r["status"], seconds=r.get("seconds"), unplaced=len(r.get("unplaced") or []),
                    unsupported=r.get("unsupported") or [], opened=opened)

    # ---------- 조율 ----------

    def _proposal_row(self, sid: str):
        pid = self.latest_proposal(sid)
        if pid is None:
            raise DBModeError(f"조율 대상 분반이 아닙니다: {sid}")
        st, kind = self.q("SELECT status, target_kind FROM proposal WHERE id=?", (pid,)).fetchone()
        return pid, st, kind

    def send_message(self, sid: str, text: str, sent: bool) -> int:
        """조율 메시지를 남긴다. 보냈으면 안건 OPEN → SENT (하윤 함수가 없어 서버가 직접 씀)."""
        pid, st, _ = self._proposal_row(sid)
        if st != "OPEN":
            raise DBModeError({"HOLD": "일부만 어긋난 분반입니다. 조교가 [보내기]를 눌러야 보냅니다 (POST /coord/{분반}/hold).",
                               "NO_OPTION": "대안이 없어 보낼 수 없습니다. [확인] 뒤 따로 연락하세요 (POST /coord/{분반}/ack)."}
                              .get(st, f"보내기 전(OPEN) 안건만 보냅니다. 지금 상태: {st}"))
        cid, sec = self.section_key(sid)
        prof = self.q("SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?", (cid, sec)).fetchone()[0]
        rid = self.q("SELECT round_id FROM proposal WHERE id=?", (pid,)).fetchone()[0]
        try:
            mid = self.q("""INSERT INTO message(round_id, proposal_id, sender_id, receiver_id, kind, channel, body, sent_at,
                                                delivery_status) VALUES (?,?,?,?,'ALTERNATIVE','APP',?,datetime('now'),?)""",
                         (rid, pid, self.ta_id, prof, text, "SENT" if sent else "BLOCKED")).lastrowid
            if sent:
                self.q("UPDATE proposal SET status='SENT' WHERE id=?", (pid,))
            self.con.commit()
            return mid
        except Exception:
            self.con.rollback()
            raise

    def _mark_done(self, sid: str) -> None:
        """그 분반을 지금 자리로 끝냄 (배정 상태 COORD → DONE, 지금 시간표 버전)."""
        cid, sec = self.section_key(sid)
        self.q("""UPDATE timetable_section SET status='DONE' WHERE timetable_id=? AND course_id=? AND section_no=?
                  AND status='COORD'""", (self.current_tt(), cid, sec))
        self.con.commit()

    def release_hold(self, sid: str, send: bool) -> None:
        pid, st, _ = self._proposal_row(sid)
        self.hdb.release_hold(self.con, pid, self.ta_id, send=send)
        if not send:
            self._mark_done(sid)

    def ack_no_option(self, sid: str) -> None:
        pid, st, _ = self._proposal_row(sid)
        self.hdb.ack_no_option(self.con, pid, self.ta_id)

    def add_reply(self, sid: str, text: str, choices: List[str]) -> Tuple[int, int]:
        pid, st, _ = self._proposal_row(sid)
        cid, sec = self.section_key(sid)
        prof = self.q("SELECT professor_id FROM course_section WHERE course_id=? AND section_no=?", (cid, sec)).fetchone()[0]
        mid = self.hdb.add_reply(self.con, pid, prof, text, choices=choices)
        return pid, mid

    def save_interpretation(self, pid: int, mid: int, parsed, proposal, model_name: str) -> None:
        picks = list(parsed.picks)
        chosen = self.option_id(pid, picks[0]) if picks else None
        data = {"parse": dump(parsed), "proposal": dump(proposal), "conditions": conditions_json(parsed.conditions)}
        self.hdb.save_interpretation(self.con, mid, LABEL[parsed.kind], data, model_name=model_name, chosen_option_id=chosen)
        if parsed.note and self.q("SELECT 1 FROM reply_choice WHERE message_id=? AND choice='ETC'", (mid,)).fetchone():
            # 기타 글의 시간표 밖 요청 → 기타 요청 표 (조교 [확인함])
            self.hdb.add_reply_request(self.con, mid, parsed.note)

    def _latest_reply(self, pid: int) -> Tuple[int, dict]:
        row = self.q("""SELECT m.id, ri.extracted_json FROM message m JOIN reply_interpretation ri ON ri.message_id = m.id
                        WHERE m.proposal_id=? AND m.kind='REPLY' ORDER BY m.id DESC LIMIT 1""", (pid,)).fetchone()
        if row is None:
            raise DBModeError("아직 처리안이 없습니다. 답장을 먼저 넣으세요.")
        return row[0], json.loads(row[1] or "{}")

    def _apply(self, pid: int, mid: int, decide_args: dict, option_id: int, reason: Optional[str]) -> int:
        """조교 결정 기록(decide_reply) + 새 시간표 버전(apply_option). 새 규칙 위반이면 결정을 되돌리고 거부한다.
        (하윤 apply_option 은 안건을 RESOLVED 로 바꾸고 decide_reply 는 PROPOSED 일 때만 받으므로 결정을 먼저 쓴다.
         두 함수를 한 트랜잭션으로 묶는 함수가 없어, 거부되면 서버가 결정 기록을 되돌린다.)"""
        self.hdb.decide_reply(self.con, mid, self.ta_id, option_id=option_id, reason=reason, **decide_args)
        rows = self.sc.option_rows(self.con, option_id=option_id)
        try:
            new_tt = self.sc.apply_option(self.con, pid, self.ta_id, rows, reason, base_timetable_id=self.current_tt())
        except ValueError:
            self.q("""UPDATE reply_interpretation SET ta_action=NULL, ta_reason=NULL, ta_user_id=NULL, ta_at=NULL
                      WHERE message_id=?""", (mid,))
            self.q("UPDATE proposal SET status='PROPOSED' WHERE id=?", (pid,))
            self.con.commit()
            raise
        return new_tt

    def decide(self, sid: str, action: str, reason: Optional[str], choice: Optional[str]) -> dict:
        """조교 결정. -> {"action", "applied"(Alternative dict 또는 조건), "timetable_id"}"""
        pid, st, _ = self._proposal_row(sid)
        if st == "OFFLINE":
            raise DBModeError("따로 연락 중인 분반입니다. 정한 자리를 POST /coord/{분반}/manual 로 넣으세요.")
        if st != "PROPOSED":
            raise DBModeError("아직 처리안이 없습니다. 답장을 먼저 넣으세요." if st in ("OPEN", "SENT")
                              else f"이번 차수에 이미 결정한 분반입니다 (상태 {st}).")
        mid, ex = self._latest_reply(pid)
        prop, parsed = ex.get("proposal") or {}, ex.get("parse") or {}
        cond = ex.get("conditions")
        has_cond = bool(cond and (cond.get("day_slots") or cond.get("end_before")))
        if action == "keep" or (action == "confirm" and prop.get("action") == "keep"):
            self.hdb.decide_reply(self.con, mid, self.ta_id, "KEEP", reason=reason)
            self._mark_done(sid)
            return dict(action="keep", applied=None)
        if action == "offline":
            self.hdb.decide_reply(self.con, mid, self.ta_id, "OFFLINE", reason=reason)
            return dict(action="offline", applied=None)
        if action == "edit":
            oid = self.option_id(pid, choice)
            if oid is None:
                raise DBModeError(f"{choice}안이 없습니다.")
            tt = self._apply(pid, mid, dict(action="EDIT", conditions=cond if has_cond else None), oid, reason)
            return dict(action="edit", applied=self._alt_dict(pid, oid), timetable_id=tt)
        # confirm
        if prop.get("action") == "next":
            self.hdb.decide_reply(self.con, mid, self.ta_id, "CONFIRM", reason=reason, conditions=cond,
                                  proposal_action="next")
            return dict(action="confirm_next", applied=cond)
        if prop.get("action") != "move":
            raise DBModeError(f"조교가 직접 정해야 하는 처리안입니다 (action={prop.get('action')}). "
                              "[수정]·[현재대로 유지]·[따로 연락]을 고르세요.")
        oid = self._pick(sid, pid, parsed, cond if has_cond else None)
        tt = self._apply(pid, mid, dict(action="CONFIRM", proposal_action="move", conditions=cond if has_cond else None),
                         oid, reason)
        return dict(action="confirm", applied=self._alt_dict(pid, oid), timetable_id=tt)

    def _pick(self, sid: str, pid: int, parsed: dict, cond: Optional[dict]) -> int:
        """교수가 고른 안 중 지금 놓을 수 있는 첫 안 (엔진 pick_best, 교수가 밝힌 순서 respect_order).
        기타 조건으로 엔진이 새 안을 만들었으면 그 안을 4번 대안으로 저장해 쓴다."""
        cid, sec = self.section_key(sid)
        picks = [k for k in parsed.get("picks", []) if self.option_id(pid, k)]
        oids = [self.option_id(pid, k) for k in picks]
        best = self.sc.pick_best(self.con, self.term_id, self.wish_round, self.current_tt(), cid, sec,
                                 option_ids=oids, condition=solver_condition(cond) if cond else None,
                                 time_limit=self.alt_time_limit, respect_order=bool(parsed.get("ordered")))
        ok = [b for b in best if b["feasible"]]
        if not ok:
            raise DBModeError("고른 안을 지금은 놓을 수 없습니다. [수정]·[현재대로 유지]·[따로 연락] 중에서 정해 주세요.")
        b = ok[0]
        return b["option_id"] if b.get("option_id") else self.sc.add_option(self.con, pid, b, source="ETC")

    def _alt_dict(self, pid: int, oid: int) -> dict:
        cid = self.q("SELECT course_id FROM proposal WHERE id=?", (pid,)).fetchone()[0]
        no = self.q("SELECT option_no FROM proposal_option WHERE id=?", (oid,)).fetchone()[0]
        alt = option_to_alternative(KEYS[min(no, 3) - 1], self.sc.load_option(self.con, oid), cid, self.slots, self.rooms)
        return dump(alt)

    def manual_place(self, sid: str, meetings: List[dict], reason: Optional[str]) -> Tuple[int, list]:
        """[따로 연락] 뒤 조교가 정한 자리 → 하윤 manual_place (고정). 규칙 위반은 경고로."""
        pid, st, _ = self._proposal_row(sid)
        cid, sec = self.section_key(sid)
        rows = []
        for ss, m in enumerate(sorted(meetings, key=lambda m: (m["day"], m["start"])), start=1):
            start = self.slots.id_of.get((DAYS[m["day"]], m["start"]))
            room = self.rooms.id_of.get(m["room"])
            if start is None or room is None:
                raise DBModeError(f"교시 시작이나 강의실이 아닙니다: {DAYS[m['day']]} {m['start']} {m['room']}")
            h0, m0 = map(int, m["start"].split(":"))
            h1, m1 = map(int, m["end"].split(":"))
            k = 1 if (h1 * 60 + m1) - (h0 * 60 + m0) <= 75 else 2
            rows += [(sec, ss, slot, room) for slot in self.slots.covered(start, k)]
        tt = self.hdb.manual_place(self.con, pid, self.ta_id, rows, lock=True)
        if reason:
            self.q("UPDATE timetable SET reason=? WHERE id=?", (reason, tt))
            self.con.commit()
        warn = [v for v in self.sc.check_timetable(self.con, tt) if v["course_id"] == cid and v["section_no"] == sec]
        return tt, warn

    # ---------- 차수·확정 ----------

    def next_round(self) -> Tuple[int, List[dict]]:
        stage, no = self.stage()
        if stage == "DRAFT":
            self.hdb.set_phase(self.con, self.term_id, "ROUND1", self.ta_id)
            return 1, []
        if stage != "ROUND":
            raise DBModeError(f"다음 차수로 갈 수 없는 단계입니다: {stage}")
        if no >= 3:
            raise DBModeError("최대 3차까지입니다. 남은 분반은 조교가 정해 확정(POST /finalize)하세요.")
        new_no = no + 1
        rid = self.round_id(new_no) or self.q(
            "INSERT INTO round(term_id, round_no, opened_at, deadline_at) VALUES (?,?,datetime('now'),date('now','+7 day'))",
            (self.term_id, new_no)).lastrowid
        self.con.commit()
        self.hdb.set_phase(self.con, self.term_id, PHASE_OF_ROUND[new_no], self.ta_id)
        opened, tt = [], self.current_tt()
        for prev, prev_no in self.pending_next(new_no):
            new, how = self._open_next(prev, prev_no, rid, new_no, tt)
            cond = self.hdb.carried_conditions(self.con, new)
            n = self._fill(new, cond)
            opened.append(dict(proposal_id=new, options=n, conditions=cond, from_round=prev_no, opened_by=how))
        return new_no, opened

    def pending_next(self, new_no: int) -> List[Tuple[int, int]]:
        """새 차수(new_no)가 이어받을 안건: 그 학기 이전 모든 차수에서 '다음 차수로'(NEXT)이면서 아직 다음 차수 안건으로
        이어지지 않은 것 (proposal.prev_proposal_id 로 가리키는 안건이 없음). 답장 대기 중에 차수를 넘긴 뒤 늦게 NEXT 가
        된 안건도 여기서 잡힌다. 같은 분반의 안건이 이미 새 차수에 있으면 뺀다. -> [(안건 id, 그 안건의 차수)]"""
        return [(pid, rno) for pid, rno in self.q(
            """SELECT p.id, r.round_no FROM proposal p JOIN round r ON r.id = p.round_id
               WHERE r.term_id=? AND r.round_no < ? AND p.status='NEXT'
                 AND NOT EXISTS (SELECT 1 FROM proposal n WHERE n.prev_proposal_id = p.id)
                 AND NOT EXISTS (SELECT 1 FROM proposal x JOIN round xr ON xr.id = x.round_id
                                 WHERE xr.term_id = r.term_id AND xr.round_no = ? AND x.course_id = p.course_id
                                   AND x.section_no IS p.section_no)
               ORDER BY p.id""", (self.term_id, new_no, new_no)).fetchall()]

    def _open_next(self, prev: int, prev_no: int, rid: int, new_no: int, tt: Optional[int]) -> Tuple[int, str]:
        """다음 차수 안건 열기. 바로 다음 차수면 하윤 db.open_next_proposal.
        차수를 건너뛴 경우(1차 안건이 늦게 NEXT → 3차)는 하윤 함수가 '바로 다음 차수가 아닙니다'로 막으므로, 같은 칸
        (과목·분반·이유·조율 대상 종류, OPEN, prev_proposal_id = 이전 안건)으로 서버가 직접 넣는다 (하윤에게 확인 요청)."""
        if new_no == prev_no + 1:
            return self.hdb.open_next_proposal(self.con, prev, rid, timetable_id=tt), "open_next_proposal"
        try:
            row = self.q("SELECT course_id, section_no, reason, target_kind, timetable_id FROM proposal WHERE id=?",
                         (prev,)).fetchone()
            new = self.q("""INSERT INTO proposal(round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id,
                                                  target_kind) VALUES (?,?,?,?,?, 'OPEN', ?, ?)""",
                         (rid, tt or row[4], row[0], row[1], row[2], prev, row[3])).lastrowid
            self.con.commit()
            return new, "server (차수 건너뜀)"
        except Exception:
            self.con.rollback()
            raise

    def _fill(self, pid: int, cond: Optional[dict]) -> int:
        """다음 차수 안건에 대안을 채운다. 희망은 1차 round 응답이라 alternatives 를 1차 round id 로 부르고
        add_option 으로 저장한다 (fill_options 는 안건 round 로 응답을 읽어 쓰지 않음). 없으면 NO_OPTION."""
        tt, cid, sec = self.q("SELECT timetable_id, course_id, section_no FROM proposal WHERE id=?", (pid,)).fetchone()
        opts = self.sc.alternatives(self.con, self.term_id, self.wish_round, tt, cid, sec, condition=cond, n=3,
                                    time_limit=self.alt_time_limit)
        for o in opts:
            self.sc.add_option(self.con, pid, o)
        if not opts:
            self.q("UPDATE proposal SET status='NO_OPTION' WHERE id=?", (pid,))
            self.con.commit()
        return len(opts)

    def finalize(self) -> int:
        tt = self.current_tt()
        if tt is None:
            raise DBModeError("아직 초안이 없습니다.")
        self.sc.finalize(self.con, tt)
        self.hdb.set_phase(self.con, self.term_id, "FINAL", self.ta_id, force=True)
        return tt

    def violations(self, tt: Optional[int] = None) -> list:
        tt = tt or self.current_tt()
        return self.sc.check_timetable(self.con, tt) if tt else []

    def view(self, con, tt: int, v: dict) -> dict:
        """하윤 check_timetable 위반 하나 → {rule, section_ids(서버 분반 id), detail(사람이 읽는 글)}.
        교수 겹침·교필↔전필·전필↔전필은 하윤 결과에 분반이 없어서(course_id/section_no=None) 관련 분반을 찾아 붙이고,
        detail 의 '교수 N'·'칸 N'·'강의실 N'·'과목 N' 번호를 가명·요일 시각·강의실·과목명으로 바꾼다."""
        d = v["detail"] or ""
        ids: List[str] = []
        if v.get("course_id") is not None and v.get("section_no") is not None:
            ids.append(self._sid(v["course_id"], v["section_no"]))
        elif v["rule"] == "교수 겹침":
            m = re.search(r"교수 (\d+) 칸 (\d+)", d)
            if m:
                prof, slot = int(m.group(1)), int(m.group(2))
                for cid, sec in con.execute(
                        """SELECT DISTINCT a.course_id, a.section_no FROM assignment a
                           JOIN course c ON c.id = a.course_id
                           LEFT JOIN course_section cs ON cs.course_id = a.course_id AND cs.section_no = a.section_no
                           WHERE a.timetable_id=? AND a.slot_id=? AND COALESCE(cs.professor_id, c.professor_id)=?""",
                        (tt, slot, prof)):
                    ids.append(self._sid(cid, sec))
        else:
            courses = [v["course_id"]] if v.get("course_id") is not None else []
            courses += [int(x) for x in re.findall(r"과목 (\d+)", d)]
            for cid in courses:
                ids += [self._sid(cid, sec) for (sec,) in con.execute(
                    "SELECT DISTINCT section_no FROM assignment WHERE timetable_id=? AND course_id=? ORDER BY 1", (tt, cid))]
        names = {i: n for n, i in self.prof_id.items()}
        cname = dict(con.execute("SELECT id, name FROM course"))

        def slot_text(m):
            info = self.slots.info.get(int(m.group(1)))
            return f"{info[0]} {info[2]}" if info else m.group(0)
        d = re.sub(r"교수 (\d+)", lambda m: names.get(int(m.group(1)), "담당 교수"), d)
        d = re.sub(r"(?:채플 )?칸 (\d+)", lambda m: ("채플 " if m.group(0).startswith("채플") else "") + slot_text(m), d)
        d = re.sub(r"강의실 (\d+)", lambda m: "강의실 " + self.rooms.name_of.get(int(m.group(1)), m.group(1)), d)
        d = re.sub(r"과목 (\d+)", lambda m: cname.get(int(m.group(1)), "다른 과목"), d)
        return dict(rule=v["rule"], section_ids=list(dict.fromkeys(ids)), detail=d)

    def violation_list(self, tt: Optional[int] = None) -> List[dict]:
        """지금 시간표 버전의 하드 규칙 위반 (하윤 check_timetable) → view 모양."""
        tt = tt or self.current_tt()
        return [self.view(self.con, tt, v) for v in self.violations(tt)] if tt else []

    def violations_after(self, sid: str, alt: Alternative) -> List[dict]:
        """그 분반을 대안 자리로 옮긴 '뒤' 시간표의 하드 규칙 위반 (view 모양). 진짜 DB는 그대로:
        메모리 복사본에 새 버전을 만들어 하윤 check_timetable 로 잰 뒤 버린다. 같은 칸·같은 강의실이면 '강의실 겹침' 하나."""
        tt = self.current_tt()
        if tt is None:
            return []
        cid, _ = self.section_key(sid)
        mem = sqlite3.connect(":memory:")
        try:
            self.con.backup(mem)
            mem.execute("PRAGMA foreign_keys = ON")
            rows = self.sc.option_rows(mem, option=self.adapter.option_of(sid, alt), timetable_id=tt)
            try:
                new = self.hdb.apply_option(mem, None, None, rows, "규칙 검사", course_id=cid, base_timetable_id=tt)
            except ValueError as e:
                return [dict(rule="강의실 겹침", section_ids=[sid], detail=str(e))]
            return [self.view(mem, new, v) for v in self.sc.check_timetable(mem, new)]
        finally:
            mem.close()

    def assistant_apply(self, sid: str, alt: Alternative, reason: str) -> int:
        """도우미 [적용]: 그 분반의 열린 안건이 있으면 그 안건으로, 없으면 안건 없이 새 시간표 버전."""
        self.adapter.actor_id, self.adapter.apply_reason = self.ta_id, reason
        self.adapter.timetable_id = self.current_tt()
        self.adapter.reassign(Timetable(assignments=[]), sid, alt)
        return self.current_tt()

    # ---------- 가정 실행 (AI 도우미) ----------

    def what_if(self, change: dict) -> dict:
        """가정 실행. 지금 DB를 메모리 DB로 복사(sqlite3 backup)해 그 복사본에서만 하윤 함수로 계산하고 버린다.
        진짜 DB에는 아무것도 쓰지 않는다. change 모양은 stubs.what_if 와 같다:
          {"kind": "move", "section_id", "blocks": [{day, start, slots, room}]}   분반을 그 자리로
          {"kind": "room_off", "room": "정보과학관 21303"}                       그 강의실을 못 쓰면
          {"kind": "free", "day": "수", "start": "15:00"}                        그 칸을 비우면
        -> {supported, changed, violations(새로 생긴 위반 수), rules, moved, unplaced, feasible, option, engine, note}
           supported=False 면 note 에 이유 (지어내지 않는다)."""
        tt = self.current_tt()
        if tt is None:
            return _unsupported("아직 초안이 없어 계산할 수 없어요.")
        mem = sqlite3.connect(":memory:")
        try:
            self.con.backup(mem)
            mem.execute("PRAGMA foreign_keys = ON")
            kind = change.get("kind", "move")
            if kind == "move":
                return self._what_move(mem, tt, change)
            if kind == "room_off":
                return self._what_room_off(mem, tt, change.get("room"))
            if kind == "free":
                return self._what_free(mem, tt, change.get("day"), change.get("start"))
            return _unsupported("이 가정은 아직 계산할 수 없어요.")
        finally:
            mem.close()

    def _new_violations(self, mem, base: int, new: int) -> List[dict]:
        key = lambda v: (v["rule"], v["course_id"], v["section_no"], v["detail"])   # noqa: E731
        before = [key(v) for v in self.sc.check_timetable(mem, base)]
        out = []
        for v in self.sc.check_timetable(mem, new):
            if key(v) in before:
                before.remove(key(v))
            else:
                out.append(v)
        return out

    def _sid(self, cid: int, sec: int) -> str:
        return self.pairs.sid_of.get((cid, sec), f"{cid}-{sec}")

    def _rule_text(self, v: dict, con=None, tt: Optional[int] = None) -> dict:
        x = self.view(con or self.con, tt or self.current_tt(), v)
        return dict(rule=x["rule"], section_id=x["section_ids"][0] if x["section_ids"] else None,
                    section_ids=x["section_ids"], detail=x["detail"])

    def _moved(self, mem, base: int, new: int, keys) -> Tuple[List[dict], List[str]]:
        """두 시간표 버전에서 그 분반들의 자리 비교 → (옮겨진 분반 [{section_id, before, after}], 못 놓인 분반 id)."""
        b_start, b_ks = self.sc.load_assignment(mem, base)
        n_start, n_ks = self.sc.load_assignment(mem, new)
        b = assignments_from_db(b_start, b_ks, self.slots, self.rooms, self.pairs)
        n = assignments_from_db(n_start, n_ks, self.slots, self.rooms, self.pairs)
        moved, unplaced = [], []
        for cid, sec in sorted(keys):
            sid = self._sid(cid, sec)
            nb = n.get(sid)
            if nb is None or len(nb.blocks) < len(b[sid].blocks if sid in b else []):
                unplaced.append(sid)
                continue
            if sid in b and dump(b[sid]) != dump(nb):
                moved.append(dict(section_id=sid, before=_place(b[sid]), after=_place(nb)))
        return moved, unplaced

    def _what_move(self, mem, tt: int, change: dict) -> dict:
        sid = change.get("section_id")
        if sid not in self.pairs.key_of:
            return _unsupported("조교 직접 배정 분반이거나 DB에 없는 분반이라 계산할 수 없어요.")
        cid, sec = self.section_key(sid)
        rows, day_slots = [], {}
        blocks = sorted(change.get("blocks") or [], key=lambda b: (DAYS.index(b["day"]) if b["day"] in DAYS else 9, b["start"]))
        for ss, b in enumerate(blocks, start=1):
            start = self.slots.id_of.get((b["day"], b["start"]))
            room = self.rooms.id_of.get(b.get("room") or "")
            if start is None or room is None:
                return _unsupported("교시 시작이 아니거나 DB에 없는 강의실이라 이 가정은 아직 계산할 수 없어요.")
            cells = self.slots.covered(start, b["slots"])
            if len(cells) < b["slots"]:
                return _unsupported("그 시각에서는 연강 두 칸이 이어지지 않아 계산할 수 없어요.")
            rows += [(sec, ss, c, room) for c in cells]
            day_slots.setdefault(str(DAYS.index(b["day"])), []).extend(self.slots.info[c][2] for c in cells)
        if not rows:
            return _unsupported("옮길 자리가 없어 계산할 수 없어요.")
        # (1) 그 칸·그 강의실에 그대로 놓아 본다 (규칙 검사 없이 복사본에 새 버전) → 새로 생기는 위반
        rules, clash = [], None
        try:
            new = self.hdb.apply_option(mem, None, None, rows, "가정 실행", course_id=cid, base_timetable_id=tt)
            rules = self._new_violations(mem, tt, new)
        except ValueError as e:
            clash = "같은 시간에 그 강의실을 다른 수업이 쓰고 있어요." if "강의실" in str(e) else str(e)
            new = None
        # (2) 규칙을 지키며 그 요일·교시에 놓는 안이 있는지 (엔진 alternatives, 강의실은 엔진이 고름, 필요하면 다른 수업도 조금 움직임)
        cond = {"day_slots": {d: sorted(set(v)) for d, v in day_slots.items()}, "end_before": []}
        opts = self.sc.alternatives(mem, self.term_id, self.wish_round, tt, cid, sec, condition=cond, n=1,
                                    time_limit=self.alt_time_limit, exclude_sent=False)
        option = None
        if opts:
            o = opts[0]
            alt = option_to_alternative("A", o, cid, self.slots, self.rooms)
            option = dict(alternative=dump(alt), stage=o["stage"],
                          moves=[dict(section_id=self._sid(k[0], k[1]), before=self._cell(*b), after=self._cell(*a))
                                 for k, b, a in o["moves"]])
        texts = [self._rule_text(v, mem, new) for v in rules]
        changed = [sid] + sorted({x for r in texts for x in r["section_ids"]} - {sid})
        if option:
            changed += [m["section_id"] for m in option["moves"] if m["section_id"] not in changed]
        return dict(supported=True, kind="move", feasible=new is not None and not rules, clash=clash,
                    changed=changed, violations=len(rules), rules=texts,
                    moved=[], unplaced=[], option=option, engine="하윤 엔진(복사본에서 계산)", note="")

    def _cell(self, slot: int, room: int) -> str:
        d, _p, st, _e = self.slots.info[slot]
        return f"{d} {st} {self.rooms.name_of.get(room, room)}"

    def _resolve(self, mem, tt: int, keys) -> dict:
        """복사본에서 그 분반들만 다시 푼다 (나머지는 그대로 고정, 엔진 solve 부분 재풀이)."""
        r = self.sc.solve(mem, self.term_id, self.wish_round, time_limit=self.alt_time_limit,
                          previous_timetable_id=tt, free_courses=set(keys))
        new = r.get("timetable_id")
        if new is None:
            return _unsupported(f"다시 풀지 못했어요 (엔진 상태 {r.get('status')}).")
        moved, unplaced = self._moved(mem, tt, new, keys)
        rules = self._new_violations(mem, tt, new)
        changed = [self._sid(c, s) for c, s in sorted(keys)]
        return dict(supported=True, feasible=not unplaced and not rules, clash=None, changed=changed,
                    violations=len(rules), rules=[self._rule_text(v, mem, new) for v in rules], moved=moved, unplaced=unplaced,
                    option=None, engine="하윤 엔진(복사본에서 계산)", note="")

    def _what_room_off(self, mem, tt: int, room: Optional[str]) -> dict:
        rid = self.rooms.id_of.get(room or "")
        if rid is None:
            return _unsupported(f"DB에 없는 강의실이라 계산할 수 없어요: {room}")
        keys = {(c, s) for c, s in mem.execute("SELECT DISTINCT course_id, section_no FROM assignment "
                                                 "WHERE timetable_id=? AND room_id=?", (tt, rid))}
        locked = {(c, s) for c, s in mem.execute("SELECT course_id, section_no FROM timetable_section "
                                                   "WHERE timetable_id=? AND locked=1", (tt,))}
        if keys & locked:
            return _unsupported("그 강의실에 조교가 고정한 분반이 있어 계산할 수 없어요. 고정을 먼저 풀어 주세요.")
        if not keys:
            return dict(supported=True, kind="room_off", feasible=True, clash=None, changed=[], violations=0, rules=[],
                        moved=[], unplaced=[], option=None, engine="하윤 엔진(복사본에서 계산)", note="그 강의실을 쓰는 분반이 없어요.")
        # 그 강의실을 어느 학과도 못 쓰게: 없는 학과 전용으로 바꾼다 (엔진의 전용 강의실 규칙)
        dept = mem.execute("INSERT INTO department(name) VALUES ('가정 실행: 사용 불가')").lastrowid
        mem.execute("UPDATE room SET reserved_department_id=? WHERE id=?", (dept, rid))
        mem.commit()
        return dict(self._resolve(mem, tt, keys), kind="room_off")

    def _what_free(self, mem, tt: int, day: Optional[str], start: Optional[str]) -> dict:
        slot = self.slots.id_of.get((day, start))
        if slot is None:
            return _unsupported("교시 시작 칸이 아니라 계산할 수 없어요.")
        keys = {(c, s) for c, s in mem.execute("SELECT DISTINCT course_id, section_no FROM assignment "
                                                 "WHERE timetable_id=? AND slot_id=?", (tt, slot))}
        if not keys:
            return dict(supported=True, kind="free", feasible=True, clash=None, changed=[], violations=0, rules=[],
                        moved=[], unplaced=[], option=None, engine="하윤 엔진(복사본에서 계산)", note="그 칸에는 수업이 없어요.")
        # 그 칸을 그 분반 담당 교수 응답의 불가 칸으로 → 그 분반들만 다시 푼다
        for cid, sec in keys:
            row = mem.execute("""SELECT r.id FROM course_response r JOIN course_section cs ON cs.course_id = r.course_id
                                 AND cs.section_no = r.section_no AND cs.professor_id = r.professor_id
                                 WHERE r.round_id=? AND r.course_id=? AND r.section_no=?""",
                              (self.wish_round, cid, sec)).fetchone()
            if row is None:
                return _unsupported("그 칸에 희망 입력이 없는 분반(미회신)이 있어 아직 계산할 수 없어요.")
            mem.execute("INSERT OR REPLACE INTO response_slot(response_id, slot_id, kind) VALUES (?,?, 'BLOCK')",
                        (row[0], slot))
        mem.commit()
        return dict(self._resolve(mem, tt, keys), kind="free")

    # ---------- 처음으로 ----------

    def reset(self) -> None:
        """조율·시간표 기록을 지우고 희망 수집 단계로 (희망 입력·과목·강의실은 그대로)."""
        q = self.q
        try:
            q("DELETE FROM other_request WHERE message_id IS NOT NULL")
            q("DELETE FROM reply_choice")
            q("DELETE FROM reply_interpretation")
            q("UPDATE message SET reply_to_id=NULL")
            q("DELETE FROM message")
            q("DELETE FROM proposal_option_slot")
            q("DELETE FROM proposal_option")
            q("UPDATE proposal SET prev_proposal_id=NULL")
            q("DELETE FROM proposal")
            q("DELETE FROM assignment")
            q("DELETE FROM timetable_section")
            q("UPDATE timetable SET parent_id=NULL")
            q("DELETE FROM timetable")
            q("DELETE FROM solver_run")
            q("DELETE FROM round_invite WHERE round_id IN (SELECT id FROM round WHERE term_id=? AND round_no>1)", (self.term_id,))
            q("DELETE FROM round WHERE term_id=? AND round_no>1", (self.term_id,))
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise
        if self.phase() != "COLLECTING":
            self.hdb.set_phase(self.con, self.term_id, "COLLECTING", self.ta_id, force=True)
        self.adapter.timetable_id = None


def parse_conditions(c):
    if not c:
        return None
    from .contracts import Conditions
    return parse(Conditions, c)


_DB: Optional[DBMode] = None


def active() -> Optional[DBMode]:
    """DB 모드면 DBMode, 아니면 None. SSUROOM_ENGINE=solver 일 때 처음 부를 때 연다."""
    global _DB
    if not engine.use_solver():
        return None
    if _DB is None:
        _DB = DBMode.from_files()
    return _DB


def use(db: Optional[DBMode]) -> None:
    """테스트용: 이미 만든 DBMode 를 쓴다 (None 이면 다시 파일에서 연다)."""
    global _DB
    _DB = db


def _unsupported(note: str) -> dict:
    return dict(supported=False, feasible=False, clash=None, changed=[], violations=0, rules=[], moved=[], unplaced=[],
                option=None, engine="하윤 엔진(복사본에서 계산)", note=note)


def _place(a) -> str:
    """배정 → '화 13:30 정보과학관 21303 / 목 13:30 …'."""
    return " / ".join(f"{b.day} {b.start} {b.room or ''}".strip() for b in a.blocks) or "자리 없음"
