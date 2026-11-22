"""언어 모델(Gemini) 호출. 정해진 JSON 모양으로만 답을 받는다.

- API 키는 저장소 맨 위 `.env`의 GEMINI_API_KEY에서 읽는다 (.env는 커밋하지 않는다)
- 모델 이름은 GEMINI_MODEL로 바꿀 수 있다
- LLM_CACHE_DIR을 정하면 같은 프롬프트의 응답을 파일로 저장하고 다시 쓴다 (시연용 저장 응답)
- LLM_RETRIES만큼 할당량·과부하·시간 초과 오류를 잠깐 쉬고 다시 부른다 (기본 0, 평가할 때만 늘린다)
- 키가 없거나 호출·형식 검사에 실패하면 LLMUnavailable을 던진다. 부르는 쪽이 키워드 방식으로 대신 처리한다
"""
import hashlib
import json
import os
import pathlib
import time

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

ROOT = pathlib.Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

# 2.5-flash는 새 사용자에게 막힘(404), 3.x flash는 11/21에 사용량이 많아 503이 잦았다. 바꾸려면 .env에 GEMINI_MODEL
DEFAULT_MODEL = "gemini-3.5-flash-lite"
TIMEOUT_MS = 30_000   # 이보다 오래 걸리면 실패로 보고 키워드 방식으로 넘어간다


class LLMUnavailable(Exception):
    pass


def _cache_path(prompt: str, model: str) -> pathlib.Path | None:
    d = os.getenv("LLM_CACHE_DIR")
    if not d:
        return None
    h = hashlib.sha256(f"{model}\n{prompt}".encode("utf-8")).hexdigest()[:24]
    return pathlib.Path(d) / f"{h}.json"


def _call(key: str, model: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return schema.model_validate_json(resp.text)


def _retryable(e: Exception) -> bool:
    """잠깐 뒤 다시 부르면 될 수 있는 오류: 할당량(429), 서버 과부하(500·503), 시간 초과."""
    return getattr(e, "code", None) in (429, 500, 503) or "timeout" in type(e).__name__.lower()


def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    cache = _cache_path(prompt, model)
    if cache and cache.exists():
        try:
            return schema.model_validate_json(cache.read_text(encoding="utf-8"))
        except ValidationError:
            pass

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY가 없습니다")
    retries = int(os.getenv("LLM_RETRIES", "0"))   # 화면에서는 0 (바로 키워드로), 평가할 때만 늘린다
    for attempt in range(retries + 1):
        try:
            obj = _call(key, model, prompt, schema)
            break
        except ValidationError as e:
            raise LLMUnavailable(f"응답 형식이 맞지 않습니다: {e.errors()[:1]}") from e
        except Exception as e:  # 네트워크·할당량·모델 이름 오류 등
            if attempt < retries and _retryable(e):
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            raise LLMUnavailable(f"호출 실패: {type(e).__name__}: {e}") from e

    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(obj.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    return obj


def load_prompt(name: str) -> str:
    return (pathlib.Path(__file__).parent / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
