"""배정 비교 실험: 그리디 기준선 vs 배정 엔진 (11/26).

① 초안: 같은 입력으로 두 방법이 각각 초안을 만들고, 같은 지표로 잰다.
   못 놓은 분반 · 하드 규칙 위반(엔진 check_timetable) · 희망 칸을 받은 회차 비율 · 희망 건물에 놓인 회차 비율 ·
   19:30 회차 · 연강 동선(같은 학년 전공이 이어진 교시에 같은 건물인 곳) · 걸린 시간
② 재배정: 초안에서 응답한 분반 R개(시드로 고름)의 교수가 "지금 자리는 안 된다"고 회신했다고 보고(그 자리를 불가로 칠함)
   다시 푼다. 엔진은 이전 배정 유지 보너스로 다시 풀고(solve previous=초안), 그리디는 처음부터 다시 놓는다.
   바뀐 분반 수(회신한 분반 R개는 빼고 센다)와 걸린 시간을 잰다.

데이터
  synthetic  가상 데이터(solver/tests/test_data.build), 과목 86개 · 교수 37명(약 100분반), 시드 여러 개
  real       실제 2026-2 전공 분반 목록(비공개 CSV, solver/tests/run_real.build). 응답 없음 / 실제 시간을 희망으로 두 경우.
             정원·불가 칸·채플은 가정. 결과에는 집계 숫자만 남긴다
사용
  python experiments/greedy_vs_solver.py synthetic --seeds 1-10
  python experiments/greedy_vs_solver.py real data/private/real/2026-2_sections.csv
결과 CSV: experiments/results/greedy_vs_solver_<데이터>.csv (한 줄 = 한 실행·한 방법)
"""
import argparse
import csv
import os
import random
import statistics
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "solver"), os.path.join(ROOT, "db"), os.path.join(ROOT, "solver", "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)
import solver_core as sc          # noqa: E402
import greedy as gr               # noqa: E402
import test_data                  # noqa: E402

SOLVE_LIMIT = 60
REPLIES = 10                      # 재배정: "지금 자리는 안 된다"고 회신한 분반 수


# ---------------------------------------------------------------- 지표
def cells(con, tt):
    """(과목, 분반) -> {회차: [(칸, 강의실)]}"""
    out = defaultdict(lambda: defaultdict(list))
    for c, s, ss, sid, room in con.execute(
            "SELECT course_id, section_no, session_no, slot_id, room_id FROM assignment WHERE timetable_id=?", (tt,)):
        out[(c, s)][ss].append((sid, room))
    return out


def metrics(con, tt, term_id=1, round_id=1):
    by_day, courses, secs, rooms, pref, slot_info = sc.load_input(con, term_id, round_id)
    got = cells(con, tt)
    unplaced = sum(1 for (c, s) in secs if sum(len(v) for v in got.get((c, s), {}).values())
                   < courses[c]["sessions"] * courses[c]["k"])
    pre_n = pre_ok = bld_n = bld_ok = late = 0
    flow_loc = set()
    per_idx = {sid: (d, p) for sid, (d, p, _, _) in slot_info.items()}
    ends, starts = defaultdict(set), defaultdict(set)    # (학과, 학년, 요일, 교시, 건물) -> 과목들
    for (c, s), sess in got.items():
        sd, co = secs[(c, s)], courses[c]
        bp = pref.get(sd["prof"])
        for ss, cs in sess.items():
            sids = [x for x, _ in cs]
            if sd["prefer"]:
                pre_n += 1
                pre_ok += all(x in sd["prefer"] for x in sids)
            if bp is not None:
                bld_n += 1
                bld_ok += all(rooms[r]["bld"] == bp for _, r in cs)
            late += any(slot_info[x][2] == sc.LATE_START for x in sids)
            if co["cat"] and str(co["cat"]).startswith(sc.MAJOR_PREFIX) and co["year"]:
                ds = sorted(per_idx[x] for x in sids)
                b = rooms[cs[0][1]]["bld"]
                ends[(co["dept"], str(co["year"]), ds[-1][0], ds[-1][1], b)].add(c)
                starts[(co["dept"], str(co["year"]), ds[0][0], ds[0][1], b)].add(c)
    for (dept, yr, d, p, b), cs_end in ends.items():
        cs_start = starts.get((dept, yr, d, p + 1, b), set())
        if any(x != y for x in cs_end for y in cs_start):
            flow_loc.add((dept, yr, d, p, b))
    return dict(sections=len(secs), unplaced=unplaced, violations=len(sc.check_timetable(con, tt)),
                prefer_rate=round(pre_ok / pre_n, 3) if pre_n else None,
                building_rate=round(bld_ok / bld_n, 3) if bld_n else None,
                late=late, flow=len(flow_loc))


def changed(con, tt_a, tt_b, ignore=()):
    """두 시간표 사이에 칸이 바뀐 분반 수 (ignore 분반은 빼고), 강의실만 바뀐 분반 수"""
    a, b = cells(con, tt_a), cells(con, tt_b)
    t = r = 0
    for k in set(a) | set(b):
        if k in ignore:
            continue
        sa = {x for v in a.get(k, {}).values() for x, _ in v}
        sb = {x for v in b.get(k, {}).values() for x, _ in v}
        if sa != sb:
            t += 1
        elif {y for v in a.get(k, {}).values() for _, y in v} != {y for v in b.get(k, {}).values() for _, y in v}:
            r += 1
    return t, r


def reply_block(con, tt, seed, n=REPLIES):
    """응답한 분반 n개를 시드로 골라, 지금 놓인 칸을 그 분반 응답의 불가 칸으로 칠한다 ('지금 자리는 안 된다')."""
    _, courses, secs, *_ = sc.load_input(con, 1, 1)
    got = cells(con, tt)
    cand = sorted(k for k, sd in secs.items() if sd["responded"] and k in got)
    pick = random.Random(seed).sample(cand, min(n, len(cand)))
    for (c, s) in pick:
        prof = secs[(c, s)]["prof"]
        rid = con.execute("SELECT id FROM course_response WHERE round_id=1 AND course_id=? AND section_no=? AND professor_id=?",
                          (c, s, prof)).fetchone()[0]
        for sess in got[(c, s)].values():
            for sid, _ in sess:
                con.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,'BLOCK')", (rid, sid))
    con.commit()
    return set(pick)


# ---------------------------------------------------------------- 실행
def run_one(build, label, seed):
    rows = []
    for method in ("solver", "greedy"):
        con = build()
        t0 = time.time()
        if method == "solver":
            r = sc.solve(con, 1, 1, time_limit=SOLVE_LIMIT)
        else:
            r = gr.greedy(con, 1, 1)
        draft_s = time.time() - t0
        tt = r["timetable_id"]
        m = metrics(con, tt)
        picked = reply_block(con, tt, seed)
        t1 = time.time()
        if method == "solver":
            r2 = sc.solve(con, 1, 1, time_limit=SOLVE_LIMIT, previous_timetable_id=tt)
        else:
            r2 = gr.greedy(con, 1, 1)
        re_s = time.time() - t1
        tt2 = r2["timetable_id"]
        ch, ch_room = changed(con, tt, tt2, ignore=picked)
        m2 = metrics(con, tt2)
        row = dict(data=label, seed=seed, method=method, status=r["status"], seconds=round(draft_s, 1), **m,
                   re_changed=ch, re_room_only=ch_room, re_unplaced=m2["unplaced"], re_violations=m2["violations"],
                   re_seconds=round(re_s, 1))
        print("  ", row, flush=True)
        rows.append(row)
    return rows


def summary(rows):
    keys = ["unplaced", "violations", "prefer_rate", "building_rate", "late", "flow", "seconds",
            "re_changed", "re_room_only", "re_unplaced", "re_seconds"]
    print("\n방법별 평균 (최소~최대)")
    for method in ("solver", "greedy"):
        rs = [r for r in rows if r["method"] == method]
        parts = []
        for k in keys:
            vs = [r[k] for r in rs if r[k] is not None]
            if vs:
                parts.append(f"{k} {statistics.mean(vs):.3g} ({min(vs)}~{max(vs)})")
        print(f"  {method}: " + ", ".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", choices=["synthetic", "real"])
    ap.add_argument("csv_path", nargs="?")
    ap.add_argument("--seeds", default="1-10")
    a = ap.parse_args()
    rows = []
    if a.data == "synthetic":
        lo, hi = (int(x) for x in a.seeds.split("-"))
        for seed in range(lo, hi + 1):
            print(f"[가상 시드 {seed}]", flush=True)
            rows += run_one(lambda: test_data.build(seed=seed, n_courses=86, n_prof=37), "synthetic", seed)
    else:
        import run_real
        src = list(csv.DictReader(open(a.csv_path, encoding="utf-8-sig")))
        for resp in (False, True):
            label = "real_" + ("prefer" if resp else "noresp")
            print(f"[실제 82분반: {'실제 시간을 희망으로' if resp else '응답 없음'}]", flush=True)
            rows += run_one(lambda: run_real.build([dict(x) for x in src], resp)[0], label, 1)
    os.makedirs(os.path.join(ROOT, "experiments", "results"), exist_ok=True)
    out = os.path.join(ROOT, "experiments", "results", f"greedy_vs_solver_{a.data}.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary(rows)
    print("\n저장:", out)


if __name__ == "__main__":
    main()
