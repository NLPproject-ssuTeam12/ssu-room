# 배정 엔진(solver_core.py) 사용법 — 조율·서버 쪽 참고

DB 연결은 항상 `db.connect()`로 한다. SQLite는 외래키 검사가 연결마다 꺼진 채로 시작해서,
`sqlite3.connect`를 직접 쓰면 잘못된 번호가 에러 없이 저장된다.

`db.py`는 `db/`에, `solver_core.py`는 `solver/`에 있다. 둘 다 `sys.path`에 있어야 아래처럼 부를 수 있다
(테스트는 `solver/tests/test_data.py`가 경로를 잡아 준다).

```python
import sys; sys.path[:0] = ["db", "solver"]      # 저장소 맨 위에서 실행할 때
import db, solver_core as sc
con = db.connect("ssuroom.db")
```

## 1. 초안 만들기 / 일부만 다시 풀기

```python
r = sc.solve(con, term_id, round_id, time_limit=60)
# r = dict(status, timetable_id, unplaced=[(과목,분반,회차)...], unsupported=[(과목,이유)...], objective, seconds)

# 교수 한 명의 응답이 바뀐 뒤: 그 교수 분반만 다시 풀고 나머지는 그대로 고정 (수 초 이내)
sc.solve(con, term_id, round_id, previous_timetable_id=tt,
         free_courses={(과목id, 분반번호), ...})        # 과목 id만 넣으면 그 과목의 모든 분반
```

## 2. 대안 만들기 — `make_alternatives` (= `alternatives`)

```python
opts = sc.make_alternatives(con, term_id, round_id, timetable_id, course_id,
                            section_no=2,            # 생략하면 과목의 모든 분반
                            condition={...},         # 생략 가능. 아래 참고
                            n=3)
```

조율 쪽이 넘기는 모양을 **그대로** `condition`에 받는다. 모든 칸이 선택 사항이다.

```json
{"days": [0, 2], "window": ["13:30", "17:45"], "end_before": [{"day": 2, "time": "17:00"}]}

요일마다 시간이 다르면 `by_day`를 쓴다:

```json
{"by_day": {"0": ["13:30", "14:45"], "2": ["15:00", "16:15"]}}
```
```

| 칸 | 뜻 | 엔진에서의 처리 |
|---|---|---|
| `days` | 되는 요일 (0=월 … 4=금) | 하나면 **그 요일이 들어간 안**, 둘 이상이면 **그 요일들 안에서만** |
| `window` | 되는 시간대 [시작, 끝] | 수업이 시작 ≥ 시작, 끝 ≤ 끝 이어야 함 (`"13:30"`–`"17:45"` = 4–6교시) |
| `by_day` | 요일별 시간대 `{"요일번호": [시작, 끝]}`. 한 요일에 여러 개면 `[[시작,끝],[시작,끝]]` | **적힌 요일에서만**, 그 요일의 시간대 안에서만(수업 전체가 범위 안에 들어가야 함). 요일 키는 `"0"`도 `0`도 됨 |
| `end_before` | 요일별로 끝나야 하는 시각 | 그 요일에 놓이는 수업은 끝 시각 ≤ time |
| `slot_ids` | 칸 번호 목록(위 셋 대신 써도 됨) | 수업이 차지하는 칸이 모두 목록 안에 있어야 함 |
| `day_slots` | 요일(0~4) → 그 요일에 되는 교시의 **시작 시각** 목록. 빈 목록 = 그 요일 아무 교시나 | 아래 "`day_slots`" 참고. 안에서 `days`·`slot_ids`로 바뀐다 |

- `days`(하나면 "그 요일이 들어간 안")와 `by_day`("적힌 요일에서만")는 뜻이 다르다. 한 요일만 허용하려면 `by_day`, 그 요일이 꼭 들어가면 되는 경우는 `days`.
- 시각은 75분 격자(1교시 09:00–10:15, 2교시 10:30–11:45, …)와 맞춰야 한다. 예를 들어 `["09:00","10:30"]`은 1교시만 통과한다(2교시는 10:30에 시작해서 범위를 벗어남).

### `day_slots`

```json
{"day_slots": {"0": ["13:30", "15:00"], "2": []}, "end_before": [{"day": 2, "time": "17:00"}]}
```

| `day_slots` | 솔버 조건으로 바뀐 모양 | 뜻 |
|---|---|---|
| 요일 둘 이상 | `slot_ids` = 그 요일들의 해당 교시 칸 (빈 목록이면 그 요일 전체 칸) | 수업은 그 요일들 안에서만, 각 요일은 적힌 교시에서만 |
| 요일 하나 | `days: [그 요일]` + `slot_ids` = 그 요일의 해당 교시 칸 + 나머지 요일 전체 칸 | 그 요일이 들어가야 하고(그 요일엔 적힌 교시만), 주 2회의 다른 하루는 자유 |
| 비어 있음(`{}`·`null`) | 없음 | 요일·교시 조건 없음 |

- `end_before`는 현재 형식 그대로 함께 쓴다(모두 AND).
- **연강(2칸 이어진 수업)** 은 두 교시가 모두 목록에 있어야 놓인다. 예: `{"3": ["13:30"]}`이면 목요일 연강은 15:00 교시가 빠져서 못 놓이고, `["13:30","15:00"]`이면 놓인다.
- 시작 시각은 격자의 교시 시작과 정확히 같아야 한다(`"9:00"`도 `"09:00"`로 본다). 어느 교시와도 안 맞으면 그 교시는 없는 것으로 보고, 갈 곳이 없으면 대안은 0개로 나온다(조건이 무시되지 않는다).
- `days`·`slot_ids`를 `day_slots`와 같이 주면 둘 다 만족해야 한다. 같이 쓰지 않는 편이 안전하다.

조건은 **대상 과목·분반에만** 적용된다. 시간은 `"HH:MM"` 0 채움 형식.

### 확인된 조건 흐름 (11/24)

교수가 자기 화면에서 쓴 답장은 `db.add_reply`로, 해석은 `db.save_interpretation`으로 DB에 남는다. 조교가 [확인]·[수정]을 누르면 서버가 `db.decide_reply(con, message_id, ta_id, 'CONFIRM' | 'EDIT', reason, conditions=...)`로 조건을 `reply_interpretation.extracted_json`의 `"confirmed_conditions"`에 저장한다. 다음 차수 대안을 만들 때 `cond = db.confirmed_conditions(con, proposal_id)`로 읽어 **바꾸지 않고** `alternatives(..., condition=cond)`에 넘긴다. 모양은 서버 `conditions_json`과 같은 `{"day_slots": {"1": [...]}, "end_before": [...]}`이고, 조교가 확인한 조건이 없으면(`[현재대로 유지]`, 결정 전, 조건 없이 [확인]) `None`이라 조건 없이 만든 대안과 같다. 엔진 코드는 바뀌지 않았고, `tests/run_cc.py`가 이 흐름([확인]·[수정]·조건 없음·결정 전)을 가상 데이터로 검사한다. 자세한 함수 설명은 `../db/README.md` "조율 회신".

**다음 차수로 조건 넘기기.** 처리안이 "다음 차수"이면 서버가 `db.decide_reply(..., 'CONFIRM', conditions=cond, proposal_action='next')`를 불러 안건을 `NEXT`로 둔다(조건이 비면 거부, 시간표는 그대로). 다음 차수를 열 때 `new = db.open_next_proposal(con, 이전 안건, 다음 차수 round_id)`로 같은 분반의 새 안건(`prev_proposal_id`로 이어짐)을 만들고, `cond = db.carried_conditions(con, new)`로 이전 차수에서 확인한 조건을 읽어 **바꾸지 않고** `alternatives(..., condition=cond)`에 넘긴다. 한 단계만 이어받으며(3차 안건은 2차에서 확인한 조건), 3차 다음 차수는 없다. 엔진 코드는 바뀌지 않았고(`timetable_section` INSERT에 칸 이름만 적음), `tests/run_cc.py` "[다음 차수]"가 이 흐름을 가상 데이터로 검사한다.

반환: 대안 리스트(최대 n개). 각 항목:

```python
dict(stage="다른 수업은 그대로" | "같은 교수·같은 학년 필수과목 일부 이동",
     placements={(분반, 회차): (시작 칸 id, 강의실 id)},
     ks={(분반, 회차): 한 회에 차지하는 칸 수},
     moves=[((과목, 분반, 회차), (이전 칸, 이전 방), (새 칸, 새 방))],   # 2단계에서 같이 움직인 다른 수업
     objective=...)
```

- 현재 배정과 같은 안은 나오지 않는다.
- 조건을 만족하는 안이 없거나 모자라면 리스트가 짧거나 비어 있다(= 교수에게 "가능한 안이 없다"고 알려야 하는 경우).
- 저장: `sc.save_proposal(con, round_id, timetable_id, course_id, opts, reason, section_no=2)`
  → `proposal`(분반 번호 포함), `proposal_option`, `proposal_option_slot`

## 3. 값의 뜻

| 항목 | 값 |
|---|---|
| 분반 수강 인원 `course_section.enrollment` | 정수(>0) 또는 NULL(미정). 정원이 더 작은 강의실은 후보에서 뺌 |
| 희망 건물 `professor_building_pref.building_id` | 교수당 하나. 그 밖의 건물은 벌점(`building_other`) |
| 실습실 `course_response.lab_requirement` | `1` 쓴다(실습실만 배정) / `0` 안 쓴다 (필수 입력) |
| 칠한 칸 `response_slot.kind` | `PREFER` 희망 / `BLOCK` 불가. 칠하지 않은 칸은 상관없음 |
| 주 1회 연강 `course_response.single_day_pref` | `MUST` 하루에 연속 2칸 / `NONE` 1칸씩 이틀 (필수 입력. `PREFER`는 11/24에 없앰) |
| 답장 해석 `reply_interpretation.label` | `ACCEPT` 수용 / `CONDITIONAL` 조건부 / `REJECT` 거절 / `UNCLEAR` 확인 필요 |

### 연강은 두 종류다 (용어 구분)

| 용어 | 뜻 | 어디서 받나 |
|---|---|---|
| **주 1회 연강** | 한 분반이 **하루에 2칸을 이어서** 수업 (예: 화 3·4교시). 3학점 수업이 이틀 나눠 하지 않고 하루에 끝남 | 교수 응답 `single_day_pref` (MUST/NONE) |
| **분반 연강** | 한 교수가 한 과목의 두 분반을 맡을 때 **가반이 끝나자마자 나반**이 이어짐. 교차는 가반 월1·목2, 나반 월2·목1처럼 엇갈리게 | 교수 응답 `course_response.section_pair` (`NONE` / `BACK_TO_BACK` / `CROSS`, 11/24) |

- 주 1회 연강은 **주당 2칸짜리 수업(1칸×2회)** 에만 적용된다. 그 외 수업은 입력된 구성 그대로.
- 응답이 없는 분반(미회신)은 입력된 구성 그대로 두고 주 1회 연강을 가정하지 않는다.

## 4. 분반별 담당 교수

- `course_section(course_id, section_no, professor_id, enrollment)` 한 행이 분반 하나다. 그 교수가 맡고, `enrollment`가 그 분반 수강 인원이다. 과목에 행이 없으면 `course.professor_id`의 1분반 하나로 본다.
- 교수 겹침 검사, 불가 시간·실습실·연강 응답은 **분반의 담당 교수 기준**이다.
  응답(`course_response`)도 교수별로 받는다: `UNIQUE (round_id, course_id, professor_id)`.
- 같은 과목의 분반을 다른 교수가 맡으면, 그 교수의 응답이 없을 때 그 분반은 미회신으로 본다.
- `v_schedule`, `v_professor_conflict` 뷰도 분반 담당 교수를 따른다.

## 5. 분반 수, 수강 인원, 희망 건물 (11/24)

- 분반은 오프라인 회의에서 정해진 상태로 시작한다. 분반 수 = 그 과목의 `course_section` 행 수. 번호는 1부터 빈틈없어야 하고, 아니면 `load_input`이 `ValueError`를 낸다. 교수 요청 `SECTION_COUNT`는 읽지 않는다.
- 두 교수가 같은 시간대에 수업해도 된다(다른 강의실이면). 교수 겹침은 분반 담당 교수 기준으로만 막는다.
- 수강 인원: `enrollment`보다 정원이 작은 강의실은 그 분반의 후보에서 뺀다(필수). NULL이면 검사하지 않는다. 시간표의 `timetable_section.planned_enrollment`에 그 값을 그대로 적는다.
- 희망 건물: 교수당 하나. 다른 건물에 놓으면 `building_other`(기본 50, 큰 벌점) 벌점. 응답 없는 교수는 전년 확정본에서 가장 많이 쓴 건물을 희망 건물로 본다.
- "선호 시간 외 불가"(`prefer_only`)와 강의 언어(`language`)는 없앴다(006).
- 필수과목(같은 학과·같은 학년(`course.target_year`)끼리만, 학년이 다르면 겹쳐도 됨): 교양필수↔전공필수는 겹치지 않는다(하드), 교양필수끼리는 겹쳐도 된다. 서로 다른 전공필수 과목은 겹치지 않는다. 다만 두 과목 모두 분반이 둘 이상이면 일부 겹쳐도 된다(분반마다 안 겹치는 상대 분반이 하나 이상 있어야 함). 같은 과목에서 교수가 다른 분반끼리는 겹쳐도 된다(하드). 분반 수는 `course_section` 행 수.
- 채플: `chapel_slot(term_id, target_year, slot_id)`의 칸에는 그 학년 전공필수를 놓지 않는다(하드).
- 대안 2단계는 같은 교수의 다른 수업과, 대상과 겹칠 수 없는 같은 학년 필수과목(교필↔전필, 다른 전필)을 함께 움직일 수 있다.
- 시간: 19:30 교시는 `late`(기본 60) 감점, 연속 2칸 이상 수업은 18:00 이후에 시작하지 않는다(하드).
- 대안은 분반별 시작 칸 집합으로 비교한다. 회차 순서만 바꾼 같은 안은 다시 나오지 않는다.

## 5-1. 교수 답장 선택과 수동 배치 (11/25)

```python
best = sc.pick_best(con, term_id, round_id, timetable_id, course_id, section_no,
                    option_ids=[A안 id, B안 id], condition=기타_조건_또는_None,
                    respect_order=False)   # 교수가 글로 순서를 밝혔으면 True, option_ids 를 그 순서로
# -> 좋은 순 [dict(source='A'|'B'|'C'|'ETC', option_id, feasible, objective, stage, placements, ks, moves)]
new_id = sc.add_option(con, proposal_id, best[0])      # source 'ETC'(기타 조건으로 만든 안)를 쓸 때 4번 대안으로 저장
sc.load_option(con, option_id)                         # 저장된 대안 → placements·ks·slots
sc.check_timetable(con, timetable_id)                  # 하드 규칙 위반 목록 (수동 배치 경고용)
```

- 순서: `respect_order=False`(버튼만 누름)면 점수 순, `True`(교수가 "A가 제일 좋고 안 되면 B"처럼 밝힘)면 `option_ids` 순서를 점수보다 먼저 지킨다. 놓을 수 있는 안 중 앞 순서가 첫째이고, 기타 조건으로 만든 새 안은 밝힌 순서 뒤.
- `pick_best`는 고른 안마다 **지금 시간표에서 그 안의 칸에만 놓도록** 풀어 엔진 점수(낮을수록 좋음)를 비교한다. 다른 수업은 그대로이고, 안 되면 같은 교수·같은 학년 필수과목을 조금 움직여 본다. 그래도 안 되면 `feasible=False`(맨 뒤).
- 고정: 이전 시간표에서 `timetable_section.locked=1`인 분반은 `solve`(부분·전체)·`alternatives`·`pick_best`에서 움직이지 않는다. 고정 분반의 대안을 만들려 하면 `ValueError`(먼저 `db.set_lock`으로 푼다). 새 시간표에도 `MANUAL`·고정이 이어진다.
- 수동 배치가 규칙을 어긴 채 고정돼 있어도 풀이가 막히지 않는다: 고정끼리의 위반은 그대로 두고, 나머지 수업이 피한다.

## 5-2. 처리안을 새 시간표 버전으로 저장 (11/25)

```python
rows = sc.option_rows(con, option_id=B안_id)                       # 또는 option_rows(con, option=대안, timetable_id=기준)
new_tt = sc.apply_option(con, proposal_id, ta_id, rows, "교수님과 통화로 확인",
                         base_timetable_id=현재_시간표)              # 안건 없으면(도우미 [적용]) proposal_id=None, course_id=과목
# 이후 alternatives(..., new_tt, ...)·solve(previous_timetable_id=new_tt) 로 다음 차수
```

- 기준 버전을 복사해 `TA_EDIT`(parent=기준 버전) 새 버전을 만들고 rows의 분반만 바꾼다. 기준 버전에 없던 하드 규칙 위반(`check_timetable`)이 새로 생기면 저장하지 않고 `ValueError`. 안건은 `RESOLVED`, 사유는 `timetable.reason`.
- 저장 뒤에는 **새 id를 현재 시간표로** 써야 한다. 다음 차수 `alternatives`는 그 버전의 배정을 '현재 배정'으로 보고 같은 안을 빼고, `solve(previous_timetable_id=새 id)`는 그 배정을 유지 보너스로 지킨다(`tests/run_apply.py`).

## 6. 서버 단계와 기타 요청 (`db.py`)

```python
db.get_phase(con, term_id)                    # ('ROUND1', '1차 조율')
db.set_phase(con, term_id, 'ROUND2', user_id) # 한 칸씩만. 건너뛰기·되돌리기는 force=True. phase_log에 기록
db.pending_other_requests(con, round_id)      # 조교가 아직 확인 안 한 기타 요청
db.confirm_other_request(con, other_request_id, user_id, memo=None)
```

- 단계: `COLLECTING` 희망 수집 → `ROUND1` 1차 조율 → `ROUND2` 2차 조율 → `ROUND3` 3차 조율 → `FINAL` 확정.
- 기타 요청은 AI를 거치지 않는다. 교수 원문(`other_request.body`, `PENDING`) → 조교가 읽고 필요하면 `request_item`(`source='TA'`, `other_request_id`)을 직접 입력 → "확인함"(`CONFIRMED`).
- 11/24부터 솔버는 `request_item`을 읽지 않는다. 분반 수는 `course_section`, 분반 연강·교차는 응답의 `section_pair`로 받는다. `request_item`은 조교가 남기는 기록이다.

## 7. 알려진 한계

- 분반 연강·교차(`section_pair`)는 그 교수가 그 과목에서 맡은 분반이 정확히 2개이고 1회 한 칸일 때만 지원. 이때 주 1회 연강 응답은 무시된다(`unsupported`에 표시).
- 풀이 시간: 조건이 빡빡한 분반 연강·교차 과목이 있으면 30초 안에는 일부가 못 놓일 수 있다. 60~90초를 권장.
