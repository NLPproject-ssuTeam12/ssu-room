"""실제 개설 강좌 시간표(2026-1·2학기, AI소프트웨어학부)로 회신 평가용 조율 상황을 만든다.

  python eval/make_scenarios.py            # eval/scenarios.json, eval/상황_메시지.md 다시 만듦

- 원본: data/private/timetable/2026-1.xlsx, 2026-2.xlsx (학교 개설 강좌 조회 결과. 커밋하지 않는다)
- 과목명·분반·강의실·시간은 실제 값을 쓴다. 교수 이름은 가명(가·나·다 …)으로 바꾸고 실명은 어디에도 남기지 않는다
- 상황 만드는 법
  1. 75분 수업 주 2회 또는 같은 날 두 칸 연강인 분반을 고른다 (50분 실습·토요일·시간 없는 강좌·재수강 공통 분반은 뺀다)
  2. 겹친 상대: 같은 강의실을 쓰거나, 같은 학년 전공필수·전공기초끼리인 다른 과목. 그 과목의 실제 시간을 '처음 희망'으로 둔다
  3. 대안: 그 분반의 실제 배정 시간 1개 + 실제 시간표에서 비어 있는 시간 1~2개
     (같은 과목이 실제로 쓰는 강의실, 강의실·담당 교수·같은 학년 전공필수·전공기초와 안 겹침)
  4. 학기마다 10개. 2·3차 조율, 상대 이름 숨김, 대안 2개짜리를 섞는다
  5. 새 세트 (11/22): 위 20개를 똑같이 만든 뒤, 거기서 쓴 과목·상대를 빼고 다른 시드로 5개(s21~s25)를 더 만든다.
     프롬프트·규칙을 고칠 때 아무도 보지 않은 평가용이다 (eval/상황_메시지_새.md)
"""
import itertools
import json
import pathlib
import random
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from openpyxl import load_workbook  # noqa: E402  (.venv에만 있음)

from app.nlp.coord import check_message, write_message  # noqa: E402
from app.nlp.coord_models import DAYN, MessageInput  # noqa: E402

SRC = ROOT / "data" / "private" / "timetable"
TERMS = [("2026-1.xlsx", "2026-1학기"), ("2026-2.xlsx", "2026-2학기")]
GRID = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "19:30"]
PSEUDO = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허고노도로모보소오조초코토포호"
# 지난 조건으로 쓸 시간대 → 교시 (coord.SLOT_WORDS와 같은 값. 찾는 순서를 고정해 같은 상황이 다시 나오게 한다)
PREV_SLOTS = [("오전", ["09:00", "10:30"]), ("오후", ["13:30", "15:00", "16:30"]), ("늦은 오후", ["16:30"]), ("저녁", ["18:00", "19:30"])]
LINE = re.compile(r"^([월화수목금토](?: [월화수목금토])*) (\d\d:\d\d)-(\d\d:\d\d) \((.*)\)$")


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def hhmm(x):
    return f"{x // 60:02d}:{x % 60:02d}"


# ---------------- 읽기 ----------------
def room_of(raw):
    """'문화관 03408(AI융합학부 HW실습실)-교수' → '문화관 03408'. 교수 이름 부분은 버린다."""
    body = raw.rsplit("-", 1)[0].strip()
    m = re.match(r"(\S+)\s+(\d{5})", body)
    return (f"{m.group(1)} {m.group(2)}" if m else None), ("실습실" in body)


def read_term(path):
    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    secs = []
    for r in rows[1:]:
        d = dict(zip(head, r))
        raw_meet = []
        for line in (d["강의시간(강의실)"] or "").split("\n"):
            m = LINE.match(line.strip())
            if not m:
                continue
            room, lab = room_of(m.group(4))
            for day in m.group(1).split():
                raw_meet.append((day, mins(m.group(2)), mins(m.group(3)), room, lab))
        grade = re.match(r"\s*(\d)학년", d["수강대상"] or "")
        secs.append(dict(
            name=d["과목명"].strip(), sec=str(d["과목번호"])[-2:], cat=(d["이수구분(주전공)"] or "")[:2],
            grade=int(grade.group(1)) if grade else None, prof=(d["교수명"] or "").strip(),
            retake="재수강" in (d["분반"] or ""), meet=raw_meet))
    return secs


def shape_of(s):
    """주 2회 75분 → ('two', [(d,start,end,room)×2]), 같은 날 두 칸 연강 → ('long', [(d,start,end,room)]), 그 밖 → None."""
    ms = s["meet"]
    if not ms or s["retake"] or "\n" in s["prof"] or any(m[0] == "토" or m[3] is None for m in ms):
        return None
    if not all(m[2] - m[1] == 75 and hhmm(m[1]) in GRID for m in ms):
        return None
    days = sorted({m[0] for m in ms}, key=DAYN.index)
    if len(ms) == 2 and len(days) == 2:
        return "two", [(DAYN.index(m[0]), m[1], m[2], m[3]) for m in sorted(ms, key=lambda m: DAYN.index(m[0]))]
    if len(ms) == 2 and len(days) == 1:
        a, b = sorted(ms, key=lambda m: m[1])
        if b[1] - a[2] == 15 and a[3] == b[3]:
            return "long", [(DAYN.index(a[0]), a[1], b[2], a[3])]
    return None


# ---------------- 겹침 검사 ----------------
class Busy:
    def __init__(self, secs):
        self.room, self.prof, self.grade = defaultdict(list), defaultdict(list), defaultdict(list)
        for i, s in enumerate(secs):
            for day, st, en, room, _ in s["meet"]:
                if day == "토":
                    continue
                d = DAYN.index(day)
                if room:
                    self.room[room].append((d, st, en, i))
                for p in s["prof"].split("\n"):
                    self.prof[p.strip()].append((d, st, en, i))
                if s["grade"] and s["cat"] in ("전필", "전기"):
                    self.grade[s["grade"]].append((d, st, en, i))

    @staticmethod
    def hit(lst, d, st, en, skip):
        return any(x[0] == d and x[1] < en and st < x[2] and x[3] not in skip for x in lst)

    def free(self, meetings, s, skip, secs):
        for d, st, en, room in meetings:
            if self.hit(self.room[room], d, st, en, skip) or self.hit(self.prof[s["prof"]], d, st, en, skip):
                return False
            if s["grade"] and s["cat"] in ("전필", "전기"):
                same = {i for i, t in enumerate(secs) if t["name"] == s["name"]}
                if self.hit(self.grade[s["grade"]], d, st, en, skip | same):
                    return False
        return True


def overlap(a, b):
    return any(x[0] == y[0] and x[1] < y[2] and y[1] < x[2] for x in a for y in b)


def slot_label(ms):
    """희망 표시: '화·목 13:30', '화 10:30 / 금 12:00', '수 13:30~16:15 연강'."""
    if len(ms) == 1:
        d, st, en, _ = ms[0]
        return f"{DAYN[d]} {hhmm(st)}~{hhmm(en)} 연강"
    if len({m[1] for m in ms}) == 1:
        return f"{'·'.join(DAYN[m[0]] for m in ms)} {hhmm(ms[0][1])}"
    return " / ".join(f"{DAYN[m[0]]} {hhmm(m[1])}" for m in ms)


def candidates(shape, rooms):
    if shape == "two":
        for (d1, d2), t, room in itertools.product(itertools.combinations(range(5), 2), GRID, rooms):
            st = mins(t)
            yield [(d1, st, st + 75, room), (d2, st, st + 75, room)]
    else:
        for d, t, room in itertools.product(range(5), GRID[:6], rooms):   # 18:00 이후 시작 연강은 없다
            st = mins(t)
            yield [(d, st, st + 165, room)]


def dist(a, b):
    """희망과 얼마나 가까운가: 요일이 같으면 가깝고, 시작 시각 차이가 작으면 가깝다."""
    da, db = {m[0] for m in a}, {m[0] for m in b}
    return len(da ^ db) * 100 + abs(a[0][1] - b[0][1])


# ---------------- 상황 만들기 ----------------
PLAN = [  # (차수, 이름 공개, 대안 수)
    (1, True, 3), (1, True, 3), (1, False, 3), (2, True, 3), (1, True, 2),
    (1, True, 3), (3, True, 2), (1, False, 3), (2, False, 3), (1, True, 3)]
NEW_PLAN = {"2026-1학기": [(1, True, 3), (2, True, 3)],
            "2026-2학기": [(1, True, 3), (1, False, 2), (2, True, 3)]}
NEW_SEED = 20261122


def build(secs, term, rng, names, used_courses, used_blockers, plan=PLAN, max_long=2):
    busy = Busy(secs)
    shaped = [(i, s, *shape_of(s)) for i, s in enumerate(secs) if shape_of(s)]
    rooms_by_course = defaultdict(set)
    for i, s, sh, ms in shaped:
        rooms_by_course[s["name"]] |= {m[3] for m in ms}
    rng.shuffle(shaped)
    shaped.sort(key=lambda x: x[2] != "long")          # 연강을 먼저 몇 개 넣기 위해
    out, n_long = [], 0
    for i, x, sh, real in shaped:
        if len(out) == len(plan) or x["name"] in used_courses:
            continue
        if sh == "long" and n_long >= max_long:
            continue
        rnd, reveal, n_alt = plan[len(out)]
        # 겹친 상대: 같은 강의실 또는 같은 학년 전공필수·전공기초, 모양이 같고 다른 과목
        blockers = []
        for j, y, sh2, ys in shaped:
            if (sh2 != sh or y["name"] == x["name"] or y["prof"] == x["prof"] or overlap(ys, real)
                    or (term, y["name"], y["sec"]) in used_blockers):
                continue
            same_room = {m[3] for m in ys} & {m[3] for m in real}
            same_grade = x["grade"] and x["grade"] == y["grade"] and {x["cat"], y["cat"]} <= {"전필", "전기"}
            if same_room or same_grade:
                blockers.append((0 if same_grade else 1, j, y, ys))
        if not blockers:
            continue
        blockers.sort(key=lambda b: (b[0], dist(b[3], real)))
        _, j, y, wish = blockers[0]
        skip = {i}
        alts = [c for c in candidates(sh, sorted(rooms_by_course[x["name"]]))
                if not overlap(c, wish) and c != real and busy.free(c, x, skip, secs)]
        alts.sort(key=lambda c: (dist(c, wish), c[0][3] != real[0][3]))
        picked = []
        for c in alts:   # 서로 너무 같지 않게: 요일·시각이 모두 같은 것은 하나만
            if all((tuple(m[:2] for m in c) != tuple(m[:2] for m in p)) for p in picked):
                picked.append(c)
            if len(picked) == n_alt - 1:
                break
        if len(picked) < n_alt - 1:
            continue
        options = picked + [real]
        rng.shuffle(options)
        prev = None
        if rnd > 1:
            prev = prev_condition(options)
            if prev is None:
                continue
        keys = "ABC"
        s = {
            "id": None, "term": term,
            "_요약": summary(x, y, sh, wish, real, rnd, reveal, n_alt),
            "professor": names(x["prof"]), "course": f"{x['name']} {x['sec']}", "round": rnd,
            "wish": slot_label(wish), "blocker_prof": names(y["prof"]), "blocker_course": f"{y['name']} {y['sec']}",
            "alternatives": [{"key": k, "meetings": [{"day": d, "start": hhmm(st), "end": hhmm(en), "room": r} for d, st, en, r in o]}
                             for k, o in zip(keys, options)],
            "_실제배정": keys[options.index(real)],
        }
        if not reveal:
            s["reveal"] = False
        if prev:
            s["prev_conditions"] = prev
        out.append(s)
        used_courses |= {x["name"]}
        used_blockers |= {(term, y["name"], y["sec"])}
        n_long += sh == "long"
    return out


def prev_condition(options):
    """2·3차: 지난 답장에서 받은 조건. 모든 대안이 맞는 조건 하나를 고른다 (요일 → 교시). 없으면 None."""
    days = [{m[0] for m in o} for o in options]
    if all(d == days[0] for d in days):
        return {"day_slots": {d: [] for d in sorted(days[0])}}          # 그 요일들, 아무 교시나
    for _, sl in PREV_SLOTS:
        used = {g for o in options for m in o for g in GRID if m[1] <= mins(g) < m[2]}
        if used <= set(sl):
            return {"day_slots": {d: sl for d in range(5)}}             # 요일 상관없이 그 교시
    return None


def summary(x, y, sh, wish, real, rnd, reveal, n_alt):
    why = "같은 학년 전공필수·전공기초" if x["grade"] and x["grade"] == y["grade"] and {x["cat"], y["cat"]} <= {"전필", "전기"} else "같은 강의실"
    bits = [f"{x['grade']}학년" if x["grade"] else "전체 학년", {"전필": "전공필수", "전기": "전공기초", "전선": "전공선택"}.get(x["cat"], x["cat"]),
            "연강" if sh == "long" else "주 2회", f"겹친 이유: {why}"]
    if rnd > 1:
        bits.append(f"{rnd}차")
    if not reveal:
        bits.append("이름 숨김")
    if n_alt == 2:
        bits.append("대안 둘")
    return ", ".join(bits)


def main():
    rng = random.Random(20261121)
    pseudo = {}

    def names(real):
        if real not in pseudo:
            pseudo[real] = PSEUDO[len(pseudo)]
        return pseudo[real]

    scenarios = []
    used_courses, used_blockers = set(), set()
    terms = [(read_term(SRC / fname), term) for fname, term in TERMS]
    for secs, term in terms:
        scenarios += build(secs, term, rng, names, used_courses, used_blockers)
    first = len(scenarios)
    rng_new = random.Random(NEW_SEED)   # 새 세트: 위 20개에서 쓴 과목·상대는 used_*로 빠진다
    for secs, term in terms:
        new = build(secs, term, rng_new, names, used_courses, used_blockers, plan=NEW_PLAN[term], max_long=1)
        if len(new) < len(NEW_PLAN[term]):
            raise SystemExit(f"{term} 새 상황을 {len(NEW_PLAN[term])}개 못 만듦 ({len(new)}개)")
        for s in new:
            s["_세트"] = "새"
        scenarios += new
    for n, s in enumerate(scenarios, 1):
        s["id"] = f"s{n}"
    data = {"_설명": (f"회신 평가용 조율 상황 {len(scenarios)}개 (s1~s{first}: 처음 세트, s{first + 1}~s{len(scenarios)}: 새 세트 _세트='새'). "
                      "eval/make_scenarios.py가 AI소프트웨어학부 2026-1·2학기 실제 개설 강좌 시간표로 만든다. "
                      "과목명·분반·강의실·시간은 실제 값, 교수 이름은 가명이다. 처음 희망·겹친 상대·대안은 실제 시간표로 꾸민 가상 상황이다. "
                      "메시지는 eval/상황_메시지.md (처음 세트), eval/상황_메시지_새.md (새 세트). 요일 0=월 1=화 2=수 3=목 4=금. "
                      "_실제배정 = 실제로 배정된 시간이 들어간 대안 (평가에는 쓰지 않는다)."),
            "scenarios": scenarios}
    (ROOT / "eval" / "scenarios.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_messages(scenarios[:first])
    write_messages(scenarios[first:], "상황_메시지_새.md",
                   "새 세트: 처음 20개와 다른 과목으로 만든 5개. 프롬프트·규칙을 고칠 때 보지 않은 평가용이다.")
    print(f"상황 {len(scenarios)}개 (처음 {first} + 새 {len(scenarios) - first}, 가명 {len(pseudo)}명)")


def scenario_input(s):
    return MessageInput(**{k: v for k, v in s.items() if k in MessageInput.model_fields})


def write_messages(scenarios, fname="상황_메시지.md", note=""):
    out = [f"# 평가용 조율 메시지 {len(scenarios)}개", "",
           "답장을 쓸 때 보는 메시지다. `eval/make_scenarios.py`가 2026-1·2학기 실제 개설 강좌 시간표로 상황을 만들고, 틀 문장으로 메시지를 쓴다.",
           "과목명·분반·강의실·시간은 실제 값이고, 교수 이름(한 글자)은 가명이다. 처음 희망·겹친 상대·대안은 실제 시간표로 꾸민 가상 상황이다."]
    out += [note] if note else []
    out += ["", "| 상황 | 학기 | 분반 | 특징 |", "|---|---|---|---|"]
    out += [f"| {s['id']} | {s['term']} | {s['course']} | {s['_요약']} |" for s in scenarios]
    for s in scenarios:
        inp = scenario_input(s)
        m = write_message(inp)
        probs = check_message(m.text, inp)
        if probs:
            raise SystemExit(f"{s['id']} 메시지 검사 실패: {probs}")
        out += ["", f"## {s['id']}: {s['course']} ({s['term']})", "", s["_요약"], "", "```", m.text, "```"]
    (ROOT / "eval" / fname).write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
