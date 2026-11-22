"""조율 NLP 평가 스크립트 (백엔드 2). 정답 라벨은 이 스크립트만 읽는다. 서비스 코드는 읽지 않는다.

저장소 맨 위에서 실행한다.

  # 회신 해석: 방식별 지표 (결과는 eval/results/에 남는다)
  python eval/run_coord.py reply --method keyword
  python eval/run_coord.py reply --method llm
  python eval/run_coord.py reply --method llm --split dev    # 프롬프트 고칠 때는 dev 16개만 본다
  python eval/run_coord.py reply --method llm --split new    # 최종 숫자: 규칙을 정한 뒤 받은 새 답장 (한 번만 돌린다)

  # 두 사람 라벨 일치도 (카파)와 서로 다른 문장 목록
  python eval/run_coord.py agree eval/labels/gold_a.csv eval/labels/gold_b.csv

  # 조율 메시지: 자동 검사 결과 + 사람이 점수 매길 표(CSV)
  python eval/run_coord.py message --method llm --repeat 3

파일 모양은 docs/planning/라벨링_가이드_회신.md를 본다.
- eval/scenarios.json        가상 조율 상황 (대안 A·B·C)
- eval/labels/replies.csv    답장 문장 (사람이 쓴다. 언어 모델로 만들지 않는다)
- eval/labels/gold.csv       최종 정답 (두 사람이 따로 단 뒤 맞춰서 만든다)
"""
import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.nlp import llm  # noqa: E402
from app.nlp.coord import SLOT_WORDS, check_message, match_conditions, parse_reply, write_message  # noqa: E402
from app.nlp.coord_models import (DAYN, SLOTS, Alternative, Conditions, EndBefore, MessageInput,  # noqa: E402
                                  ReplyParse)

EVAL = ROOT / "eval"
KINDS = ["수용", "조건부", "거절", "확인 필요"]
# 받아들임 여부: 수용·조건부는 고른 안으로 옮기고, 거절·확인 필요는 시간을 확정하지 않는다.
# 이 둘을 헷갈리는 것이 비싼 오류다 (11/22, 결과를 본 뒤 보조 지표로 추가)
ACCEPT = ("수용", "조건부")


# ---------------- 파일 읽기 ----------------
def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def load_scenarios() -> dict:
    data = json.loads((EVAL / "scenarios.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["scenarios"]}


def scenario_input(s: dict) -> MessageInput:
    keep = {k: v for k, v in s.items() if k in MessageInput.model_fields}
    return MessageInput(**keep)


def parse_days(v: str) -> list[int]:
    return sorted({DAYN.index(c) for c in v if c in DAYN})


def _m(t: str) -> int:
    h, mm = t.split(":")
    return int(h) * 60 + int(mm)


def parse_slots(v: str) -> list[str]:
    """되는 교시. '오후' / '10:30, 15:00' / '15:00-20:45'(그 안에 다 들어가는 교시) / '15:00 이후'를 섞어 써도 된다."""
    out = []
    for tok in filter(None, (t.strip() for t in re.split(r"[,;/]", v))):
        if tok in SLOT_WORDS:
            out += SLOT_WORDS[tok]
            continue
        m = re.fullmatch(r"(\d{1,2}:\d{2})\s*[-~]\s*(\d{1,2}:\d{2})", tok)
        if m:
            a, b = (_m(x) for x in m.groups())
            out += [s for s in SLOTS if a <= _m(s) and _m(s) + 75 <= b]
            continue
        m = re.fullmatch(r"(\d{1,2}:\d{2})\s*(이후|~)", tok)
        if m:
            out += [s for s in SLOTS if _m(s) >= _m(m.group(1))]
            continue
        t = re.sub(r"^(\d{1,2}:\d{2}):\d{2}$", r"\1", tok).zfill(5)   # 시트가 '9:00:00'으로 내보내는 경우
        if t not in SLOTS:
            raise ValueError(f"교시 형식: {tok!r} (예: 오후 / 10:30, 15:00 / 15:00 이후). 교시는 {', '.join(SLOTS)}")
        out.append(t)
    return out


def parse_end(v: str) -> list[EndBefore]:
    out = []
    for part in filter(None, (p.strip() for p in re.split(r"[;,]", v))):
        m = re.fullmatch(r"([월화수목금])\s*(\d{1,2}:\d{2})", part)
        if not m:
            raise ValueError(f"종료 조건 형식: {part!r} (예: 수 17:00)")
        out.append(EndBefore(day=DAYN.index(m.group(1)), time=m.group(2).zfill(5)))
    return out


def parse_day_slots(v: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for part in filter(None, (p.strip() for p in v.split(";"))):
        if "=" not in part:
            raise ValueError(f"요일별 교시 형식: {part!r} (예: 화=오전; 목=13:30,15:00)")
        d, s = part.split("=", 1)
        days, slots = parse_days(d), parse_slots(s)
        if not days:
            raise ValueError(f"요일이 없음: {part!r}")
        for day in days:
            out[day] = slots
    return out


def gold_row(r: dict) -> ReplyParse:
    """라벨 CSV 한 줄 → ReplyParse. 형식이 틀리면 어느 줄인지 알려 주고 멈춘다."""
    try:
        if r["kind"] not in KINDS:
            raise ValueError(f"kind는 {KINDS} 중 하나: {r['kind']!r}")
        picks = [p for p in re.split(r"[,\s]+", r.get("picks", "").upper()) if p]
        if r.get("day_slots"):      # 요일마다 다른 교시: "화=오전; 목=13:30,15:00" (교시를 비우면 그 요일은 아무 교시나)
            ds = parse_day_slots(r["day_slots"])
        else:                       # days × slots (교시만 있으면 다섯 요일 모두)
            days, slots = parse_days(r.get("days", "")), parse_slots(r.get("slots", r.get("window", "")))
            ds = {d: slots for d in (days or (range(5) if slots else []))}
        cond = Conditions(day_slots=ds, end_before=parse_end(r.get("end_before", "")))
        return ReplyParse(kind=r["kind"], picks=picks, conditions=cond)
    except Exception as e:
        sys.exit(f"라벨 형식 오류 (id={r.get('id')}): {e}")


def load_gold(path) -> dict[str, ReplyParse]:
    return {r["id"]: gold_row(r) for r in read_csv(path)}


# ---------------- 비교 ----------------
def cond_items(c: Conditions) -> set:
    """조건 F1을 셀 항목: (요일, 교시) 짝, 아무 교시나 되는 요일, 요일별 종료 시각. (11/22 요일별 교시로 바뀌며 짝 단위로 셈)"""
    items = {("end", e.day, e.time) for e in c.end_before}
    for d, slots in c.day_slots.items():
        items |= {("slot", d, s) for s in slots} if slots else {("day", d)}
    return items


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def show(p: ReplyParse) -> str:
    c = p.conditions
    bits = [p.kind, "".join(p.picks) or "-"]
    groups: dict[tuple, list[int]] = {}
    for d, s in c.day_slots.items():
        groups.setdefault(tuple(s), []).append(d)
    for s, days in groups.items():
        bits.append("".join(DAYN[d] for d in days) + (" " + "·".join(s) if s else " 아무 교시"))
    bits += [f"{DAYN[e.day]} {e.time} 전" for e in c.end_before]
    return " / ".join(bits)


# ---------------- reply ----------------
def cmd_reply(a):
    if a.method == "llm":
        os.environ.setdefault("LLM_RETRIES", "3")
    sc = load_scenarios()
    replies = read_csv(a.replies)
    if a.split != "all":
        split = {r["id"]: r["split"] for r in read_csv(a.split_file)}
        replies = [r for r in replies if split.get(r["id"]) == a.split]
        print(f"{a.split} 문장 {len(replies)}개만 평가")
    gold = load_gold(a.gold)
    missing = [r["id"] for r in replies if r["id"] not in gold]
    if missing:
        print(f"정답이 없는 문장 {len(missing)}개는 건너뜀: {', '.join(missing[:10])}")
    rows, kinds, conf = [], Counter(), Counter()
    tp = fp = fn = 0
    for r in replies:
        if r["id"] not in gold:
            continue
        s = sc[r["scenario"]]
        inp = scenario_input(s)
        alts = inp.alternatives
        choice = r.get("choice") or None
        t0 = time.time()
        msg = write_message(inp).text            # 답장이 붙는 메시지는 틀 문장으로 고정 (평가 대상은 해석)
        pred = parse_reply(r["reply"], choice, alternatives=alts, message=msg, method=a.method)
        sec = time.time() - t0
        g = gold[r["id"]]
        gi, pi = cond_items(g.conditions), cond_items(pred.conditions)
        tp, fp, fn = tp + len(gi & pi), fp + len(pi - gi), fn + len(gi - pi)
        conf[(g.kind, pred.kind)] += 1
        pg = match_conditions(g, alts, round=inp.round)
        pp = match_conditions(pred, alts, round=inp.round)
        row = dict(id=r["id"], scenario=r["scenario"], reply=r["reply"], choice=choice or "",
                   gold=show(g), pred=show(pred),
                   kind_ok=g.kind == pred.kind, picks_ok=g.picks == pred.picks, cond_ok=gi == pi,
                   accept_ok=(g.kind in ACCEPT) == (pred.kind in ACCEPT),
                   action_ok=(pg.action, pg.key) == (pp.action, pp.key),
                   danger=g.kind in ("거절", "확인 필요") and pred.kind in ("수용", "조건부"),
                   fallback=pred.fallback, fallback_reason=pred.fallback_reason, seconds=round(sec, 2))
        row["all_ok"] = row["kind_ok"] and row["picks_ok"] and row["cond_ok"]
        rows.append(row)
        kinds[g.kind] += 1
    if not rows:
        sys.exit("평가할 문장이 없습니다. eval/labels/replies.csv와 gold.csv를 채워 주세요.")

    n = len(rows)
    rate = lambda k: sum(r[k] for r in rows) / n  # noqa: E731
    p, rc, f1 = prf(tp, fp, fn)
    model = os.getenv("GEMINI_MODEL", llm.DEFAULT_MODEL) if a.method == "llm" else "-"
    summary = {
        "method": a.method, "model": model, "n": n, "정답 분포": dict(kinds),
        "판정 정확도": round(rate("kind_ok"), 3),
        "받아들임 여부 정확도(수용·조건부 vs 거절·확인 필요)": round(rate("accept_ok"), 3),
        "고른 안 일치(순서 포함)": round(rate("picks_ok"), 3),
        "조건 정밀도": round(p, 3), "조건 재현율": round(rc, 3), "조건 F1": round(f1, 3),
        "전부 일치": round(rate("all_ok"), 3),
        "처리안 일치(match_conditions)": round(rate("action_ok"), 3),
        "위험 오류(거절·확인 필요 → 수용·조건부)": sum(r["danger"] for r in rows),
        "키워드로 넘어간 건수": sum(r["fallback"] for r in rows),
        "평균 처리 시간(초)": round(sum(r["seconds"] for r in rows) / n, 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n혼동 행렬 (행 = 정답, 열 = 예측)")
    print("          " + "".join(f"{k:>8}" for k in KINDS))
    for g in KINDS:
        print(f"{g:>8}  " + "".join(f"{conf[(g, q)]:>8}" for q in KINDS))
    wrong = [r for r in rows if not r["all_ok"]]
    if wrong:
        print(f"\n틀린 문장 {len(wrong)}개")
        for r in wrong[: a.show]:
            print(f"- [{r['id']}] {r['reply']}\n    정답 {r['gold']}\n    예측 {r['pred']}{'  (키워드로 넘어감: ' + r['fallback_reason'] + ')' if r['fallback'] else ''}")

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    base = out / f"reply_{a.method}_{a.split}_{stamp}"
    with open(f"{base}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    pathlib.Path(f"{base}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {base}.csv, {base}.json")
    return summary


# ---------------- agree ----------------
def kappa(pairs) -> float:
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def cmd_agree(a):
    ga, gb = load_gold(a.a), load_gold(a.b)
    ids = sorted(set(ga) & set(gb))
    if not ids:
        sys.exit("두 파일에 같은 id가 없습니다.")
    kind_pairs = [(ga[i].kind, gb[i].kind) for i in ids]
    same = lambda f: sum(f(ga[i]) == f(gb[i]) for i in ids) / len(ids)  # noqa: E731
    res = {"공통 문장": len(ids),
           "판정 일치율": round(same(lambda p: p.kind), 3),
           "판정 카파(Cohen)": round(kappa(kind_pairs), 3),
           "고른 안 일치율": round(same(lambda p: p.picks), 3),
           "조건 일치율": round(same(lambda p: cond_items(p.conditions)), 3)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    diff = [i for i in ids if show(ga[i]) != show(gb[i])]
    if diff:
        print(f"\n서로 다른 문장 {len(diff)}개 (만나서 맞춘 뒤 gold.csv에 적는다)")
        for i in diff:
            print(f"- {i}: {show(ga[i])}  |  {show(gb[i])}")
    return res


# ---------------- message ----------------
def cmd_message(a):
    if a.method == "llm":
        os.environ.setdefault("LLM_RETRIES", "3")
    rows = []
    for s in load_scenarios().values():
        inp = scenario_input(s)
        for k in range(a.repeat if a.method == "llm" else 1):
            t0 = time.time()
            m = write_message(inp, method=a.method)
            rows.append(dict(scenario=s["id"], try_no=k + 1, method=m.method, fallback=m.fallback,
                             auto_problems=" | ".join(m.problems) or "", recheck=" | ".join(check_message(m.text, inp)) or "통과",
                             seconds=round(time.time() - t0, 2), text=m.text,
                             대안_그대로="", 희망_그대로="", 지어낸말_없음="", 금지내용_없음="", 자연스러움_1to5="", 메모=""))
    n = len(rows)
    print(json.dumps({"method": a.method, "메시지 수": n,
                      "언어 모델 글 사용": sum(r["method"] == "llm" for r in rows),
                      "검사에 걸려 틀 문장으로 대신": sum(r["fallback"] for r in rows)}, ensure_ascii=False, indent=1))
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"message_{a.method}_{dt.datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {path}  (빈 칸은 사람이 1/0으로 채운다)")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="조율 NLP 평가")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reply", help="회신 해석 평가")
    r.add_argument("--method", choices=["keyword", "llm"], required=True)
    r.add_argument("--replies", default=str(EVAL / "labels" / "replies.csv"))
    r.add_argument("--gold", default=str(EVAL / "labels" / "gold.csv"))
    r.add_argument("--out", default=str(EVAL / "results"))
    r.add_argument("--show", type=int, default=20, help="틀린 문장 몇 개까지 보여 줄지")
    r.add_argument("--split", choices=["all", "dev", "test", "new"], default="all",
                   help="dev = 프롬프트 고칠 때 보는 16개, test = 평가 64개, "
                        "new = 규칙·프롬프트를 고칠 때 아무도 안 본 새 세트 (s21~s25, eval/labels/split.csv)")
    r.add_argument("--split-file", default=str(EVAL / "labels" / "split.csv"))
    g = sub.add_parser("agree", help="두 사람 라벨 일치도")
    g.add_argument("a")
    g.add_argument("b")
    m = sub.add_parser("message", help="조율 메시지 자동 검사 + 사람 평가표")
    m.add_argument("--method", choices=["keyword", "llm"], required=True)
    m.add_argument("--repeat", type=int, default=1, help="상황마다 몇 번 쓸지 (llm)")
    m.add_argument("--out", default=str(EVAL / "results"))
    a = ap.parse_args(argv)
    return {"reply": cmd_reply, "agree": cmd_agree, "message": cmd_message}[a.cmd](a)


if __name__ == "__main__":
    main()
