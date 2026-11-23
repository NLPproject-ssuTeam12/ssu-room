"""AI 도우미 평가 스크립트 (백엔드 3). 정답 라벨은 이 스크립트만 읽는다. 서비스 코드(backend/app)는 읽지 않는다.

저장소 맨 위에서 실행한다.

  python eval/run_assistant.py --method keyword
  python eval/run_assistant.py --method llm
  python eval/run_assistant.py --method llm --labels eval/labels/assistant_questions_daewon.csv

지표
- 의도 정확도: intent가 맞은 비율
- 정보 F1: 분반·교수·요일·시작 시각·강의실·건물을 (칸, 값) 항목으로 보고 정답 항목과 비교 (micro). 칸별 F1도 출력
- 되묻기 정확도: 물어야 할 때 물었나 + 안 물어야 할 때 안 물었나. 둘을 따로도 출력

라벨 파일 (eval/labels/assistant_questions_*.csv, UTF-8)
  id,history,question,writer,intent,section,professor,days,start,room,building,ask_back,memo
- intent가 빈 줄은 아직 라벨이 없는 것으로 보고 건너뛴다 (몇 줄인지 출력)
- history: 앞 대화. 여러 줄이면 '|'로 나눈다. '도우미:'로 시작하면 도우미 말, 아니면 조교 말
- section: "과목명 02" (재수강 분반이면 "과목명 03 재수강"), 분반 id, 과목 코드 10자리 중 하나. 빈칸 = 정해지지 않음
- professor: "교수03" / days: "월·수", "월수", "월,수" / start: "13:30" / room: "21303" 또는 "정보과학관 21303"
- ask_back: Y/N (1/0, 예/아니오, O/X, true/false도 받음). 빈칸이면 N
결과: eval/results/assistant_{method}_{날짜시각}.csv / .json
"""
import argparse
import csv
import datetime as dt
import glob
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIELDS = ["section", "professor", "days", "start", "room", "building"]
INTENTS = ["explain", "move", "what_if", "status", "out_of_scope"]
YES = {"y", "yes", "1", "예", "네", "o", "true", "t"}
NO = {"", "n", "no", "0", "아니오", "아니요", "x", "false", "f"}
DAY_CHARS = "월화수목금"


# ---------------- 파일 읽기 ----------------
def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def parse_history(text: str) -> list[dict]:
    out = []
    for part in (p.strip() for p in (text or "").split("|")):
        if not part:
            continue
        if part.startswith("도우미:"):
            out.append({"role": "assistant", "text": part[len("도우미:"):].strip()})
        else:
            out.append({"role": "user", "text": re.sub(r"^조교:\s*", "", part)})
    return out


def parse_yes(v: str) -> bool:
    v = (v or "").strip().lower()
    if v in YES:
        return True
    if v in NO:
        return False
    raise ValueError(f"ask_back 값을 모름: {v!r}")


# ---------------- 정답·예측을 같은 모양으로 ----------------
class Normalizer:
    def __init__(self, store):
        from backend.app.nlp.assistant import BUILDING_ALIAS
        self.alias = BUILDING_ALIAS
        self.sections = store.list_sections()
        self.ids = {s.id for s in self.sections}
        self.rooms = {r.id: r.room_no for r in store.list_rooms()}

    @staticmethod
    def _n(t: str) -> str:
        return re.sub(r"\s+", "", t or "").lower()

    def section(self, v: str):
        """정답 section 칸 → 분반 id (못 찾으면 '?' + 원문, 비교에서 틀림으로 센다)."""
        v = (v or "").strip()
        if not v:
            return None
        if v in self.ids:
            return v
        code = re.fullmatch(r"\d{10}", v)
        if code:
            hits = [s.id for s in self.sections if s.code == v]
            return hits[0] if len(hits) == 1 else f"?{v}"
        retake = "재수강" in v
        m = re.search(r"(\d{1,2})\s*(분반|반)?\s*(재수강)?\s*$", v)
        num = f"{int(m.group(1)):02d}" if m else None
        name = self._n(v[:m.start()] if m else v.replace("재수강", ""))
        hits = [s for s in self.sections if self._n(s.name) == name
                and (num is None or s.code[-2:] == num)
                and (not retake or (s.division and "재수강" in s.division))]
        return hits[0].id if len(hits) == 1 else f"?{v}"

    @staticmethod
    def days(v) -> list[str]:
        if isinstance(v, list):
            return [d for d in DAY_CHARS if d in v]
        return [d for d in DAY_CHARS if d in (v or "")]

    @staticmethod
    def start(v):
        v = (v or "").strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else (v or None)

    @staticmethod
    def room(v):
        m = re.search(r"\d{5}", v or "")
        return m.group(0) if m else ((v or "").strip() or None)

    def building(self, v):
        v = self._n(v)
        if not v:
            return None
        return next((b for a, b in self.alias.items() if self._n(a) == v), v)

    def gold(self, r: dict) -> dict:
        return {"section": self.section(r.get("section")), "professor": (r.get("professor") or "").replace(" ", "") or None,
                "days": self.days(r.get("days")), "start": self.start(r.get("start")),
                "room": self.room(r.get("room")), "building": self.building(r.get("building"))}

    def pred(self, q) -> dict:
        return {"section": q.section_id, "professor": q.professor, "days": self.days(q.days),
                "start": q.start, "room": self.rooms.get(q.room, q.room) if q.room else None,
                "building": self.building(q.building or "")}


def items(info: dict) -> set:
    """(칸, 값) 항목. 요일은 요일마다 한 항목."""
    out = set()
    for f in FIELDS:
        v = info.get(f)
        if f == "days":
            out |= {("days", d) for d in v or []}
        elif v:
            out.add((f, v))
    return out


def f1(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


# ---------------- 평가 ----------------
def evaluate(rows: list[dict], method: str, store) -> tuple[list[dict], dict]:
    from backend.app.nlp.assistant import read_question
    norm = Normalizer(store)
    out, skipped = [], 0
    tp = fp = fn = 0
    per = {f: [0, 0, 0] for f in FIELDS}
    ask_tp = ask_fn = noask_tn = noask_fp = 0
    intent_ok, fallbacks = 0, 0
    confusion = Counter()
    for r in rows:
        if not r.get("question") or not r.get("intent"):
            skipped += 1
            continue
        if r["intent"] not in INTENTS:
            raise ValueError(f"{r.get('id')}: intent 값을 모름: {r['intent']!r}")
        q = read_question(r["question"], parse_history(r.get("history", "")), store, method=method)
        g, p = norm.gold(r), norm.pred(q)
        gi, pi = items(g), items(p)
        tp, fp, fn = tp + len(gi & pi), fp + len(pi - gi), fn + len(gi - pi)
        for f in FIELDS:
            gf, pf = {x for x in gi if x[0] == f}, {x for x in pi if x[0] == f}
            per[f][0] += len(gf & pf)
            per[f][1] += len(pf - gf)
            per[f][2] += len(gf - pf)
        g_ask, p_ask = parse_yes(r.get("ask_back", "")), bool(q.ask_back)
        if g_ask:
            ask_tp, ask_fn = ask_tp + p_ask, ask_fn + (not p_ask)
        else:
            noask_tn, noask_fp = noask_tn + (not p_ask), noask_fp + p_ask
        intent_ok += q.intent == r["intent"]
        confusion[(r["intent"], q.intent)] += 1
        fallbacks += bool(getattr(q, "fallback", False))
        out.append({
            "id": r.get("id", ""), "question": r["question"],
            "gold_intent": r["intent"], "pred_intent": q.intent, "intent_ok": q.intent == r["intent"],
            "gold_info": "; ".join(f"{k}={v}" for k, v in sorted(gi)),
            "pred_info": "; ".join(f"{k}={v}" for k, v in sorted(pi)),
            "missed": "; ".join(f"{k}={v}" for k, v in sorted(gi - pi)),
            "extra": "; ".join(f"{k}={v}" for k, v in sorted(pi - gi)),
            "gold_ask": g_ask, "pred_ask": p_ask, "ask_ok": g_ask == p_ask, "ask_back": q.ask_back or "",
            "fallback": bool(getattr(q, "fallback", False)), "fallback_reason": getattr(q, "fallback_reason", None) or "",
        })
    n = len(out)
    should, shouldnt = ask_tp + ask_fn, noask_tn + noask_fp
    summary = {
        "method": method, "rows": n, "skipped": skipped, "fallback": fallbacks,
        "intent_accuracy": round(intent_ok / n, 3) if n else None,
        "info": f1(tp, fp, fn),
        "info_by_field": {f: f1(*per[f]) for f in FIELDS},
        "ask_back": {
            "accuracy": round((ask_tp + noask_tn) / n, 3) if n else None,
            "asked_when_needed": f"{ask_tp}/{should}", "asked_when_needed_rate": round(ask_tp / should, 3) if should else None,
            "quiet_when_not_needed": f"{noask_tn}/{shouldnt}",
            "quiet_when_not_needed_rate": round(noask_tn / shouldnt, 3) if shouldnt else None,
        },
        "intent_confusion": {f"{g}->{p}": c for (g, p), c in sorted(confusion.items()) if g != p},
    }
    return out, summary


def print_summary(s: dict, files: list[str]) -> None:
    print(f"라벨 파일: {', '.join(files) or '(없음)'}")
    print(f"방식: {s['method']}  평가한 줄: {s['rows']}  건너뛴 줄(라벨 없음): {s['skipped']}"
          + (f"  키워드로 대신 처리: {s['fallback']}" if s["method"] == "llm" else ""))
    if not s["rows"]:
        print("평가할 줄이 없습니다. intent 칸을 채운 뒤 다시 돌리세요.")
        return
    print(f"의도 정확도: {s['intent_accuracy']}")
    i = s["info"]
    print(f"정보 F1: {i['f1']} (정밀도 {i['precision']}, 재현율 {i['recall']}, tp {i['tp']} fp {i['fp']} fn {i['fn']})")
    for f, v in s["info_by_field"].items():
        print(f"  {f:9s} F1 {v['f1']}  (tp {v['tp']} fp {v['fp']} fn {v['fn']})")
    a = s["ask_back"]
    print(f"되묻기 정확도: {a['accuracy']}  물어야 할 때 물음 {a['asked_when_needed']}  "
          f"안 물어야 할 때 안 물음 {a['quiet_when_not_needed']}")
    if s["intent_confusion"]:
        print("틀린 의도 (정답->예측): " + ", ".join(f"{k} {v}" for k, v in s["intent_confusion"].items()))


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="AI 도우미 평가 (키워드/언어 모델)")
    ap.add_argument("--method", choices=["keyword", "llm"], default="keyword")
    ap.add_argument("--labels", nargs="*", help="라벨 CSV (기본: eval/labels/assistant_questions_*.csv 전부)")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results"), help="결과 폴더")
    args = ap.parse_args(argv)

    files = args.labels or sorted(glob.glob(str(ROOT / "eval" / "labels" / "assistant_questions_*.csv")))
    rows = [r for f in files for r in read_csv(f)]

    from backend.app.store import store
    out, summary = evaluate(rows, args.method, store)
    summary["labels"] = [str(pathlib.Path(f).name) for f in files]
    print_summary(summary, summary["labels"])

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    d = pathlib.Path(args.out)
    d.mkdir(parents=True, exist_ok=True)
    base = d / f"assistant_{args.method}_{stamp}"
    cols = ["id", "question", "gold_intent", "pred_intent", "intent_ok", "gold_info", "pred_info", "missed", "extra",
            "gold_ask", "pred_ask", "ask_ok", "ask_back", "fallback", "fallback_reason"]
    with open(f"{base}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    pathlib.Path(f"{base}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {base}.csv, {base}.json")
    summary["files"] = [f"{base}.csv", f"{base}.json"]
    return summary


if __name__ == "__main__":
    main()
