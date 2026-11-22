"""시연용 언어 모델 응답을 미리 저장하고, 키 없이도 저장본으로 나오는지 확인한다.

시연 중에 Gemini가 막히거나(과부하 503, 할당량 429) 느려도 같은 답이 나오게 하려는 것이다.
llm.py는 LLM_CACHE_DIR이 정해져 있으면 "모델 이름 + 프롬프트 전체"를 열쇠로 응답을 파일에 저장하고 다시 쓴다.
그래서 시연 때와 **똑같은 입력**(메시지에 들어가는 값, 대안, 답장 글, 누른 안)으로 미리 한 번 돌려 두면 된다.
서버와 같은 순서로 부른다: write_message → (그 원문을 message로) parse_reply.

  # 1. 저장: 장면 파일의 메시지·답장을 언어 모델로 한 번씩 돌려 data/demo_cache/에 저장
  python eval/warm_demo_cache.py eval/demo_scenes.json
  # 2. 확인: 키를 빼고 돌려서 전부 저장본으로 나오는지 (하나라도 키워드로 넘어가면 실패)
  python eval/warm_demo_cache.py eval/demo_scenes.json --check
  # 서버로 시연할 때: .env 또는 환경 변수에 LLM_CACHE_DIR=data/demo_cache, GEMINI_MODEL은 저장할 때와 같게

장면 파일 (JSON 목록). 한 장면 = 조율 메시지 하나 + 그 메시지에 온 답장들
  {"name": "1차 조율", "scenario": "s1"}                       ← eval/scenarios.json의 상황을 그대로 쓸 때
  {"name": "...", "input": {MessageInput 값}, "message_method": "llm",
   "replies": [{"text": "A로 할게요", "choice": null}]}       ← 시연 데이터(서버 store.message_input 결과)를 옮겨 적을 때
message_method는 서버에서 조율 메시지를 쓸 때 고른 방식 (keyword면 메시지는 언어 모델을 안 부른다).

다른 방법: 서버를 LLM_CACHE_DIR을 정한 채 켜고 시연을 한 번 그대로 해 보면 그때 응답이 저장된다.
그 뒤 같은 순서·같은 글로 시연하면 저장본이 쓰인다. --check는 장면 파일이 있어야 한다.
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / "demo_cache"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenes", help="장면 JSON 파일")
    ap.add_argument("--check", action="store_true", help="키 없이 돌려서 전부 저장본으로 나오는지 확인")
    ap.add_argument("--cache", default=os.getenv("LLM_CACHE_DIR") or str(DEFAULT_CACHE))
    a = ap.parse_args(argv)

    os.environ["LLM_CACHE_DIR"] = a.cache
    if a.check:
        os.environ["GEMINI_API_KEY"] = ""      # .env보다 먼저 정해 두면 load_dotenv가 덮어쓰지 않는다
    else:
        os.environ.setdefault("LLM_RETRIES", "3")
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "eval"))
    from app.nlp import llm  # noqa: E402
    from app.nlp.coord import parse_reply, write_message  # noqa: E402
    from app.nlp.coord_models import MessageInput  # noqa: E402
    import run_coord  # noqa: E402

    scenes = json.loads(pathlib.Path(a.scenes).read_text(encoding="utf-8"))
    sc = run_coord.load_scenarios()
    model = os.getenv("GEMINI_MODEL", llm.DEFAULT_MODEL)
    print(f"{'확인' if a.check else '저장'} · 모델 {model} · 저장 폴더 {a.cache}")
    bad = 0
    for s in scenes:
        inp = run_coord.scenario_input(sc[s["scenario"]]) if "scenario" in s else MessageInput(**s["input"])
        how = s.get("message_method", "llm")
        t0 = time.time()
        msg = write_message(inp, how)
        ok = how == "keyword" or not msg.fallback
        bad += not ok
        print(f"\n[{s.get('name', s.get('scenario'))}] 메시지 ({how}) {'OK' if ok else '실패: 키워드로 넘어감'} {time.time() - t0:.1f}초")
        for r in s.get("replies", []):
            t0 = time.time()
            p = parse_reply(r.get("text", ""), r.get("choice"), alternatives=inp.alternatives, message=msg.text, method="llm")
            ok = not p.fallback
            bad += not ok
            print(f"  답장 {'OK' if ok else '실패: 키워드로 넘어감'} {time.time() - t0:.1f}초 | {r.get('text', '')[:40]!r} → "
                  f"{p.kind} {''.join(p.picks) or '-'}{' · ' + p.note if p.note else ''}")
    print(f"\n{'모두 저장본으로 나옴' if not bad else f'실패 {bad}건'}" if a.check else f"\n저장 끝 (실패 {bad}건)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
