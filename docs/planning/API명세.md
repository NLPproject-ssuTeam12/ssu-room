# SSU:room API 명세

서버(백엔드 ③)와 화면(프론트엔드)이 주고받는 약속이다. 화면은 이 문서만 보고 붙인다.
예시 응답은 실제 서버(TestClient, 2026-11-21, 실습 데이터 `real`)에서 받은 것을 줄여 붙였다.

- 서버: `http://localhost:8000`
- 화면: `http://localhost:5173` (서버가 이 주소만 CORS 허용)
- 실행 (저장소 루트에서):

  ```
  uvicorn backend.app.main:app --reload --port 8000
  ```

- 데이터 묶음: 환경변수 `DATA_SET` (기본 `real`) → `data/private/<DATA_SET>/` 의 JSON을 읽는다.
  `real`은 `python backend/tools/import_real.py --src <원본 폴더>` 로 만든다. 이 폴더는 커밋하지 않는다.
- 상태는 서버 메모리에만 있다. 서버를 다시 켜거나 `POST /reset` 하면 처음으로 돌아간다. (DB는 나중에)
- 테스트: `python -m pytest backend/tests -q` (backend/ 안에서는 `python -m pytest tests -q`)

## 데이터 안내 (화면에 표시할 것)

| 항목 | 사실 |
|---|---|
| 강의실 정원·실습실 여부 | **추정값**. 지난 학기 수강 인원·실습 과목 사용으로 짐작함. `estimated: true` |
| 교수 희망 | **가상**. 실제 교수 희망이 아님 |
| 교수 이름 | **가명** (`교수01` 형식). 실명은 어디에도 없음 |
| 분반·과목 | 2026-2학기 AI대학 실제 개설 목록 |

---

## 1. 단계 흐름

```
COLLECT ──POST /draft──▶ DRAFT ──POST /rounds/next──▶ ROUND 1 ─▶ ROUND 2 ─▶ ROUND 3
   ▲                        │                            │                      │
   │                        └────────POST /finalize──────┴──────────────────────┴──▶ FINAL
   └──────────────────────────── POST /reset (어느 단계에서든) ─────────────────────────┘
```

- `COLLECT`: 교수 희망을 받는다.
- `DRAFT`: 초안이 나왔다. 조율 목록이 생긴다. 아직 메시지는 못 보낸다.
- `ROUND`(1~3차): 조율 메시지 → 답장 → 조교 결정. 3차 다음은 없다(409).
- `FINAL`: 확정. 이후 바꾸는 요청은 모두 409.

| 엔드포인트 | COLLECT | DRAFT | ROUND | FINAL |
|---|:-:|:-:|:-:|:-:|
| `GET /health` `/sections` `/rooms` `/wishes` `/coord` | ✓ | ✓ | ✓ | ✓ |
| `POST /wishes` | ✓ | | | |
| `POST /draft` | ✓ | | | |
| `GET /timetable` | | ✓ | ✓ | ✓ |
| `POST /coord/{id}/message` `/reply` `/decide` | | | ✓ | |
| `POST /rounds/next` | | ✓ (→1차) | ✓ (1·2차만) | |
| `POST /finalize` | | ✓ | ✓ | |
| `POST /reset` | ✓ | ✓ | ✓ | ✓ |
| `GET /settings` `POST /settings` | ✓ | ✓ | ✓ | ✓ |
| `POST /assistant` | ✓ | ✓ | ✓ | ✓ |
| `POST /assistant/apply` | | ✓ | ✓ | |
| `GET /export.xlsx` | | | | ✓ |

`GET /coord`는 COLLECT에서 빈 목록 `[]`이다.

---

## 2. 꼭 알아야 할 것

### 분반 id는 인코딩해서 주소에 넣는다
분반 id에 한글·괄호가 있다. 예: `2150164203-(공통-재수강)`. 주소에 넣을 때 **`encodeURIComponent`** 를 쓴다.

```js
fetch(`http://localhost:8000/coord/${encodeURIComponent(sectionId)}/message`, { method: "POST" })
```

### 수업 모양 `shape`
| 값 | 뜻 | 자동 배정·조율 |
|---|---|---|
| `TWICE` | 주 2회. 1칸(75분) Block 2개. 두 번의 시각이 달라도 됨 | 대상 |
| `ONCE_LONG` | 주 1회 연강. 2칸 Block 1개 | 대상 |
| `MANUAL` | 그 밖의 모양 (Co-op 4칸 연속, 주 4칸 등). **조교 직접 배정** | 제외. 시간표에는 그대로 보임 |

실제 데이터: TWICE 52, ONCE_LONG 33, MANUAL 12 (합 97). MANUAL 분반에 조율 요청을 보내면 409.

### Block (수업 한 번)
```json
{ "day": "화", "start": "18:00", "slots": 1, "room": "문화관 03407" }
```
- `day`: 월~금. **토요일(`토`)은 MANUAL 분반에만** 나온다(실제 데이터에 2개).
- `start`: 보통 8칸 중 하나 — `09:00 10:30 12:00 13:30 15:00 16:30 18:00 19:30`.
- `slots`: 칸 수. 1칸 = 75분, 2칸 = 165분(쉬는 시간 15분 포함). 끝 시각 = 시작 + 75×칸 + 15×(칸−1).
- `room`: **이 수업의 강의실** (11/23 추가). 솔버는 한 분반의 두 수업을 다른 강의실에 놓을 수 있다(예: 화 문화관 03407, 목 정보과학관 21304).
  서버가 내보내는 시간표에서는 늘 채워져 있다. 들어오는 값이 비어 있으면 그 배정의 `room`으로 본다.

> **강의실 읽는 법:** 배정(Assignment)의 `room`은 **대표 강의실 = 첫 수업의 강의실**이다(기존 화면 호환용, 이름·뜻 그대로).
> 수업마다 강의실은 `blocks[].room`을 쓴다. 두 수업의 강의실이 같으면 `room`과 `blocks[].room`이 모두 같다.
> 도우미로 강의실만 바꾸면 그 분반의 모든 수업에 적용된다.

### 배정 상태 `status`
| 값 | 뜻 |
|---|---|
| `DONE` | 배정됨 |
| `COORD` | 조율 중 (밀림). `reason`에 이유 |
| `MANUAL` | 조교 직접 배정 분반 |

### 학년 `year`
`null`이면 전체 학년 분반이다.

### 에러 모양
모든 에러는 `{"detail": ...}` 이다.
- 409·404·501, 서버가 직접 낸 422: `detail`은 **문장(문자열)**. 그대로 화면에 보여 주면 된다.
- 요청 형식이 틀린 422(Pydantic): `detail`은 **목록** `[{loc, msg, type}]`. `msg`를 보여 준다.

---

## 3. 가짜 함수(STUB)와 `/health`

배정·조율 계산은 아직 가짜 함수가 한다. 응답 모양은 진짜와 같고, 값만 그럴듯하게 만든 것이다.
진짜 함수가 들어오면 서버가 자동으로 바꿔 쓴다. 화면 코드는 바꿀 필요 없다.

| 엔드포인트 | 쓰는 함수 (담당) |
|---|---|
| `POST /draft` | `make_draft`, `make_alternatives`, `check_rules` (문하윤) |
| `POST /coord/{id}/message` | `write_message`, `check_message` (최재성) |
| `POST /coord/{id}/reply` | `parse_reply`, `match_conditions` (최재성) |
| `POST /coord/{id}/decide` | `reassign`, `check_rules` (문하윤) |
| `POST /rounds/next` (2·3차) | `make_alternatives` (문하윤) |
| `POST /finalize` | `check_rules` (문하윤) |
| `POST /assistant` (what_if·move) | `what_if` (문하윤). 질문 해석은 키워드 기준선(진짜, 김대원) |
| `POST /assistant/apply` | `reassign`, `check_rules` (문하윤) |

진짜/가짜 확인: `GET /health` 의 `engine`. 값이 `"stub"`이면 가짜, `"real (모듈 이름)"`이면 진짜다.
진짜 모듈이 있는데 불러오다 실패하면 가짜로 돌고 `load_warnings`에 `"parse_reply 함수: 진짜 모듈 불러오기 실패 → 가짜 사용 (이유)"`가 생긴다.
조율 함수 4개는 진짜와 서버(stubs.py)의 인자 모양(이름·순서·키워드 전용·기본값)도 비교한다. 다르면 가짜로 돌고
`load_warnings`에 `"parse_reply: 진짜 함수 모양이 서버와 다름 (차이) → 가짜 사용"`이 생긴다.
2026-11-21에 `jaeseong/coord`의 coord.py를 임시로 합쳐 확인했을 때 4개 모두 `real (backend.app.nlp.coord)`였고 경고는 없었다.

가짜 값에서 알아 둘 것:
- 조율 이유 문장 끝에 `(가짜 값)`이 붙는다.
- 대안 A·B·C는 같은 강의실을 쓰는 다른 분반과의 겹침만 피한다. 교수·학년 겹침은 안 본다.
- 가짜 조율 함수는 `method`와 상관없이 틀 문장·간단한 키워드로 처리한다(답장에서 요일·교시는 안 뽑고 종료 시각만, `note`는 항상 `""`).
- 가짜 `make_alternatives`는 지금 자리에서 한두 교시·요일을 옮겨 보는 것만 해서, 조건(`slots` 등)에 맞는 대안이 없으면 0개가 된다. 그러면 다음 차수 메시지는 409.
- 시간 규칙(팀 결정 11/21): 가짜 `make_alternatives`는 18:00 시작 연강을 만들지 않고(하드), 19:30 교시는 큰 감점으로 보아 19:30을 안 쓰는 안을 먼저 고른다. 19:30 안은 다른 안이 3개가 안 될 때만 들어간다. 가짜 `check_rules`는 이 둘을 위반으로 세지 않는다(실제 초안에 18:00 연강이 5개 있다).
- 가짜 `what_if`는 옮기는 분반의 **첫 번째 수업만** 옮겨 보고 위반을 센다(강의실 겹침만). 그래서 미리 보기 위반 수와 실제 적용 뒤 위반 수가 다를 수 있다.

---

## 4. 엔드포인트

### `GET /health`
서버 상태, 진짜/가짜 함수, 데이터 읽기 경고. 모든 단계.

```json
{
  "ok": true,
  "data_set": "real",
  "stage": "COLLECT",
  "round_no": 0,
  "engine": {
    "check_rules": "stub", "make_draft": "stub", "make_alternatives": "stub",
    "reassign": "stub", "what_if": "stub",
    "write_message": "stub", "check_message": "stub", "parse_reply": "stub", "match_conditions": "stub"
  },
  "load_warnings": [
    "2150130801: 희망 칸 1개 버림 ['수-17:00']"
  ]
}
```
- `round_no`: 0 = 조율 전, 1~3 = 차수.
- `load_warnings`: 진짜 함수 불러오기 실패 + 희망 파일에서 버린 칸(토요일, 8칸 밖 시각).

### `GET /sections`
분반 목록. 모든 단계.

```json
[
  {
    "id": "2150164903-(공통-재수강)",
    "code": "2150164903",
    "name": "웹프로그래밍",
    "division": "(공통-재수강)",
    "year": null,
    "category": "전선-AI소프트웨어",
    "enrollment": 30,
    "weekly_blocks": 2,
    "professor": "교수46",
    "lab_need": "MUST",
    "shape": "ONCE_LONG"
  }
]
```
- `division`: 분반 번호. 없으면 `null` (이때 `id` = `code`).
- `weekly_blocks`: 주당 75분 칸 수.
- `professor`: 가명. 담당 미정이면 `null`.
- `lab_need`: `MUST`(실습실 필요) / `NONE`(필요 없음). 두 가지뿐이다 (팀 결정 11/21. 값 이름은 하윤 DB `lab_requirement`와 같다).

### `GET /rooms`
강의실 목록. 모든 단계.

```json
[
  { "id": "문화관 03105", "building": "문화관", "room_no": "03105",
    "capacity": 53, "is_lab": true, "estimated": true }
]
```
- `estimated: true`: 정원이나 실습실 여부가 추정값. 지금은 17개 모두 추정.

### `GET /wishes`
교수 희망 전체와 교수 단위 값. 모든 단계.

```json
{
  "wishes": [
    {
      "section_id": "2150164203-(공통-재수강)",
      "professor": "교수42",
      "cells": { "금-13:30": "BLOCK", "목-12:00": "BLOCK", "목-18:00": "PREFER", "화-09:00": "BLOCK",
                 "화-18:00": "PREFER", "화-19:30": "PREFER" },
      "must": false,
      "lab": "NONE",
      "single_day": "NONE",
      "building": "문화관",
      "room": null,
      "note": ""
    }
  ],
  "professors": { "교수42": { "sections": ["2150164203-(공통-재수강)", "2150166301"] } }
}
```
- `cells`: 칸 이름 `"요일-시작"` → `PREFER`(희망) / `BLOCK`(불가). **없는 칸 = 가능.**
- `must`: '꼭' 체크 (분반마다 하나).
- `lab`: 실습실 `MUST`(필요) / `NONE`(필요 없음).
- `single_day`: 주 1회 연강(하루에 두 교시를 이어서) `MUST`(무조건) / `PREFER`(선호) / `NONE`(필요 없음 = 주 2회, 기본). 하윤 DB `single_day_pref`와 같은 이름. 지금 데이터는 모두 `NONE`(가상 희망에 값이 없어 기본값).
- `professors`: 교수(가명)별 맡은 분반 id. 예전 '연강'(`consecutive`, 맡은 강의를 이어서 하기) 값은 팀 결정(11/21)으로 뺐다.

### `POST /wishes`
분반 하나의 희망을 저장한다(덮어씀). **COLLECT에서만.**

요청:
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "cells": { "월-09:00": "PREFER", "금-19:30": "BLOCK" },
  "must": false,
  "lab": "MUST",
  "single_day": "PREFER",
  "building": null,
  "room": null,
  "note": "화요일 오전 불가"
}
```
- `section_id`만 필수. 나머지는 빼면 기본값(`cells: {}`, `must: false`, `lab: "NONE"`, `single_day: "NONE"`, `note: ""`).
- `lab`은 `MUST`/`NONE`만 받는다. `PREFER`를 보내면 422.
- `professor`는 빼면 그 분반 담당 교수로 채운다.

응답 200:
```json
{ "saved": { "section_id": "2150164203-(공통-재수강)", "professor": "교수42",
             "cells": { "월-09:00": "PREFER", "금-19:30": "BLOCK" }, "must": false, "lab": "MUST",
             "single_day": "PREFER", "building": null, "room": null, "note": "화요일 오전 불가" } }
```

에러:
| 코드 | 언제 | detail |
|---|---|---|
| 422 | 칸 이름이 틀림 (토요일, `월-09:30` 같은 없는 시작 시각) | `[{"loc": ["body","cells"], "msg": "칸 이름은 '요일-시작'(예: 월-09:00)이어야 함: '토-09:00'"}]` |
| 422 | 칸 값이 `PREFER`/`BLOCK`이 아님, `lab`이 `MUST`/`NONE`이 아님(`PREFER` 포함), `single_day`가 `MUST`/`PREFER`/`NONE`이 아님 | Pydantic 목록 |
| 422 | 다른 교수 이름 | `이 분반의 담당 교수가 아닙니다.` |
| 404 | 없는 분반 | `분반이 없습니다: 없는-분반` |
| 409 | COLLECT가 아님 | `희망은 수집 단계(COLLECT)에서만 받습니다. 지금 단계: FINAL` |

### `POST /draft`
초안을 만든다. COLLECT → DRAFT. 요청 본문 없음. STUB: `make_draft`·`make_alternatives`·`check_rules`(문하윤).

응답 200:
```json
{
  "stage": "DRAFT",
  "assignments": 97,
  "status_count": { "MANUAL": 12, "COORD": 3, "DONE": 82 },
  "coord": ["2150164203-(공통-재수강)", "2150163304-(공통-재수강)", "2150164903-(공통-재수강)"],
  "violations": 0
}
```
- `coord`: 밀린 분반(조율 대상) id.
- `violations`: 하드 규칙 위반 수.

에러: 409 `초안은 수집 단계(COLLECT)에서 한 번만 만듭니다. 지금 단계: DRAFT`

### `GET /timetable`
현재 시간표. DRAFT·ROUND·FINAL.

```json
{
  "stage": "DRAFT",
  "round_no": 0,
  "status": "DRAFT",
  "assignments": [
    { "section_id": "2150162703-(공통-재수강)",
      "blocks": [ { "day": "월", "start": "16:30", "slots": 1, "room": "문화관 03407" },
                  { "day": "화", "start": "16:30", "slots": 1, "room": "정보과학관 21304" } ],
      "room": "문화관 03407", "status": "DONE", "reason": null },
    { "section_id": "2150164203-(공통-재수강)",
      "blocks": [ { "day": "화", "start": "18:00", "slots": 1, "room": "문화관 03407" },
                  { "day": "목", "start": "18:00", "slots": 1, "room": "문화관 03407" } ],
      "room": "문화관 03407", "status": "COORD",
      "reason": "희망 칸 화-19:30의 문화관 03407을(를) '오픈소스기초설계' 분반이 쓰고 있음 (가짜 값)" },
    { "section_id": "2150184201",
      "blocks": [ { "day": "토", "start": "13:30", "slots": 4, "room": "문화관 03105" } ],
      "room": "문화관 03105", "status": "MANUAL",
      "reason": "조교 직접 배정 분반 (수업 모양이 주 2회·주 1회 연강이 아님)" }
  ]
}
```
- `status`(시간표 전체): `DRAFT` / `ROUND` / `FINAL`.
- `room`은 대표 강의실(첫 수업의 강의실), 수업마다 강의실은 `blocks[].room`. 첫 분반은 두 수업의 강의실이 다른 예(가상).
- 과목명·교수는 `GET /sections`에서 `section_id`로 찾아 붙인다.

에러: 409 `아직 초안이 없습니다. POST /draft 를 먼저 부르세요.`

### `GET /coord`
조율 목록. 모든 단계(COLLECT는 `[]`).

> **조율 데이터 모양(대안·답장 해석·처리안)과 조율 함수의 입력·출력 상세는 [API_조율.md](API_조율.md)(최재성)를 따른다.**
> 이 문서는 서버 엔드포인트(경로·요청 본문·상태·에러)만 적는다. `Alternative`, `Meeting`, `Conditions`, `ReplyParse`, `Proposal`, `MessageInput`, `Message`의 칸 설명은 API_조율.md에서 본다.
> (API_조율.md는 지금 `jaeseong/coord` 브랜치에 있다. main에 합쳐지면 이 링크가 열린다.)
> 요일은 숫자 `0=월 … 4=금`. 시간표(`/timetable`)의 `blocks`는 요일 글자(`"월"`)라서 둘이 다르다.

```json
[
  {
    "section_id": "2150164203-(공통-재수강)",
    "name": "디지털시스템입문",
    "professor": "교수42",
    "reason": "희망 칸 화-19:30의 문화관 03407을(를) '오픈소스기초설계' 분반이 쓰고 있음 (가짜 값)",
    "round_no": 1,
    "state": "OPEN",
    "alternatives": [
      { "key": "A", "meetings": [ { "day": 1, "start": "18:00", "end": "19:15", "room": "문화관 03105" },
                                  { "day": 3, "start": "18:00", "end": "19:15", "room": "문화관 03105" } ] },
      { "key": "B", "meetings": [ "…" ] },
      { "key": "C", "meetings": [ "…" ] }
    ],
    "message": null,
    "proposal": null,
    "last_parse": null,
    "next_conditions": null,
    "prev_conditions": null
  }
]
```
- `state`: `OPEN`(메시지 전) → `SENT`(보냄) → `PROPOSED`(답장 해석, 처리안 있음) → `RESOLVED`(반영) / `KEPT`(현재대로 유지) / `NEXT`(조건을 넣어 다음 차수로, 조교가 확인함).
- `round_no`: DRAFT에서는 `null`.
- `alternatives`: 대안 0~3개 (`Alternative`). 없을 수도 있다.
- `message`: 보낸 글. `proposal`: 처리안(`Proposal`). `last_parse`: 마지막 답장 해석(`ReplyParse`).
- `next_conditions`: 이번 차수에 조교가 [확인]한 조건. `prev_conditions`: 지난 차수에서 넘어온 조건(2차 메시지에 쓴다).
- 다음 차수로 가면 `RESOLVED`가 아닌 분반은 `OPEN`으로 돌아가고 대안을 새로 받는다(`KEPT`·`NEXT` 포함).

### `POST /coord/{id}/message`
조율 메시지를 쓰고 검사한다. 검사를 통과해야 "보냄" 처리. **ROUND에서만.**
함수: `write_message(MessageInput, method)` → `check_message(text, MessageInput)`.

요청 본문은 없어도 된다. 있으면 `{ "method": "keyword" | "llm" }` (기본 `keyword`).

`MessageInput`은 서버가 채운다(`store.message_input`). 화면에서 받지 않는다.

| 칸 | 서버가 넣는 값 |
|---|---|
| `professor` | 받는 교수 가명 (`교수42`) |
| `course` | 과목 + 분반 번호 (+ 구분) `디지털시스템입문 03 (공통-재수강)` |
| `round` | 지금 차수 |
| `wish` | 희망(PREFER) 칸을 글로. 같은 시각끼리 묶음 `화·목 18:00, 화 19:30` |
| `alternatives` | 조율 목록의 대안 |
| `blocker_prof`, `blocker_course` | 희망 칸을 막은 상대 분반. 같은 강의실 → 같은 교수 순으로 찾은 **추정값** |
| `reveal` | 학과 설정 `reveal_opponent`(**기본 켬**, `POST /settings`로 끔). 켜져 있으면 메시지에 "○○ 교수님의 △△ 분반과 겹칩니다"가 들어간다. 끄면 "다른 강의와"로 쓰고, `check_message`가 이름이 새지 않았는지 검사한다 |
| `prev_conditions` | 2차부터, 지난 차수에 조교가 [확인]한 조건 |
| `hidden` | 상대 교수의 기타 요청(`note`). 검사에만 쓴다 |
| `term` | 기본 `2027-1학기` (환경변수 `COORD_TERM`으로 바꿈) |

연차·임용일·우선순위는 `MessageInput`에 칸이 없고 넣지 않는다.

응답 200 (진짜 `write_message`, keyword):
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "round_no": 1,
  "text": "교수42 교수님, 안녕하세요. 학과사무실입니다.\n2027-1학기 디지털시스템입문 03 (공통-재수강) 분반 시간표 1차 조율 안내드립니다.\n\n희망하신 시간(화·목 18:00, 화 19:30)이 다른 강의와 겹칩니다.\n\nA  화·목 18:00~19:15 · 문화관 03105\nB  화·목 18:00~19:15 · 벤처중소기업센터 10311\nC  화·목 18:00~19:15 · 정보과학관 21101\n\n가능한 안을 골라 주시거나, 모두 어려우시면 가능한 시간을 적어 주세요. 회신 기한은 1주이며, 기한 전에 한 번 더 알려 드립니다.",
  "method": "keyword",
  "fallback": false,
  "problems": [],
  "issues": [],
  "sent": true,
  "at": "2026-11-21T22:56:31"
}
```
- `method`·`fallback`·`problems`: `write_message` 결과(`Message`) 그대로. `llm`이 실패하면 `method: "keyword"`, `fallback: true`, `problems`에 이유(예: `호출 실패: ServerError: 503 UNAVAILABLE …`).
- `issues`: `check_message` 결과(문장 목록). 빈 목록이어야 보낸다.
- `sent: false`면 검사에 걸려 보내지 않은 것. 상태는 그대로 `OPEN`.
- 다시 부르면 다시 쓴다(`SENT` 상태에서도 가능).
- 에러 409: `대안이 없어 조율 메시지를 쓸 수 없습니다. [수정]이나 [현재대로 유지]로 정해 주세요.`

### `POST /coord/{id}/reply`
교수 답장을 해석해 처리안을 만든다. **반영은 안 한다.** ROUND에서만, 메시지를 보낸 뒤.
함수: `parse_reply(text, choice, alternatives=…, message=…, method=…)` → `match_conditions(parse, alternatives, round, unavailable)`.

요청:
```json
{ "text": "A나 C 다 괜찮아요. 수요일은 17시 전에 끝나야 해요", "choice": null, "method": "keyword" }
```
- `choice`: 교수가 화면 버튼으로 고른 안 `"A"`/`"B"`/`"C"`, 모두 어려움 `"none"`, 안 누름 `null`(기본). 버튼이 글보다 먼저다.
- `text`와 `choice` 중 하나는 있어야 한다(둘 다 비면 422).
- `alternatives`·`message`는 서버가 조율 목록의 대안과 보낸 글로 넣는다.
- `unavailable`: 서버가 지금 시간표에 대안을 넣어 보고(`check_rules`) 이 분반이 낀 위반이 생기는 안의 키.

응답 200 (진짜 `parse_reply`·`match_conditions`, keyword):
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "round_no": 1,
  "text": "A나 C 다 괜찮아요. 수요일은 17시 전에 끝나야 해요",
  "choice": null,
  "method": "keyword",
  "parse": {
    "kind": "조건부",
    "picks": ["A", "C"],
    "conditions": { "day_slots": {}, "end_before": [ { "day": 2, "time": "17:00" } ] },
    "note": "",
    "method": "keyword",
    "fallback": false
  },
  "proposal": {
    "action": "move",
    "key": "A",
    "conditions": { "day_slots": {}, "end_before": [ { "day": 2, "time": "17:00" } ] },
    "text": "A안(화·목 18:00~19:15 · 문화관 03105)으로 옮길까요?",
    "checks": [ { "key": "A", "ok": true, "why": "조건과 맞음" }, { "key": "C", "ok": true, "why": "조건과 맞음" } ]
  },
  "note": "",
  "unavailable": [],
  "at": "…"
}
```
- `parse.kind`: `수용` / `조건부` / `거절` / `확인 필요` (한글 그대로. `확인 필요`는 띄어 쓴다).
- `parse.conditions` (요일별 교시, 11/22): `{"day_slots": {요일 번호: [교시 시작 시각]}, "end_before": [...]}`.
  - 요일 번호는 0=월 … 4=금, JSON에서는 문자열 키(`"1"`).
  - 교시: 오전 = `["09:00", "10:30"]`, 점심 = `["12:00"]`, 오후 = `["13:30", "15:00", "16:30"]`, 늦은 오후 = `["16:30"]`, 저녁 = `["18:00", "19:30"]`. 8교시 시작 시각 밖의 값은 들어오지 않는다.
  - 빈 목록 = 그 요일은 아무 교시나. `day_slots`가 `{}`이면 요일·교시 제한 없음.
  - 요일이 둘 이상이면 수업이 그 요일들 안에서만(키 없는 요일 불가), 하나면 그 요일이 들어가기만 하면 된다(주 2회의 다른 하루는 자유). 연강은 두 교시가 모두 들어 있어야 맞는다.
  - 예: "화 오전이나 목 오후" = `{"1": ["09:00", "10:30"], "3": ["13:30", "15:00", "16:30"]}`, "화목이면 돼요" = `{"1": [], "3": []}`.
  - 옛 모양(`days`·`slots`)은 서버가 받아서 이 모양으로 바꿔 내보낸다. 답장 기록·처리안·`/coord`의 `prev_conditions`·`next_conditions`·`/decide`의 `applied` 모두 같은 모양.
- `note`: 조교가 확인할 교수 요청(예: `"실습용 PC가 있는 방"`). `parse.note`와 같은 값을 맨 위에도 둔다 — **화면은 처리안과 함께 보여 준다.** 배정·다음 차수 조건에는 쓰지 않는다(조교가 직접 처리). 언어 모델(`llm`)만 채우고 `keyword`는 항상 `""`. 자세한 규칙은 API_조율.md.
- `proposal.action`과 조교 버튼:
  - `move`: `key` 안으로 옮기자는 안. `[확인]`하면 옮긴다.
  - `next`: 맞는 안이 없음. `[확인]`하면 `conditions`를 기록해 다음 차수 대안에 쓴다(시간표는 안 바뀜).
  - `decide`: 확인 필요이거나 3차가 끝남. `[확인]` 안 됨. `[수정]` 또는 `[현재대로 유지]`.

거절 예 (진짜 함수, `method: "keyword"`, `choice: "none"`, 글 "셋 다 안 됩니다. 화요일 오후면 괜찮아요"):
```json
{ "parse": { "kind": "거절", "picks": [], "conditions": { "day_slots": { "1": ["13:30", "15:00", "16:30"] }, "end_before": [] }, "note": "", "method": "keyword", "fallback": false },
  "proposal": { "action": "next", "key": null, "conditions": { "…": "…" }, "text": "새 조건(화요일, 오후)으로 다음 차수 대안을 만들까요?", "checks": [] },
  "note": "" }
```

`note`가 있는 예 (언어 모델이 교수 요청을 뽑은 경우. 모양만 보이는 예):
```json
{ "parse": { "kind": "조건부", "picks": ["A"], "conditions": { "day_slots": {}, "end_before": [] }, "note": "실습용 PC가 있는 방", "method": "llm", "fallback": false },
  "proposal": { "action": "move", "key": "A", "…": "…", "text": "A안(…)으로 옮길까요? 교수님 요청: 실습용 PC가 있는 방" },
  "note": "실습용 PC가 있는 방" }
```

### `POST /coord/{id}/decide`
조교 결정. **이것을 불러야만 시간표나 다음 차수 조건이 바뀐다.** ROUND에서만. 함수: `reassign`·`check_rules`(문하윤).

요청 본문 `{action, reason, choice}`:

| action | 화면 버튼 | 필요한 값 | 하는 일 |
|---|---|---|---|
| `confirm` | [확인] | 없음 | 처리안이 `move`면 `key` 안으로 옮긴다. `next`면 조건을 기록하고 상태 `NEXT` |
| `edit` | [수정] | **`reason`(빈칸 안 됨)과 `choice`(`A`/`B`/`C`) 둘 다** | 조교가 고른 안으로 옮기고 사유를 남긴다 |
| `keep` | [현재대로 유지] | `reason`은 선택 | 안 옮긴다. 분반은 `COORD`로 남아 다음 차수로 간다 |

```json
{ "action": "edit", "reason": "교수님과 전화로 B안 합의", "choice": "B" }
```

응답 200 (confirm `move`·edit):
```json
{
  "decision": {
    "section_id": "2150164203-(공통-재수강)",
    "round_no": 1,
    "action": "confirm",
    "reason": null,
    "applied": { "key": "A", "meetings": [ { "day": 1, "start": "18:00", "end": "19:15", "room": "문화관 03105" },
                                           { "day": 3, "start": "18:00", "end": "19:15", "room": "문화관 03105" } ] },
    "at": "2026-11-21T22:56:35"
  },
  "coord": { "section_id": "2150164203-(공통-재수강)", "state": "RESOLVED", "…": "…" },
  "violations": 0
}
```
- 옮긴 분반은 시간표에서 `status: "DONE"`이 되고 `blocks`가 `applied.meetings`로 바뀐다. 수업마다 강의실은 `blocks[].room`(= `meetings[].room`), `room`은 첫 수업의 강의실.
- confirm `next` 응답은 `{decision, coord}`: `decision.action: "confirm_next"`, `applied`는 조건(`{"day_slots": {...}, "end_before": [...]}`), `coord.state: "NEXT"`.
- keep 응답은 `violations` 없이 `{decision, coord}` (`applied: null`, `state: "KEPT"`).

에러:

| 코드 | 언제 | detail |
|---|---|---|
| 422 | edit인데 사유 없음 | `수정하려면 사유(reason)를 적어야 합니다.` |
| 422 | edit인데 안 없음 | `수정하려면 고를 안(choice: A|B|C)을 적어야 합니다.` |
| 422 | 그 안이 없음 | `B안이 없습니다.` |
| 409 | confirm인데 답장 전 | `아직 처리안이 없습니다. 답장을 먼저 넣으세요.` |
| 409 | confirm인데 처리안이 decide | `조교가 직접 정해야 하는 처리안입니다 (action=decide). [수정]이나 [현재대로 유지]를 고르세요.` |
| 409 | 이번 차수에 이미 결정 | `이번 차수(1차)에 이미 결정한 분반입니다.` |

### 조율 3개(`message`·`reply`·`decide`) 공통 에러
검사 순서대로:

| 코드 | 언제 | detail |
|---|---|---|
| 404 | 없는 분반 | `분반이 없습니다: 없는-분반` |
| 409 | MANUAL 분반 | `조교 직접 배정 분반입니다. 자동 배정·조율 대상이 아닙니다.` |
| 409 | ROUND가 아님 | `조율은 차수 진행 중(ROUND)에만 할 수 있습니다. 지금 단계: DRAFT` |
| 409 | 조율 목록에 없는 분반 | `조율 대상 분반이 아닙니다: <id>` |
| 409 | 이미 RESOLVED·KEPT | `이번 차수(1차)에 이미 결정한 분반입니다.` |
| 409 | (reply만) 메시지 전 | `먼저 조율 메시지를 보내야 답장을 받을 수 있습니다.` |

### `POST /rounds/next`
다음 차수로. DRAFT → 1차, 1차 → 2차, 2차 → 3차. 요청 본문 없음.
2·3차로 갈 때 남은 분반의 대안을 새로 만든다(`make_alternatives(section_id, conditions)`, 문하윤).
`conditions`는 **조교가 [확인]한 조건(`next_conditions`)만** 쓴다. 확인하지 않은 답장 해석은 넣지 않는다(없으면 조건 없이). 답장 `note`도 넣지 않는다.

응답 200:
```json
{ "stage": "ROUND", "round_no": 2, "open": ["2150163304-(공통-재수강)", "2150164903-(공통-재수강)"] }
```
- `open`: 아직 반영 안 된 조율 분반.

2차 메시지 예 (조건 "화요일, 오후" = `{"day_slots": {"1": ["13:30", "15:00", "16:30"]}}`를 [확인]한 뒤, 진짜 `write_message`):
```text
2027-1학기 웹프로그래밍 03 (공통-재수강) 분반 시간표 2차 조율 안내드립니다.

지난 회신에서 주신 조건(화요일, 오후)을 반영해 대안을 다시 드립니다.
처음 희망하신 시간: 월 12:00, 월 13:30, 월·수 15:00

A  화 13:30~16:15 연강 · 정보과학관 21101
…
```

에러:

| 코드 | 언제 | detail |
|---|---|---|
| 409 | 3차 다음 | `최대 3차까지입니다. 남은 분반은 조교가 정해 확정(POST /finalize)하세요.` |
| 409 | COLLECT·FINAL | `다음 차수로 갈 수 없는 단계입니다: COLLECT` |

### `POST /finalize`
확정. DRAFT·ROUND → FINAL. 요청 본문 없음. STUB: `check_rules`(문하윤).

```json
{ "stage": "FINAL", "round_no": 3, "unresolved": ["2150163304-(공통-재수강)"], "violations": 0 }
```
- `unresolved`: 조율이 안 끝나 `COORD`로 남은 분반. 조교가 SAP에서 직접 정한다.

에러: 409 `확정할 수 없는 단계입니다: COLLECT` (COLLECT·FINAL)

### `GET /settings` · `POST /settings`
학과 설정. 모든 단계에서 보고 바꿀 수 있다. 바꾸면 그다음에 쓰는 조율 메시지부터 적용된다.

```json
{ "reveal_opponent": true }
```
- `reveal_opponent`: 조율 메시지에 겹친 상대 교수 이름 알리기. 기본 `true` (팀 결정: 기본 켬, 조교가 끌 수 있음).
- `POST /settings`는 바꿀 칸만 보낸다. 예: `{ "reveal_opponent": false }` → 바뀐 설정 전체를 돌려준다.
- 값 형식이 틀리면 422.
- `POST /reset` 하면 기본값으로 돌아간다.

### `POST /reset`
처음 상태(COLLECT)로. 희망 수정, 시간표, 조율·메시지·답장·결정 기록, 학과 설정이 모두 처음으로 돌아간다. 시연용.

```json
{ "stage": "COLLECT" }
```

### `POST /assistant`
조교 질문을 읽고(의도·정보) 배정 함수를 불러 설명한다. 모든 단계.
**시간표는 바꾸지 않는다.** 옮기기(move)는 제안만 만들고, `/assistant/apply`를 불러야 반영된다.
질문 해석은 키워드 기준선 또는 언어 모델(`backend/app/nlp/assistant.py`, `method`로 고름). 미리 보기·옮기기는 STUB `what_if`(문하윤).

요청:
```json
{
  "text": "확통 월수 12시로 옮겨줘",
  "history": [
    { "role": "user", "text": "자료구조 언제야?" },
    { "role": "assistant", "text": "자료구조 02분반 지금 배정: …", "section_id": "2150163202" }
  ],
  "method": "keyword"
}
```
- `history`: 앞 대화. 빼도 된다. **응답의 `section_id`를 assistant 항목에 넣어 보내면** "그 강의", "아까 그거", "그거"를 그 분반으로 읽는다.
- `method`: `keyword`(기본) 또는 `llm`.
  - `llm`: 언어 모델(Gemini)이 의도와 정보(과목명·분반 번호·교수·요일·시작 시각·강의실·건물)만 뽑는다. 프롬프트는 `backend/app/nlp/prompts/assistant.txt`.
  - 분반 id는 모델이 정하지 않는다. 모델이 쓴 과목명·번호를 키워드 버전과 같은 코드로 실제 분반에 연결한다.
  - 버리는 것: 질문·앞 대화 글에서 과목명 찾기로 찾히지 않는 과목, 질문·앞 대화에 (별칭으로도) 없는 건물, 질문에 없는 강의실 번호·시각 표현, 월~금이 아닌 요일, 없는 교수.
  - 시각은 모델이 질문의 말을 그대로(`time_text`) 넘기고, 위 시각 규칙(교시와 안 맞거나 때만 말하면 되묻기)을 키워드 버전과 같은 코드가 적용한다.
  - 되묻기(`ask_back`)와 옮길 수 있는지(교수 불가 시간·채플·18:00 연강)는 두 방식 모두 같은 코드가 판단한다.
  - 언어 모델이 실패하면(키 없음, 호출 실패, 형식 오류, 빈 질문) 오류 없이 키워드 방식으로 대신 처리한다. 이때 `command.method: "keyword"`, `command.fallback: true`, `command.fallback_reason`에 이유(예: `GEMINI_API_KEY가 없습니다`, `호출 실패: ServerError: 503 …`).
  - 옮기기는 `llm`이어도 제안만 만든다. `/assistant/apply` 전에는 반영하지 않는다.

응답 공통 모양:
| 키 | 뜻 |
|---|---|
| `command` | 읽은 의도·정보. `intent`, `section_id`, `professor`, `day`, `days`, `start`, `room`, `building`, `ask_back`, 그리고 `method`(실제로 쓴 방식), `fallback`(`llm` 실패로 키워드로 대신 처리했으면 `true`), `fallback_reason`(그 이유, 아니면 `null`) |
| `section_id` | 이 질문의 분반 (없으면 `null`). history에 넣는다 |
| `answer` | 화면에 보여 줄 문장 |
| `changes` | 표로 보여 줄 줄 `[{section_id, name, before, after, note}]` |
| `proposal_id` | move 제안 id. 있으면 [적용] 버튼을 보인다 |
| `needs_apply` | `true`면 아직 반영 안 됨. [적용]을 눌러야 함 |

의도(`command.intent`):
| 값 | 이런 말 | 하는 일 |
|---|---|---|
| `explain` | 왜, 이유, 어째서, 밀렸어, 언제야, 어디서 | 지금 배정, 희망 칸과 맞는지, 조율 중이면 밀린 이유 |
| `status` | 현황, 남은, 몇 개, 어디까지, 진행 | 단계·차수, 조율 중·답장 기다림·MANUAL 수 |
| `what_if` | 옮기면, 바꾸면, 비우면, 못 쓰면, ~면 어때, 될까, `?`로 끝남 | `what_if` 미리 보기. 반영 안 함 |
| `move` | 옮겨줘, 바꿔줘, 넣어줘 | 미리 보기 + 제안 저장 (`proposal_id`) |
| `out_of_scope` | 그 밖 | `시간표 편성·조율 관련 질문만 도울 수 있어요.` |

읽는 정보:
- 분반: 과목명(띄어쓰기 달라도 됨, 앞부분 일부도 됨), 줄임말 몇 개(운체, 자구, 확통, 웹프, 컴네 …), 분반 번호(`02`, `2분반` = 과목 코드 끝 두 자리), `재수강`, 과목 코드 10자리, 교수 가명(`교수07`).
- 요일: `월`, `월요일`, `월·수`, `월수`. 시각: `13:30`, `13시 반`, `1시 반`(1~7시는 오후), `오후 3시`. 교시 시작 시각(09:00·10:30·12:00·13:30·15:00·16:30·18:00·19:30)과 딱 맞을 때만 받는다.
  - 맞지 않으면(`2시`) 가장 가까운 교시로 바꾸지 않고 되묻는다: `14:00은 교시 시작 시각이 아니에요. 13:30과 15:00 중 언제로 할까요?`
  - 때만 말하면(`오전`·`오후`·`저녁`) 그 안의 교시를 되묻는다: `오후 교시는 13:30, 15:00, 16:30 중 언제로 할까요?` 교시가 하나뿐인 `늦은 오후`(16:30)·`밤`(19:30)은 그대로 받는다.
- 강의실: `21303`, `정보과학관 21303`. 건물만(`정보관`, `문화관` …) 말하면 `building`.
- 모자라면 `command.ask_back`에 되물을 말이 들어가고, `answer`도 그 문장이다. (예: 분반이 여러 개, 옮길 곳이 없음, 주 2회 분반인데 요일을 하나만 말함)

**explain** — `디지털시스템입문 재수강 분반 왜 밀렸어?`
```json
{
  "command": { "intent": "explain", "section_id": "2150164203-(공통-재수강)", "days": [], "start": null, "ask_back": null, "…": "…" },
  "section_id": "2150164203-(공통-재수강)",
  "answer": "디지털시스템입문 03분반 (공통-재수강) 지금 배정: 화 18:00~19:15 / 목 18:00~19:15 · 문화관 03407. 모두 교수 희망 칸 안이에요. 조율 중이에요 (메시지 보내기 전). 밀린 이유: 희망 칸 화-19:30의 문화관 03407을(를) '오픈소스기초설계' 분반이 쓰고 있음 (가짜 값)",
  "proposal_id": null, "changes": [], "needs_apply": false
}
```
MANUAL 분반이면 `…은(는) 조교 직접 배정 분반이에요(수업 모양이 주 2회·주 1회 연강이 아님). …`

**status** — `지금 현황 알려줘`
```json
{
  "command": { "intent": "status", "…": "…" },
  "answer": "지금은 조율 1차 단계예요. 조율 중 분반 3개 (메시지 전 3, 답장 기다림 0, 처리안 확인 기다림 0), 반영 끝 0개. 조교 직접 배정(MANUAL) 12개.",
  "changes": [
    { "section_id": "2150164203-(공통-재수강)", "name": "디지털시스템입문 03분반 (공통-재수강)", "before": null, "after": null, "note": "OPEN" }
  ],
  "proposal_id": null, "needs_apply": false
}
```
- status의 `changes`는 조율 중 분반 목록이다. `note` = 조율 `state`.

**what_if** — `확통을 월·수 13:30으로 옮기면 어때?`
```json
{
  "command": { "intent": "what_if", "section_id": "2150163102", "day": "월", "days": ["월", "수"], "start": "13:30", "…": "…" },
  "section_id": "2150163102",
  "answer": "확률및통계 02분반을(를) 월 13:30~14:45 / 수 13:30~14:45 · 정보과학관 21501(으)로 옮기면 같이 바뀌어야 하는 다른 분반 1개, 규칙 위반 1건이에요. (미리 보기만 했어요. 옮기려면 '옮겨줘'라고 말해 주세요.)",
  "changes": [
    { "section_id": "2150163102", "name": "확률및통계 02분반",
      "before": "월 12:00~13:15 / 화 12:00~13:15 · 정보과학관 21501",
      "after": "월 13:30~14:45 / 수 13:30~14:45 · 정보과학관 21501", "note": "옮김" },
    { "section_id": "2150134101", "name": "운영체제 01분반",
      "before": "월 13:30~16:15 · 정보과학관 21501", "after": "겹침 → 다시 배정 필요", "note": "영향 받음" }
  ],
  "proposal_id": null, "needs_apply": false
}
```
- 분반 없이도 된다: `수요일 15시를 비우면?`(그 시간 비우기), `21303 못 쓰면 어떻게 돼?`(강의실 못 씀). `changes`에 영향 받는 분반이 `note: "영향 받음"`으로 나온다.

**move** — `확통 월수 12시로 옮겨줘`
```json
{
  "command": { "intent": "move", "section_id": "2150163102", "days": ["월", "수"], "start": "12:00", "…": "…" },
  "section_id": "2150163102",
  "answer": "확률및통계 02분반을(를) 월 12:00~13:15 / 수 12:00~13:15 · 정보과학관 21501(으)로 옮기면 같이 바뀌어야 하는 다른 분반 0개, 규칙 위반 0건이에요. 아직 반영하지 않았어요. [적용]을 누르고 사유를 적으면 반영돼요.",
  "proposal_id": "…",
  "changes": [
    { "section_id": "2150163102", "name": "확률및통계 02분반",
      "before": "월 12:00~13:15 / 화 12:00~13:15 · 정보과학관 21501",
      "after": "월 12:00~13:15 / 수 12:00~13:15 · 정보과학관 21501", "note": "옮김" }
  ],
  "needs_apply": true
}
```
- 제안을 만들지 않는 경우(`proposal_id: null`): MANUAL 분반, 초안 전, FINAL 뒤(`시간표가 이미 확정됐어요…`), 이미 그 자리, 되묻기, 옮기면 안 되는 자리(아래).
- **요일 되묻기** (팀 결정): 주 2회 분반에 요일을 하나만 말하면 묶을 요일을 되묻는다. 주 1회 연강 분반은 요일 하나가 맞으므로 묻지 않는다. 주 1회 연강 분반에 요일 두 개를 말하면 하나만 달라고 되묻는다.
  - `확률및통계 금요일 저녁으로 바꿔줘` → `확률및통계 02분반은(는) 주 2회 수업이에요. 금요일과 묶을 요일을 하나 더 알려 주세요. (예: 수·금)`

**옮기지 않는 자리** (팀 결정. move와 what_if 모두. 미리 보기도 하지 않고 `changes: []`, `proposal_id: null`):

| 경우 | 예 (실제 응답) |
|---|---|
| 교수 불가 시간(`cells`의 `BLOCK`) | `확통 월수 3시로 옮겨줘` → `…(으)로는 옮기지 않아요. 교수 불가 시간(수-15:00)이에요. 다른 시간을 알려 주세요.` |
| 그 학년 채플 시간 | `확통 월수 10시 반으로 옮겨줘` (2학년) → `…(으)로는 옮기지 않아요. 2학년 채플 시간(월 10:30~11:20)과 겹쳐요. 그 시간은 비워 둬야 해요. 다른 시간을 알려 주세요.` |
| 18:00 시작 연강 | `자료구조 금요일 저녁 6시로 옮겨줘` → `…(으)로는 옮기지 않아요. 18:00에 시작하는 연강은 없어요(20:45에 끝나요). 더 이른 시각을 알려 주세요.` |

채플은 개설 강좌의 수강 대상을 보고 나눈다:
- **막음**: AI대학(AI소프트웨어학부·정보보호학과) 대상 채플 시간, 분반 학년이 그 채플 대상 학년과 같을 때만. 지금 데이터: 1학년 목 10:30~11:40(소그룹채플), 2학년 월 10:30~11:20, 3학년 화 15:00~15:50(비전채플).
- **경고만** (제안은 만든다): 모든 단과대학이 고르는 채플(독서채플 2~4학년 화 15:00·화 16:30·목 16:30, 비전채플 전체학년 수 10:30)이나 학년이 없는 분반. 답 끝에 `채플 시간(…)과 겹쳐요. 대상 학년이 정해지지 않은 채플이라 막지는 않았어요. 조교님이 확인해 주세요.`
- 다른 학과 대상 채플은 보지 않는다.

**19:30 교시**는 막지 않고 알린다(큰 감점, 팀 결정 11/21): `확통 화목 저녁 7시 반으로 옮겨줘` → `… 19:30 교시는 다른 방법이 없을 때만 쓰는 늦은 교시예요(큰 감점). 아직 반영하지 않았어요. …`

**out_of_scope** — `점심 뭐 먹지?`
```json
{ "command": { "intent": "out_of_scope", "…": "…" }, "answer": "시간표 편성·조율 관련 질문만 도울 수 있어요.",
  "proposal_id": null, "changes": [], "needs_apply": false }
```

**되묻기** — `알고리즘 왜 밀렸어?`
```json
{
  "command": { "intent": "explain", "section_id": null,
               "ask_back": "알고리즘은(는) 분반이 5개예요. 몇 분반인가요? (04분반 (공통-재수강)(교수02, 2150163304), 01분반(교수27, 2150163301), 02분반(교수27, 2150163302), 03분반(교수02, 2150163303), 01분반(교수32, 2150131601))" },
  "answer": "알고리즘은(는) 분반이 5개예요. 몇 분반인가요? (…)",
  "proposal_id": null, "changes": [], "needs_apply": false
}
```
- 같은 과목에 번호가 같은 분반이 있을 수 있다(알고리즘 01분반 2개). 그때는 교수 가명이나 과목 코드로 답하면 된다.

에러:
| 코드 | 언제 | detail |
|---|---|---|
| 501 | `method: "llm"` | `언어 모델(llm) 도우미는 다음 단계에서 구현합니다. method=keyword를 쓰세요.` |
| 422 | `text` 없음 | Pydantic 목록 |

### `POST /assistant/apply`
도우미 move 제안을 반영한다. **조교가 [적용]을 누르고 사유를 적었을 때만.** DRAFT·ROUND.
STUB: `reassign`·`check_rules`(문하윤).

요청:
```json
{ "proposal_id": "…", "reason": "교수님 전화 요청" }
```

응답 200:
```json
{
  "decision": {
    "section_id": "2150163102",
    "round_no": 1,
    "action": "assistant_move",
    "reason": "교수님 전화 요청",
    "applied": { "key": "A", "meetings": [ { "day": 0, "start": "12:00", "end": "13:15", "room": "정보과학관 21501" },
                                           { "day": 2, "start": "12:00", "end": "13:15", "room": "정보과학관 21501" } ] },
    "at": "…"
  },
  "summary": "확률및통계 02분반: 월 12:00~13:15 / 화 12:00~13:15 · 정보과학관 21501 → 월 12:00~13:15 / 수 12:00~13:15 · 정보과학관 21501",
  "violations": 1
}
```
- 이 예에서 미리 보기는 위반 0건인데 적용 뒤 1건이다. 가짜 `what_if`는 첫 번째 수업만 옮겨 보고 세기 때문이다(3절 참고).
- 수정 기록(조교 결정 기록)에 `action: "assistant_move"`와 사유가 남는다.
- 그 분반이 조율 목록에 있었으면 조율 `state`가 `RESOLVED`가 된다(조교가 직접 옮김).
- 제안은 한 번만 쓸 수 있다. `/reset` 하면 제안이 모두 사라진다.

에러:
| 코드 | 언제 | detail |
|---|---|---|
| 422 | 사유 없음·빈칸 | `적용하려면 사유(reason)를 적어야 합니다.` |
| 404 | 없는 제안, 이미 쓴 제안 | `제안이 없습니다: 1f30c8a9a57a` |
| 409 | FINAL | `시간표가 확정(FINAL)되어 적용할 수 없습니다.` |
| 409 | 제안 뒤 시간표가 바뀜(다른 결정·적용) | `제안을 만든 뒤 시간표가 바뀌었습니다. 도우미에게 다시 물어봐 주세요.` |

### `GET /export.xlsx`
확정(FINAL) 시간표를 엑셀 파일로 내려받는다. FINAL 단계에서만. 함수: `backend/app/export.py`의 `timetable_rows`(시간표 → 행 목록), `write_xlsx`(행 목록 → 파일).

- 응답 200: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, 파일 이름 `ssuroom_timetable.xlsx`.
- 시트 `확정 시간표`:
  - 1행: `가상/가명 데이터, SAP 실제 양식 아님(제안 양식). 교수 이름은 가명이다.`
  - 2행 열 이름: `과목 코드`, `과목명`, `분반`, `교수`, `요일·시간`, `강의실`
  - 3행부터 분반마다 한 행, 과목 코드 순. **MANUAL 분반도 들어간다.**
  - `분반` = 과목 코드 끝 두 자리(+ 재수강 표시). `교수` = 가명(없으면 `담당 미정`). `요일·시간` = `화 10:30~11:45 / 목 10:30~11:45` (칸이 없으면 `미배정`). `강의실`이 없으면 `미정`. 수업마다 강의실이 다르면 `요일·시간`과 같은 순서로 `문화관 03407 / 정보과학관 21304`처럼 짝지어 적는다.
- 409: FINAL 전. `확정(FINAL)한 뒤에 내보낼 수 있습니다. 지금 단계: ROUND`
- 지금은 서버 메모리의 시간표를 쓴다. 하윤 DB로 옮기면 `timetable_rows`만 바꾼다(`v_schedule`).

---

## 5. 시연 한 바퀴 (호출 순서)

```
POST /reset
GET  /settings                     (학과 설정: 상대 교수 이름 알리기)
GET  /sections, /rooms, /wishes
POST /wishes                       (교수 입력 화면, 여러 번)
POST /draft
GET  /timetable, /coord
POST /rounds/next                  → 1차
POST /coord/{id}/message           (조율 분반마다)
POST /coord/{id}/reply             (교수 답장)
POST /coord/{id}/decide            (조교 [확인]/[수정]/[현재대로 유지])
POST /rounds/next                  → 2차, 3차 (남은 분반만 다시)
POST /finalize

(언제든) POST /assistant           (조교 질문. move면 proposal_id가 옴)
         POST /assistant/apply     ([적용] + 사유. FINAL 전까지)
```

이 흐름은 `backend/tests/test_api.py`의 `test_full_flow`가 그대로 검사한다.
