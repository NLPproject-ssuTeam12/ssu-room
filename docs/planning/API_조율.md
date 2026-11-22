# 조율 NLP API (백엔드 2)

조율 단계에서 쓰는 함수 네 개와, 서버에서 열 때의 요청·응답 모양이다. 서버 연결은 백엔드 3(대원), 화면은 프론트(민우)가 맡는다.
코드: `backend/app/nlp/coord.py`, 데이터 모양: `backend/app/nlp/coord_models.py` (공용 `schemas.py`가 생기면 옮긴다).
아래 JSON 예시는 실제 코드 출력이다 (가상 데이터).

> 상태: 11/21 초안. `Conditions` 모양은 배정 엔진(하윤)이 읽는 값이라 맞춰야 한다. 엔드포인트 경로는 제안이다.

## 공통 규칙

| 항목 | 값 |
|---|---|
| 요일 | 0=월 1=화 2=수 3=목 4=금 |
| 시각 | `"HH:MM"` 문자열 |
| 수업 한 번 (`Meeting`) | `{day, start, end, room}`. 주 2회 = 2개, 주 1회 연강 = 1개(165분) |
| 대안 (`Alternative`) | `{key: "A"|"B"|"C", meetings: [Meeting]}`. 배정 엔진 `make_alternatives`가 만든다 |
| 방식 (`method`) | `"keyword"`(기준선) 또는 `"llm"`(Gemini). 언어 모델이 실패하면 키워드 결과를 돌려주고 `fallback: true` |
| 조교 확인 | 처리안(`Proposal`)은 조교가 [확인]을 눌러야 반영한다. 이 API는 아무것도 바꾸지 않는다 |

## 1. 조율 메시지 쓰기 `write_message`

`POST /api/coord/message`

요청 `{"input": MessageInput, "method": "llm"}`

```json
{
 "professor": "나",
 "course": "객체지향프로그래밍 02",
 "term": "2027-1학기",
 "round": 1,
 "wish": "월·수 15:00",
 "alternatives": [
  {"key": "A", "meetings": [{"day": 0, "start": "16:30", "end": "17:45", "room": "정보관 305"},
                            {"day": 2, "start": "16:30", "end": "17:45", "room": "정보관 305"}]},
  {"key": "B", "meetings": [{"day": 0, "start": "12:00", "end": "13:15", "room": "정보관 305"},
                            {"day": 2, "start": "12:00", "end": "13:15", "room": "정보관 305"}]},
  {"key": "C", "meetings": [{"day": 0, "start": "18:00", "end": "19:15", "room": "정보관 305"},
                            {"day": 2, "start": "18:00", "end": "19:15", "room": "정보관 305"}]}
 ],
 "blocker_prof": "가",
 "blocker_course": "자료구조 01",
 "reveal": true,
 "prev_conditions": null,
 "hidden": []
}
```

| 칸 | 채우는 곳 |
|---|---|
| `wish` | 교수가 고른 희망을 글로 (`"월·수 15:00"`, `"수 13:30~16:15 연강"`) |
| `blocker_prof`, `blocker_course` | 겹친 상대. `reveal`이 false면 메시지에 이름을 쓰지 않는다 |
| `reveal` | 학과 설정 "상대 교수 이름 알리기" |
| `prev_conditions` | 2차부터: 지난 답장에서 받은 조건 |
| `hidden` | **서버가 DB에서 채운다.** 상대 교수의 기타 요청 원문 등 메시지에 나오면 안 되는 글. 언어 모델에는 주지 않고 검사에만 쓴다. 화면에서 받지 않는다 |

응답 `Message`

```json
{
 "text": "나 교수님, 안녕하세요. 학과사무실입니다.\n2027-1학기 객체지향프로그래밍 02 분반 시간표 1차 조율 안내드립니다.\n\n희망하신 시간(월·수 15:00)이 가 교수님의 자료구조 01 분반과 겹칩니다.\n\nA  월·수 16:30~17:45 · 정보관 305\nB  월·수 12:00~13:15 · 정보관 305\nC  월·수 18:00~19:15 · 정보관 305\n\n가능한 안을 골라 주시거나, 모두 어려우시면 가능한 시간을 적어 주세요. 회신 기한은 1주이며, 기한 전에 한 번 더 알려 드립니다.",
 "method": "keyword",
 "fallback": false,
 "problems": []
}
```

- 언어 모델 글이 검사(`check_message`)에 걸리면 틀 문장을 돌려주고 `fallback: true`, `problems`에 이유를 넣는다
- 화면은 `text`를 조교에게 보여 주고, 조교가 보내기를 눌러야 보낸다

## 2. 메시지 검사 `check_message`

`POST /api/coord/message/check` 요청 `{"text": "...", "input": MessageInput}` → 응답 `{"problems": ["..."]}` (빈 목록 = 통과)

조교가 메시지를 직접 고친 뒤 보내기 전에 부른다. 걸리는 것:
연차·임용·우선순위 같은 이유, `hidden`의 글, 이름 숨김 설정인데 상대 교수 이름, 과목·분반 빠짐, 본인 희망 빠짐, 대안 줄이 빠지거나 바뀜.

## 3. 답장 해석 `parse_reply`

`POST /api/coord/reply/parse`

요청

```json
{"text": "A나 B 괜찮아요. 수요일은 17시 전에 끝나야 해요.",
 "choice": null,
 "alternatives": [/* 보낸 메시지의 대안 */],
 "message": "보낸 메시지 text",
 "method": "llm"}
```

`choice`: 교수가 화면 버튼을 눌렀으면 `"A"`/`"B"`/`"C"`, 모두 어려움이면 `"none"`, 안 눌렀으면 `null`. 버튼이 글보다 먼저다. A/B/C 버튼에 글이 짧거나 애매하면 그 안을 `수용`(조건·요청이 있으면 `조건부`)으로 본다. 다만 글이 거절이면 버튼과 모순이라 `확인 필요`로 둔다.

응답 `ReplyParse`

```json
{
 "kind": "조건부",
 "picks": ["A", "B"],
 "conditions": {"day_slots": {}, "end_before": [{"day": 2, "time": "17:00"}]},
 "note": "",
 "method": "keyword",
 "fallback": false,
 "fallback_reason": ""
}
```

| 칸 | 뜻 |
|---|---|
| `kind` | `수용` / `조건부` / `거절` / `확인 필요` |
| `picks` | 받아들인 안, 원하는 순서 |
| `conditions.day_slots` | 요일(0=월~4=금) → 그 요일에 되는 교시 시작 시각 목록 (11/22, 요일별 교시). **빈 목록 = 그 요일은 아무 교시나.** 예: "화 오전이나 목 오후" → `{"1": ["09:00", "10:30"], "3": ["13:30", "15:00", "16:30"]}`, "화목이면" → `{"1": [], "3": []}`, "오후면 아무 요일이나" → 다섯 요일 모두 오후 교시. 요일이 둘 이상이면 그 요일들 안에서만, 하나면 그 요일이 들어가기만 하면 됨(주 2회의 다른 하루는 자유). 연강은 두 교시가 모두 들어 있어야 맞음. 교시는 09:00·10:30·12:00·13:30·15:00·16:30·18:00·19:30. 옛 모양 `days`·`slots`로 보내도 받아서 요일 × 교시로 바꾼다. 파이썬 객체에서는 옛 코드용 읽기 값 `.days`·`.slots`도 있지만 근사값이라 새 코드는 `day_slots`를 읽는다 |
| `conditions.end_before` | 요일별로 이 시각 전에 끝나야 함. 교수가 고른 안이 15분 이내로만 넘기면("17:45 종료인데 17:30에 끝낼 수 있으면") 교수 재량으로 보고 넣지 않는다 (`EARLY_END_MIN`) |
| `note` | 학과사무실이 확인하거나 바꿔야 하는 요청 (예: "계단식 강의실", "강의실 21304 요청", "목요일만 10:30으로 조정 희망"). 배정 엔진은 읽지 않고 화면에 그대로 보여 준다. 언어 모델만 채우고 키워드 방식은 비워 둔다. 있으면 `kind`는 `조건부`, 처리안 문구 끝에 "교수님 요청: …"이 붙는다. 강의실 요청은 모델이 번호만 뽑고 코드가 고른 안의 강의실과 대조해서, 이미 그 방이면 note에 넣지 않는다(`수용`) |
| `fallback`, `fallback_reason` | 언어 모델이 실패해 키워드 방식으로 대신 읽었으면 `true`와 이유("503 과부하", "429 요청 제한", "시간 초과", "형식 오류", "키 없음"). **이때 글만 보고 수용·조건부가 나오면 `확인 필요`로 낮추고**, 키워드 추정은 `note`에 "AI 해석 실패(503 과부하). 키워드 추정: B 수용"처럼 남긴다. 처리안은 조교 직접 결정(`decide`)이 되고 문구 끝에 note가 붙는다. 화면 버튼(choice A/B/C)을 눌렀으면 그대로 수용. 키워드 규칙이 거절·보류를 수용으로 잘못 읽는 일을 막기 위해서다 (11/22) |

## 4. 조건 대조 → 처리안 `match_conditions`

`POST /api/coord/reply/match`

요청 `{"parse": ReplyParse, "alternatives": [...], "round": 1, "unavailable": []}`
`unavailable`: 그사이 다른 강의가 들어가 못 쓰게 된 대안 키 (서버가 현재 시간표로 확인).

응답 `Proposal`

```json
{
 "action": "move",
 "key": "B",
 "conditions": {"day_slots": {}, "end_before": [{"day": 2, "time": "17:00"}]},
 "text": "B안(월·수 12:00~13:15 · 정보관 305)으로 옮길까요?",
 "checks": [
  {"key": "A", "ok": false, "why": "수요일 17:45 종료 → 17:00 전 종료 조건과 어긋남"},
  {"key": "B", "ok": true, "why": "조건과 맞음"}
 ]
}
```

| `action` | 뜻 | 조교가 [확인]을 누르면 |
|---|---|---|
| `move` | 고른 안 중 조건에 맞는 첫 안으로 옮김 | 배정 엔진 `reassign`으로 `key` 안 반영 |
| `next` | 맞는 안이 없음. 조건을 넣어 다음 차수 | 배정 엔진 `make_alternatives(conditions)` → 다음 차수 메시지 |
| `decide` | 확인 필요이거나 3차가 끝남 | 조교가 직접 정한다 |

## DB에 남길 것 (하윤 스키마 기준 제안)

| 값 | 테이블.칸 |
|---|---|
| 보낸 메시지 `text` | `message.body` |
| `kind` | `reply_interpretation.label` |
| `ReplyParse` 전체 JSON | `reply_interpretation.extracted_json` |
| 언어 모델 이름 (keyword면 `"keyword"`) | `reply_interpretation.model_name` |
| 조교 선택 [확인]/[수정]/[현재대로 유지]와 사유 | `reply_interpretation.ta_action`, `ta_reason` |

## 서버 없이 바로 부르기 (파이썬)

```python
from app.nlp.coord import write_message, check_message, parse_reply, match_conditions
from app.nlp.coord_models import MessageInput

m = write_message(MessageInput(**body["input"]), method="llm")
r = parse_reply(text, choice, alternatives=alts, message=m.text, method="llm")
p = match_conditions(r, alts, round=1, unavailable=[])
```

환경 변수: `GEMINI_API_KEY`(필수, `.env`), `GEMINI_MODEL`(기본 `gemini-3.5-flash-lite`), `LLM_CACHE_DIR`(시연용 저장 응답), `LLM_RETRIES`(기본 0).
