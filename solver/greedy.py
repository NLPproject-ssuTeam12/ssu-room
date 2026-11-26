"""그리디 기준선 (11/26, 평가: '배정 — 그리디 기준선과 비교').

사람이 엑셀로 편성하는 방식을 흉내 낸 비교용 배정 방법이다. 서비스에서는 쓰지 않는다.
- 분반을 정한 우선순위대로 하나씩 꺼낸다: 실습실 필요 → 가능한 시간(불가가 아닌 칸)이 적은 분반 → 먼저 임용된 교수 → 과목·분반 번호.
- 이미 놓은 분반은 그대로 둔 채, 그 분반의 모든 회차를 엔진과 같은 하드 규칙·같은 점수로 그때 가장 좋은 곳에 놓는다.
  (엔진의 _solve_model 을 그 분반만 풀리게 불러서 규칙·점수가 엔진과 똑같다. 아직 꺼내지 않은 분반은 skip 으로 뺀다)
- 한 번 놓은 분반은 다시 바꾸지 않는다. 지금까지 놓은 것 때문에 놓을 수 없으면 그 분반은 못 놓음으로 남긴다.
엔진(solve)과 다른 점은 "앞에서 놓은 것을 뒤에서 다시 고치지 않는다"는 것 하나다.

  greedy(con, term_id, round_id) -> dict(status, timetable_id, unplaced, seconds, order)
"""
import json
import time

import solver_core as sc


def priority(secs, slot_info):
    """그리디가 분반을 꺼내는 순서 (정한 우선순위)."""
    total = len(slot_info)

    def key(k):
        sd = secs[k]
        return (0 if sd["lab"] == "MUST" else 1,
                total - len(sd["block"]),
                sd.get("hire_year") if sd.get("hire_year") is not None else 9999,
                k[0], k[1])
    return sorted(secs, key=key)


def greedy(con, term_id, round_id, weights=None, step_time=5, workers=8, created_by=None):
    """분반을 하나씩 놓는 그리디 배정. 결과를 엔진과 같은 모양으로 timetable 에 저장한다 (solver_run.weights_json 에 method=greedy)."""
    W = {**sc.DEFAULT_WEIGHTS, **(weights or {})}
    _, courses, secs, _, _, slot_info = sc.load_input(con, term_id, round_id)
    order = priority(secs, slot_info)
    prev, prevk = {}, {}                         # 지금까지 놓은 회차 {(과목,분반,회차): (시작칸, 강의실)}, 칸 수
    done, failed = set(), set()
    t0 = time.time()
    for k in order:
        skip = set(secs) - done - {k}            # 아직 꺼내지 않은 분반과 못 놓은 분반은 이번 풀이에서 뺀다
        out = sc._solve_model(con, term_id, round_id, W, step_time, workers, prev, prevk, {k}, 0,
                              must_sections={k}, skip=skip, flow_time_limit=max(1, step_time // 2))
        if out["placements"] is None:
            failed.add(k)                        # 앞에서 놓은 것 때문에 놓을 수 없음 → 못 놓음
            continue
        for key, v in out["placements"].items():
            if key[:2] == k:
                prev[key] = v
                prevk[key] = out["ks"][key]
        done.add(k)
    # 놓은 것 그대로 한 번 더 불러 엔진과 같은 모양으로 저장 (모두 고정, 못 놓은 분반은 뺌)
    final = sc._solve_model(con, term_id, round_id, W, 30, workers, prev, prevk, set(), 0, skip=failed)
    final["unplaced"] = [(c, s, ss) for (c, s) in sorted(failed) for ss in range(1, courses[c]["sessions"] + 1)]
    run_id, tt = sc._persist(con, final, term_id, round_id, {**W, "method": "greedy"}, step_time, None, created_by)
    return dict(status=final["status"], timetable_id=tt, run_id=run_id, unplaced=final["unplaced"],
                unplaced_sections=sorted(failed), seconds=time.time() - t0, order=order)
