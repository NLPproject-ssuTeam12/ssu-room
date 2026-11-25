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
 "hidden": [],
 "current": null
}
```

| 칸 | 채우는 곳 |
|---|---|
| `wish` | 교수가 고른 희망을 글로 (`"월·수 15:00"`, `"수 13:30~16:15 연강"`) |
| `blocker_prof`, `blocker_course` | 겹친 상대. `reveal`이 false면 메시지에 이름을 쓰지 않는다 |
| `reveal` | 학과 설정 "상대 교수 이름 알리기" |
| `prev_conditions` | 2차부터: 지난 답장에서 받은 조건 |
| `hidden` | **서버가 DB에서 채운다.** 상대 교수의 기타 요청 원문 등 메시지에 나오면 안 되는 글. 언어 모델에는 주지 않고 검사에만 쓴다. 화면에서 받지 않는다 |
| `current` | **서버가 채운다.** 희망 밖에라도 지금 놓여 있는 분반의 자리 (`"화·목 10:30~11:45 · 정보과학관 21304"`, 대안 줄과 같은 모양). 있으면 대안 아래에 틀 문장 "지금은 …에 배정되어 있습니다. 그대로 괜찮으시면 '지금 자리 그대로'를 골라 주세요."가 붙고, 교수 화면에 `KEEP` 버튼을 보여 준다. 못 놓인 분반은 `null` (11/25 결정) |
| `off`, `wish_building` | **서버가 채운다.** 희망에서 어긋난 것: `"time"`(기본, 못 놓은 분반 포함) / `"building"` / `"both"`. 엔진 `coord_targets`의 `time_off`·`building_off`가 비었는지로 정한다(#21). `building`·`both`면 `wish_building`(희망 건물 이름) 필수. 건물만이면 "희망하신 건물(정보과학관)에 배정하지 못해 아래 대안을 드립니다."로 쓰고 시간·겹친 상대는 쓰지 않는다. 둘 다면 시간 문장 뒤에 건물 문장을 붙인다. 2·3차는 "처음 희망하신 건물: …" (11/25) |

응답 `Message`

```json
{
 "text": "나 교수님, 안녕하세요. 학과사무실입니다.\n2027-1학기 객체지향프로그래밍 02 분반 시간표 1차 조율 안내드립니다.\n\n희망하신 시간(월·수 15:00)이 가 교수님의 자료구조 01 분반과 겹칩니다.\n\nA  월·수 16:30~17:45 · 정보관 305\nB  월·수 12:00~13:15 · 정보관 305\nC  월·수 18:00~19:15 · 정보관 305\n\n가능한 안을 모두 골라 주시고, 모두 어려우시면 기타를 골라 가능한 시간을 적어 주세요. 회신 기한은 1주이며, 기한 전에 한 번 더 알려 드립니다.",
 "method": "keyword",
 "fallback": false,
 "problems": []
}
```

- `llm`이어도 인사·제목 줄·대안 줄·마지막 문장은 틀 문장 그대로이고, 언어 모델은 가운데 **상황 설명 문단 하나만** 쓴다 (11/23 사람 평가 뒤 바꿈, `docs/planning/메시지_사람평가.md` 5절)
- 1차에서 `blocker_prof`·`blocker_course`가 비어 있으면(서버가 겹친 상대를 못 찾음) "겹친다"고 단정하지 않고 "희망하신 시간(…)에 배정하지 못해 아래 대안을 드립니다."로 쓴다. 상대를 알지만 `reveal`이 꺼져 있으면 "다른 강의와 겹칩니다" (11/24)
- 설명 문단 검사(`check_body`): 대안 A·B·C를 따로 설명함, 처음 희망·지난 조건에 없는 시각, 이유를 덧붙이는 말("때문", "배정되", "중복" 등, 2·3차는 "겹"도), 빈 문단, 자리표시가 남음, 1차·상대 공개인데 상대 교수·강의 이름이 빠짐
- 언어 모델 글이 `check_body`나 `check_message`에 걸리거나 호출이 실패하면 틀 문장을 돌려주고 `fallback: true`, `problems`에 이유를 넣는다
- 화면은 `text`를 조교에게 보여 주고, 조교가 보내기를 눌러야 보낸다

## 2. 메시지 검사 `check_message`

`POST /api/coord/message/check` 요청 `{"text": "...", "input": MessageInput}` → 응답 `{"problems": ["..."]}` (빈 목록 = 통과)

조교가 메시지를 직접 고친 뒤 보내기 전에 부른다. 걸리는 것:
연차·임용·우선순위 같은 이유, `hidden`의 글, 이름 숨김 설정인데 상대 교수 이름, 과목·분반 빠짐, 본인 희망(시간, `off`가 건물이면 건물) 빠짐, 대안 줄이 빠지거나 바뀜, `current`가 있는데 지금 자리가 빠지거나 바뀜.

## 3. 답장 해석 `parse_reply`

`POST /api/coord/reply/parse`

요청

```json
{"text": "A나 B 괜찮아요. 수요일은 17시 전에 끝나야 해요.",
 "choices": ["A", "B", "ETC"],
 "alternatives": [/* 보낸 메시지의 대안 */],
 "message": "보낸 메시지 text",
 "method": "llm"}
```

`choices` (11/25, 하윤 #17 교수 답장 화면): 교수가 누른 값 `"A"`·`"B"`·`"C"`·`"ETC"`(기타) 중 하나 이상, 여러 개 가능. 기타를 누르면 `text`(기타 글)가 있어야 한다(화면·DB가 막음). 기타만 누르면 A·B·C는 하나도 안 고른 것으로 본다(예전 "모두 어려움"과 같음).
- 버튼이 글보다 먼저다. A/B/C 버튼에 글이 짧거나 애매하면 그 안을 `수용`(조건·요청이 있으면 `조건부`)으로 본다. 다만 글이 거절이면 버튼과 모순이라 `확인 필요`로 둔다
- 버튼을 여러 개 누르고 글로 순서를 밝혔으면("C가 좋고 안 되면 B") `picks`를 글 순서로, 아니면 누른 순서로 준다. 버튼이 하나면 그 안이 맨 앞
- 예전 화면 값 `choice`(`"A"`/`"B"`/`"C"`, 모두 어려움 `"none"`, 안 누름 `null`)도 그대로 받는다. `choices`가 있으면 `choices`를 쓴다
- `"KEEP"`(지금 자리 그대로, 11/25): 메시지에 `current`가 있었던 분반만 화면에 보인다. 누르면 `keep: true`, `kind: 수용`, 처리안 `keep`. A·B·C와 같이 눌러도 지금 자리를 그대로 둔다(옮기지 않는 쪽이 덜 바뀜)
- 요청에 `"can_keep": true`(지금 자리가 있는 분반)를 주면 버튼 없이 글로 "지금 그대로 괜찮아요"라고 써도 `keep`으로 읽는다. A·B·C를 골랐으면 글의 "그대로"는 keep이 아니다("B로 하고 방은 지금 그대로"). "처음 희망 시간으로 해 달라"는 keep이 아니라 거절이다. `can_keep`이 없으면 글로는 keep을 읽지 않는다

응답 `ReplyParse`

```json
{
 "kind": "조건부",
 "picks": ["A", "B"],
 "ordered": false,
 "keep": false,
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
| `ordered` | 교수가 글로 선호 순서를 밝혔는가 (`picks`가 둘 이상일 때만 `true`). 서버는 배정 엔진 `pick_best(option_ids=picks 순서, respect_order=ordered)`에 넘긴다. `false`면 엔진이 점수 순으로 고른다 (11/25, 하윤 #18) |
| `keep` | 교수가 지금 배정된 자리를 그대로 원함 (`KEEP` 버튼, 또는 `can_keep`일 때 글). 처리안은 `keep` (11/25) |
| `conditions.day_slots` | 요일(0=월~4=금) → 그 요일에 되는 교시 시작 시각 목록 (11/22, 요일별 교시). **빈 목록 = 그 요일은 아무 교시나.** 예: "화 오전이나 목 오후" → `{"1": ["09:00", "10:30"], "3": ["13:30", "15:00", "16:30"]}`, "화목이면" → `{"1": [], "3": []}`, "오후면 아무 요일이나" → 다섯 요일 모두 오후 교시. 요일이 둘 이상이면 그 요일들 안에서만, 하나면 그 요일이 들어가기만 하면 됨(주 2회의 다른 하루는 자유). 연강은 두 교시가 모두 들어 있어야 맞음. 교시는 09:00·10:30·12:00·13:30·15:00·16:30·18:00·19:30. 옛 모양 `days`·`slots`로 보내도 받아서 요일 × 교시로 바꾼다. 파이썬 객체에서는 옛 코드용 읽기 값 `.days`·`.slots`도 있지만 근사값이라 새 코드는 `day_slots`를 읽는다 |
| `conditions.end_before` | 요일별로 이 시각 전에 끝나야 함. 교수가 고른 안이 15분 이내로만 넘기면("17:45 종료인데 17:30에 끝낼 수 있으면") 교수 재량으로 보고 넣지 않는다 (`EARLY_END_MIN`) |
| `note` | 학과사무실이 확인하거나 바꿔야 하는 요청 (예: "계단식 강의실", "강의실 21304 요청", "목요일만 10:30으로 조정 희망"). 배정 엔진은 읽지 않고 화면에 그대로 보여 준다. 언어 모델만 채우고 키워드 방식은 비워 둔다. 있으면 `kind`는 `조건부`, 처리안 문구 끝에 "교수님 요청: …"이 붙는다. 요청이 강의실에 관한 것이고 처리안이 `move`면 "강의실만 바꾸려면 [확인] 뒤 AI 도우미에게 …" 안내도 붙는다([수정]은 A·B·C만 고르므로). 강의실 요청은 모델이 번호만 뽑고 코드가 고른 안의 강의실과 대조해서, 이미 그 방이면 note에 넣지 않는다(`수용`) |
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
| `move` | 고른 안 중 조건에 맞는 첫 안으로 옮김. 여러 안을 골랐으면 서버가 엔진 `pick_best`로 최종 확인 | 배정 엔진 `reassign`으로 `key` 안 반영 |
| `next` | 맞는 안이 없음. **조건이 있을 때만** 그 조건을 넣어 다음 차수 (엔진이 조건에 맞는 새 안을 바로 만들 수도 있음) | 배정 엔진 `make_alternatives(conditions)` → 다음 차수 메시지 |
| `decide` | 확인 필요, 3차가 끝남, **되는 시간 없이 거절**(기타에 요청만 적은 경우 포함), 조건 없이 고른 안을 모두 못 쓰게 됨 | 조교가 [수정]·[현재대로 유지]·**[따로 연락]**(하윤 #17 `OFFLINE`) 중에서 정한다 |
| `keep` | 교수가 '지금 자리 그대로'를 고름 (`parse.keep`). 문구 "교수님이 지금 자리를 그대로 원합니다. [현재대로 유지]를 누르면 끝납니다." | 서버 `decide_reply` `KEEP` (시간표는 안 바뀜) (11/25) |

- 되는 시간 없이 거절하면 다음 차수에 넘길 조건이 없다. 시스템이 조건을 지어내지 않고 조교가 교수와 직접 정한다 (11/25, 예전에는 조건 없이 `next`를 내서 DB 저장 오류가 났음)
- 처리안 문구 끝에는 교수 요청(`note`)이 "교수님 요청: …"으로 붙는다. 시간표 밖 요청(실습 조교 등)은 서버가 하윤 `db.add_reply_request`로 기타 요청 표에 남기고, 분반 연강·교차 요청은 조교 [확인](`pair`)으로 반영한다

## 서버 연결 할 일 (#19 기준, 대원)

#19(`choices`·`ordered`·`decide`/[따로 연락]·`keep`·`current`)가 main에 들어가면 서버에서 맞출 곳. main `ebd99ab` 기준으로 확인함.

| # | 파일 | 할 일 | 안 하면 |
|---|---|---|---|
| 1 | `stubs.py` `parse_reply` | 인자 모양을 진짜와 똑같이: `parse_reply(text, choice=None, *, choices=None, alternatives=None, message="", method="keyword", can_keep=False)` | `engine.py`의 `signature_diff`가 모양이 다르다고 보고 **가짜 함수로 바꿔 씀** (경고만 남음) |
| 2 | `contracts.py` 사본 | `ReplyParse`에 `ordered: bool = False`, `keep: bool = False`, `fallback_reason: str = ""` / `MessageInput`에 `current: Optional[str] = None`, `off: Literal["time", "building", "both"] = "time"`, `wish_building: Optional[str] = None` / `Proposal.action`에 `"keep"` | 사본으로 다시 읽거나 저장할 때 칸이 빠지거나 `keep` 처리안이 검증 오류 |
| 3 | `main.py` `ReplyIn` | `choices: Optional[List[Literal["A", "B", "C", "ETC", "KEEP"]]]` 추가(예전 `choice`는 남겨도 됨), "글이나 버튼 하나는 있어야" 검사를 `choices`까지, `ETC`면 글 필수 | 여러 개 누름·기타·지금 자리 그대로를 받을 수 없음 |
| 4 | `main.py` `post_reply` | `engine.parse_reply(body.text, body.choice, choices=body.choices, alternatives=alts, message=..., method=..., can_keep=<지금 자리 있음>)` | 버튼 값이 해석에 안 들어감 |
| 5 | `store.py` `message_input` | 희망 밖에라도 놓인 분반(11/25 결정 2·3번)은 `current`에 지금 자리를 넣는다. 모양은 대안 줄과 같게: 지금 배정을 `Alternative`로 만들어 `coord.alt_label`에 넣으면 됨 (`"화·목 10:30~11:45 · 정보과학관 21304"`). 못 놓인 분반은 `None`. 같은 곳에서 `off`·`wish_building`도 채운다(#21 `coord_targets`의 `time_off`·`building_off`, 희망 건물은 `professor_building_pref`) | 메시지에 지금 자리 줄이 안 나오고, 교수 화면에 `KEEP` 버튼을 띄울 근거가 없음. 건물만 어긋난 분반에 "희망하신 시간에 배정하지 못해"라고 틀리게 나감 |
| 6 | 교수 답장 화면 | `current`가 있던 분반만 `KEEP`(지금 자리 그대로) 버튼을 보여 준다 | 못 놓인 분반에서 KEEP이 눌릴 수 있음 |
| 7 | `main.py` `post_decide` | 처리안이 `keep`이면 [확인] = [현재대로 유지] (`state="KEPT"`, DB는 `decide_reply(..., 'KEEP')`). 지금은 `move`가 아니면 [확인]이 409 | 교수가 지금 자리를 골랐는데 조교 [확인]이 막힘 |
| 8 | `main.py` `post_decide` | 처리안이 `move`이고 `picks`가 둘 이상이면 하윤 `pick_best(option_ids=picks, respect_order=ordered)`로 최종 안을 고른다 (#18) | 교수가 밝힌 순서를 무시하거나, 그사이 못 쓰게 된 안을 고를 수 있음 |
| 9 | `main.py` `DecideIn`·`post_decide` | 조교 선택에 [따로 연락] 추가 → DB `decide_reply(..., 'OFFLINE')`, 조교가 칸을 정하면 `manual_place`(하윤 #17). `decide` 처리안 문구가 이 버튼을 가리킨다 | 되는 시간 없는 거절·3차 끝을 조교가 닫을 길이 [수정]·[현재대로 유지]뿐 |

- 1·2번은 #19 병합과 같이 해야 한다. 7번 이후는 화면(민우)·DB 연결 때 같이 해도 된다
- 8번 `pick_best`는 #18(`feat/pick-order`, `solver_core.pick_best`), 9번 `OFFLINE`·`manual_place`는 #17(`feat/reply-choice`, migration 007)이 병합돼야 쓸 수 있다 (11/25 밤 기준 둘 다 병합 전)
- #19와 별개: 11/25 결정의 "메시지 보낼 분반 고르기"(못 놓음 + 희망 칸 하나도 못 받음만 자동, 희망 일부만은 조교 표시, 대안 0개면 따로 연락)는 서버가 분반을 고르는 일이라 조율 함수 밖이다

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
r = parse_reply(text, choices=["A", "ETC"], alternatives=alts, message=m.text, method="llm",
                can_keep=current is not None)   # 지금 자리가 있는 분반이면 True
p = match_conditions(r, alts, round=1, unavailable=[])
```

환경 변수: `GEMINI_API_KEY`(필수, `.env`), `GEMINI_MODEL`(기본 `gemini-3.5-flash-lite`), `LLM_CACHE_DIR`(시연용 저장 응답), `LLM_RETRIES`(기본 0).
