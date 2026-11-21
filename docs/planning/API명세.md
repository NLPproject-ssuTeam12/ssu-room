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
- 테스트: `python -m pytest backend/tests -q`

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
| `POST /assistant` `/assistant/apply`, `GET /export.xlsx` | 501 (다음 단계) | | | |

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
{ "day": "화", "start": "18:00", "slots": 1 }
```
- `day`: 월~금. **토요일(`토`)은 MANUAL 분반에만** 나온다(실제 데이터에 2개).
- `start`: 보통 8칸 중 하나 — `09:00 10:30 12:00 13:30 15:00 16:30 18:00 19:30`.
- `slots`: 칸 수. 1칸 = 75분, 2칸 = 165분(쉬는 시간 15분 포함). 끝 시각 = 시작 + 75×칸 + 15×(칸−1).

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

진짜/가짜 확인: `GET /health` 의 `engine`. 값이 `"stub"`이면 가짜, `"real (모듈 이름)"`이면 진짜다.
진짜 모듈이 있는데 불러오다 실패하면 가짜로 돌고 `load_warnings`에 `"parse_reply 함수: 진짜 모듈 불러오기 실패 → 가짜 사용 (이유)"`가 생긴다.

가짜 값에서 알아 둘 것:
- 조율 이유 문장 끝에 `(가짜 값)`이 붙는다.
- 대안 A·B·C는 같은 강의실을 쓰는 다른 분반과의 겹침만 피한다. 교수·학년 겹침은 안 본다.
- 답장 해석은 `method`와 상관없이 간단한 키워드로 읽는다.

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
- `lab_need`: `MUST`(필수) / `PREFER`(있으면 좋음) / `NONE`.

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
      "cells": { "화-09:00": "BLOCK", "화-18:00": "PREFER", "목-18:00": "PREFER" },
      "must": false,
      "lab": "PREFER",
      "building": "문화관",
      "room": null,
      "note": ""
    }
  ],
  "professors": { "교수41": { "consecutive": "상관없음" } }
}
```
- `cells`: 칸 이름 `"요일-시작"` → `PREFER`(희망) / `BLOCK`(불가). **없는 칸 = 가능.**
- `must`: '꼭' 체크 (분반마다 하나).
- `professors.*.consecutive`: 연강 선호 `좋음` / `싫음` / `상관없음`.

### `POST /wishes`
분반 하나의 희망을 저장한다(덮어씀). **COLLECT에서만.**

요청:
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "cells": { "월-09:00": "PREFER", "금-19:30": "BLOCK" },
  "must": false,
  "lab": "PREFER",
  "building": null,
  "room": null,
  "note": "화요일 오전 불가"
}
```
- `section_id`만 필수. 나머지는 빼면 기본값(`cells: {}`, `must: false`, `lab: "NONE"`, `note: ""`).
- `professor`는 빼면 그 분반 담당 교수로 채운다.

응답 200:
```json
{ "saved": { "section_id": "2150164203-(공통-재수강)", "professor": "교수42",
             "cells": { "월-09:00": "PREFER", "금-19:30": "BLOCK" }, "must": false, "lab": "PREFER",
             "building": null, "room": null, "note": "화요일 오전 불가" } }
```

에러:
| 코드 | 언제 | detail |
|---|---|---|
| 422 | 칸 이름이 틀림 (토요일, `월-09:30` 같은 없는 시작 시각) | `[{"loc": ["body","cells"], "msg": "칸 이름은 '요일-시작'(예: 월-09:00)이어야 함: '토-09:00'"}]` |
| 422 | 칸 값이 `PREFER`/`BLOCK`이 아님, `lab` 값이 틀림 | Pydantic 목록 |
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
      "blocks": [ { "day": "월", "start": "16:30", "slots": 1 }, { "day": "화", "start": "16:30", "slots": 1 } ],
      "room": "문화관 03407", "status": "DONE", "reason": null },
    { "section_id": "2150164203-(공통-재수강)",
      "blocks": [ { "day": "화", "start": "18:00", "slots": 1 }, { "day": "목", "start": "18:00", "slots": 1 } ],
      "room": "문화관 03407", "status": "COORD",
      "reason": "희망 칸 화-19:30의 문화관 03407을(를) '오픈소스기초설계' 분반이 쓰고 있음 (가짜 값)" },
    { "section_id": "2150184201",
      "blocks": [ { "day": "토", "start": "13:30", "slots": 4 } ],
      "room": "문화관 03105", "status": "MANUAL",
      "reason": "조교 직접 배정 분반 (수업 모양이 주 2회·주 1회 연강이 아님)" }
  ]
}
```
- `status`(시간표 전체): `DRAFT` / `ROUND` / `FINAL`.
- 과목명·교수는 `GET /sections`에서 `section_id`로 찾아 붙인다.

에러: 409 `아직 초안이 없습니다. POST /draft 를 먼저 부르세요.`

### `GET /coord`
조율 목록. 모든 단계(COLLECT는 `[]`).

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
      { "label": "A", "blocks": [ { "day": "화", "start": "18:00", "slots": 1 }, { "day": "목", "start": "18:00", "slots": 1 } ],
        "room": "문화관 03105" },
      { "label": "B", "blocks": [ "…" ], "room": "벤처중소기업센터 10311" },
      { "label": "C", "blocks": [ "…" ], "room": "정보과학관 21101" }
    ],
    "message": null,
    "proposal": null,
    "last_parse": null
  }
]
```
- `state`: `OPEN`(메시지 전) → `SENT`(보냄) → `PROPOSED`(답장 해석, 처리안 있음) → `RESOLVED`(반영) 또는 `KEPT`(현재대로 유지).
- `round_no`: DRAFT에서는 `null`.
- `alternatives`: 0~3개. 없을 수도 있다.
- `message`: 보낸 글. `proposal`: 처리안(아래 `reply` 참고). `last_parse`: 마지막 답장 해석.
- 다음 차수로 가면 `RESOLVED`가 아닌 분반은 `OPEN`으로 돌아가고 대안을 새로 받는다(`KEPT` 포함).

### `POST /coord/{id}/message`
조율 메시지를 쓰고 검사한다. 검사를 통과해야 "보냄" 처리. **ROUND에서만.** 요청 본문 없음.
STUB: `write_message`·`check_message`(최재성).

응답 200:
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "round_no": 1,
  "text": "교수님, 안녕하세요. 학과사무실입니다.\n[1차 조율] 디지털시스템입문 (공통-재수강) 분반의 희망 시간이 다른 강의와 겹쳐 아래 대안을 드립니다.\n- 적어 주신 희망: 목-18:00, 화-18:00, 화-19:30\n- A안: 화 18:00~19:15 / 목 18:00~19:15 · 문화관 03105\n…\n회신 기한은 1주입니다.",
  "issues": [],
  "sent": true,
  "at": "2026-11-21T17:36:19"
}
```
- `issues`: 검사에 걸린 것 `[{"kind": "금지 내용" | "필수 내용 빠짐", "detail": "…"}]`.
- `sent: false`면 검사에 걸려 보내지 않은 것. 상태는 그대로 `OPEN`.
- 다시 부르면 다시 쓴다(`SENT` 상태에서도 가능).

### `POST /coord/{id}/reply`
교수 답장을 해석해 처리안을 만든다. **반영은 안 한다.** ROUND에서만, 메시지를 보낸 뒤.
STUB: `parse_reply`·`match_conditions`(최재성).

요청:
```json
{ "text": "A나 C 다 괜찮아요. 수요일은 17시 전에 끝나야 해요", "method": "keyword" }
```
- `method`: `keyword`(기준선, 기본) 또는 `llm`(언어 모델).

응답 200:
```json
{
  "section_id": "2150164203-(공통-재수강)",
  "round_no": 1,
  "text": "A나 C 다 괜찮아요. 수요일은 17시 전에 끝나야 해요",
  "method": "keyword",
  "parse": {
    "decision": "조건부",
    "chosen": ["A", "C"],
    "conditions": { "days": [], "time_ranges": [], "end_before": { "수": "17:00" } }
  },
  "proposal": {
    "action": "MOVE",
    "alternative": { "label": "A", "blocks": [ "…" ], "room": "문화관 03105" },
    "summary": "A안으로 옮길까요?",
    "rejected": []
  },
  "at": "2026-11-21T17:36:19"
}
```
- `parse.decision`: `수용` / `조건부` / `거절` / `확인필요`.
- `conditions`: 가능한 요일 `days`, 가능한 시간대 `time_ranges: [{start, end}]`, 요일별 종료 시각 `end_before`.
- `proposal.action`:
  - `MOVE`: `alternative`로 옮기자는 안. `[확인]`을 누를 수 있다.
  - `ASK`: 옮길 안이 없음(거절·확인필요·조건과 다 안 맞음). `[수정]` 또는 `[현재대로 유지]`만.
  - `KEEP`: 지금 자리 유지 제안.
- `rejected`: 조건과 안 맞아 뺀 안과 이유. 예: `"A안은 수 16:30~17:45 종료라 '수 17:00 전 종료'와 안 맞음"`.

거절 예:
```json
{ "parse": { "decision": "거절", "chosen": [], "conditions": { "…": "…" } },
  "proposal": { "action": "ASK", "alternative": null, "summary": "거절: 다음 차수에 새 대안이 필요합니다.", "rejected": [] } }
```

### `POST /coord/{id}/decide`
조교 결정. **이것을 불러야만 시간표가 바뀐다.** ROUND에서만. STUB: `reassign`·`check_rules`(문하윤).

요청 본문 `{action, reason, choice}`:
| action | 화면 버튼 | 필요한 값 | 하는 일 |
|---|---|---|---|
| `confirm` | [확인] | 없음 | 처리안(`proposal.action == "MOVE"`)의 안으로 옮긴다 |
| `edit` | [수정] | **`reason`(빈칸 안 됨)과 `choice`(`A`/`B`/`C`) 둘 다** | 조교가 고른 안으로 옮기고 사유를 남긴다 |
| `keep` | [현재대로 유지] | `reason`은 선택 | 안 옮긴다. 분반은 `COORD`로 남아 다음 차수로 간다 |

```json
{ "action": "edit", "reason": "교수님과 전화로 B안 합의", "choice": "B" }
```

응답 200 (confirm·edit):
```json
{
  "decision": {
    "section_id": "2150164203-(공통-재수강)",
    "round_no": 1,
    "action": "confirm",
    "reason": null,
    "applied": { "label": "A", "blocks": [ "…" ], "room": "문화관 03105" },
    "at": "2026-11-21T17:36:19"
  },
  "coord": { "section_id": "2150164203-(공통-재수강)", "state": "RESOLVED", "…": "…" },
  "violations": 0
}
```
- 옮긴 분반은 시간표에서 `status: "DONE"`이 된다.
- keep 응답은 `violations` 없이 `{decision, coord}` (`applied: null`, `state: "KEPT"`).

에러:
| 코드 | 언제 | detail |
|---|---|---|
| 422 | edit인데 사유 없음 | `수정하려면 사유(reason)를 적어야 합니다.` |
| 422 | edit인데 안 없음 | `수정하려면 고를 안(choice: A|B|C)을 적어야 합니다.` |
| 422 | 그 안이 없음 | `B안이 없습니다.` |
| 409 | confirm인데 답장 전 | `아직 처리안이 없습니다. 답장을 먼저 넣으세요.` |
| 409 | confirm인데 처리안이 ASK | `처리안에 옮길 안이 없습니다. [수정]이나 [현재대로 유지]를 고르세요.` |
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
2·3차로 갈 때 남은 분반의 대안을 새로 만든다(STUB: `make_alternatives`, 문하윤).

응답 200:
```json
{ "stage": "ROUND", "round_no": 2, "open": ["2150163304-(공통-재수강)", "2150164903-(공통-재수강)"] }
```
- `open`: 아직 반영 안 된 조율 분반.

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

### `POST /reset`
처음 상태(COLLECT)로. 희망 수정, 시간표, 조율·메시지·답장·결정 기록이 모두 지워진다. 시연용.

```json
{ "stage": "COLLECT" }
```

### 다음 단계에서 구현 (지금은 501)
| 엔드포인트 | 하는 일 | 지금 응답 |
|---|---|---|
| `POST /assistant` | AI 도우미 질문 → 설명 + 변경 표 | 501 `AI 도우미는 다음 단계에서 구현합니다.` |
| `POST /assistant/apply` | 도우미 변경 적용 (조교 [적용]) | 501 `AI 도우미 적용은 다음 단계에서 구현합니다.` |
| `GET /export.xlsx` | 엑셀 내보내기 | 501 `엑셀 내보내기는 다음 단계에서 구현합니다.` |

---

## 5. 시연 한 바퀴 (호출 순서)

```
POST /reset
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
```

이 흐름은 `backend/tests/test_api.py`의 `test_full_flow`가 그대로 검사한다.
