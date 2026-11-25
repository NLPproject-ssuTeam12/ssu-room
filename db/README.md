# db — 데이터베이스

SSU:room의 SQLite 스키마, 변경 SQL, 연결·단계 관리 함수입니다. 배정 엔진은 `../solver/`에 있습니다.
교수 응답·시간표 버전·조율 기록이 모두 이 DB에 저장됩니다.

## 파일

| 파일 | 내용 |
|---|---|
| `schema.sql` | **최종 DB 스키마** (테이블 29개, 뷰 2개). 새 DB는 이 파일로 만든다 |
| `db.py` | DB 연결(`connect`, **항상 이걸로** 외래키 검사를 켠다), 서버 단계(`get_phase` `set_phase`), 기타 요청 확인(`pending_other_requests` `confirm_other_request`), 조율 회신(`professor_owns` `add_reply` `save_interpretation` `decide_reply` `confirmed_conditions` `open_next_proposal` `carried_conditions`) |
| `seed_time_slot.py` | 시간 칸(75분 교시) 기본 데이터 |
| `migrations/001_20261121_feedback.sql` | `archive/schema_v3.sql`로 만든 DB → 11/21 피드백 반영 모양 |
| `migrations/002_20261122_phase_other_request.sql` | 001까지 적용한 DB → 단계 관리, 선호 시간 외 불가, 기타 요청 재설계 |
| `migrations/003_20261122_lab_binary_no_avoid.sql` | 002까지 적용한 DB → `AVOID` 제거, 실습실 0/1 |
| `migrations/004_20261122_phase_round3.sql` | 003까지 적용한 DB → 단계에 `ROUND3`(3차 조율) 추가 |
| `migrations/006_20261124_section.sql` | 005까지 적용한 DB → `course_section.enrollment` 추가, `course.expected_enrollment`·`course_response.prefer_only`·`language` 삭제, 희망 건물 교수당 하나 |
| `migrations/007_20261125_reply_choice.sql` | 006까지 적용한 DB → 답장 선택 `reply_choice`, 안건 상태 `OFFLINE`, 분반 고정 `timetable_section.locked`, 답장 기타 요청(`other_request.message_id`) |
| `migrations/008_20261125_timetable_reason.sql` | 007까지 적용한 DB → 시간표 버전 사유 `timetable.reason` |
| `migrations/009_20261125_section_response.sql` | 008까지 적용한 DB → 희망 입력을 분반마다(`course_response.section_no`), 분반 연강·교차 요청 `pair_request`·`pair_request_section`(`section_pair` 칸 삭제), 안건 상태 `HOLD`·`NO_OPTION`과 조율 대상 종류 `proposal.target_kind` |
| `migrations/005_20261124_reply.sql` | 004까지 적용한 DB → `message.reply_to_id`, `proposal.prev_proposal_id`, `timetable_section.status` 추가, `proposal.status` 값 6개로 고정(`WAITING`→`OPEN`) |
| `docs/c1.png` `c2.png` `c3.png` | ER 다이어그램 (원본 `c1.mmd` `c2.mmd` `c3.mmd`) |
| `tests/test_migration.py` | 변경 SQL 검사 |
| `tests/test_reply.py` | 조율 회신 함수 검사 (메모리 DB, 가상 데이터) |
| `archive/schema_v1~v11.sql` | 지난 버전 (참고용). v4 = 001까지, v5 = 002까지, v6 = 003까지, v7 = 004까지, v8 = 005까지, v9 = 006까지, v10 = 007까지, v11 = 008까지 적용한 모양 |

ER 다이어그램: `c1.png` 기초 정보(학과·교수·강의실·과목·분반 교수·시간 칸·학기 단계), `c2.png` 1차 응답 수집·기타 요청, `c3.png` 시간표·대안·메시지.

## 빠른 시작

```bash
# 저장소 맨 위에서
python -c "
import sys; sys.path.insert(0, 'db')
import db
con = db.connect('ssuroom.db')
con.executescript(open('db/schema.sql', encoding='utf-8').read())
"
python db/tests/test_migration.py    # 변경 SQL 검사 (오류 없이 '모두 통과')
python db/tests/test_reply.py        # 조율 회신 함수 검사 (pytest 로도 돈다)
```

**연결은 항상 `db.connect()`로 합니다.** SQLite는 연결마다 외래키 검사가 꺼진 채로 시작해서, `sqlite3.connect`를 직접 쓰면 잘못된 번호가 에러 없이 저장됩니다.

## 용어 (섞어 쓰지 말 것)

| 용어 | 뜻 | DB에서 어디 |
|---|---|---|
| **주 1회 연강** | 한 분반이 **하루에 2칸을 이어서** 수업 (예: 화 3·4교시). MUST 하루에 이어서 / NONE 이틀 나눠도 됨 (선호는 11/24에 없앰) | 분반 응답 `course_response.single_day_pref` |
| **분반 연강** | 한 교수가 한 과목의 분반 둘 이상을 맡을 때 **앞 분반이 끝나자마자 다음 분반**. 교수가 붙일 분반을 순서대로 고른다(두 분반만 붙이고 나머지는 떨어뜨려도 됨). 솔버는 **앞 두 분반만** 붙이고 셋째부터는 조교가 수동 배치·고정 | 과목 단위로 한 번 `pair_request.mode` = `BACK_TO_BACK`, 붙일 분반 `pair_request_section`(순서 `seq`) |
| **교차** | 분반 연강을 엇갈려서 (가반 월1·목2 / 나반 월2·목1) | `pair_request.mode` = `CROSS`. 상관없음 = 행 없음 |
| **채플 칸** | 학년별 채플 시간. 그 학년 전공필수는 이 칸에 놓지 않는다 | `chapel_slot` (조교 입력) |
| **실습실** | 1 쓴다(실습실만 배정) / 0 안 쓴다 | 분반 응답 `course_response.lab_requirement` |
| **칠한 칸** | 희망 `PREFER` / 불가 `BLOCK`. 칠하지 않은 칸은 상관없음 | 분반 응답의 `response_slot.kind` |
| **희망 입력(분반 응답)** | 시간(칠한 칸)·주 1회 연강·실습실·인원은 **분반마다** 받는다(11/25). 인원은 `course_section.enrollment`. 분반 연강·교차만 과목 단위로 한 번(`pair_request`) | `course_response` 한 행 = (차수, 과목, **분반**, 교수). 솔버는 그 분반 담당 교수의 응답만 읽는다 |
| **분반** | 오프라인 회의에서 정해진 분반. 분반 하나당 한 행: 번호(1부터 빈틈없이)·담당 교수·수강 인원. 행이 없는 과목은 `course.professor_id`의 1분반 | `course_section` (조교 입력, 인원은 교수가 정함) |
| **분반 수강 인원** | 강의실 정원보다 많으면 그 강의실은 배정 후보에서 제외(하드). NULL = 아직 모름 | `course_section.enrollment` |
| **희망 건물** | 교수당 하나. 그 밖의 건물은 솔버 벌점 | `professor_building_pref` |
| **서버 단계** | `COLLECTING` 희망 수집 → `ROUND1` 1차 조율 → `ROUND2` 2차 조율 → `ROUND3` 3차 조율 → `FINAL` 확정 | `term.phase`, `phase_log` |
| **기타 요청** | 교수가 자연어로 쓴 글. AI 없이 조교가 읽고 "확인함"을 누른다 | `other_request` |
| **조율 안건** | 조율할 분반 하나의 조율. 대안 A·B·C와 메시지·답장이 여기에 붙는다. 조율 대상 종류 `target_kind`: `UNPLACED` 못 놓음 / `MISMATCH` 희망에서 어긋남 / `PARTIAL` 일부 어긋남 | `proposal` (`section_no` = 분반) |
| **안건 상태** | `OPEN` 보내기 전 → `SENT` 답 기다림 → `PROPOSED` 조교 확인 대기 → `RESOLVED` 반영됨 / `KEPT` 현재대로 유지 / `NEXT` 다음 차수로 / `OFFLINE` 따로 연락 중. 보내기 전에 `HOLD` 조교 선택 대기(일부 어긋남) / `NO_OPTION` 대안 없음(조교 확인 → `OFFLINE`). 서버 조율 상태와 같은 이름. **안건 하나는 한 차수의 조율**이다 | `proposal.status` |
| **다음 차수 안건** | `NEXT`가 된 안건을 이어받아 다음 차수에 새로 연 안건. 같은 안건을 되돌리지 않는다 | `proposal.prev_proposal_id` |
| **분반 배정 상태** | `DONE` 끝남 / `COORD` 조율 중 / `MANUAL` 조교가 직접 정함. 서버 `assignment.status`와 같은 이름. **분반이 아직 안 풀렸는지는 이것으로 판단**한다 | `timetable_section.status` |
| **조율 메시지 / 답장** | 조교 쪽이 보낸 글(`REPLY`가 아닌 것) / 교수가 자기 화면에서 쓴 답장(`kind='REPLY'`). 답장은 `reply_to_id`로 답하는 조율 메시지를 가리킨다 | `message` |
| **해석 / 조교 결정** | 답장을 읽은 결과(`ACCEPT/CONDITIONAL/REJECT/UNCLEAR`) / 조교의 `CONFIRM` [확인]·`EDIT` [수정]·`KEEP` [현재대로 유지] | `reply_interpretation.label`, `ta_action` |
| **확인된 조건** | 조교가 [확인]·[수정]한 조건. 다음 차수 안건이 이어받아(`carried_conditions`) 대안에 넘긴다 | `reply_interpretation.extracted_json`의 `"confirmed_conditions"` |

## 단계와 기타 요청 (`db.py`)

```python
db.get_phase(con, term_id)                    # ('ROUND1', '1차 조율')
db.set_phase(con, term_id, 'ROUND3', user_id) # 한 칸씩만. 건너뛰기·되돌리기는 force=True. phase_log에 기록
db.pending_other_requests(con, round_id)      # 조교가 아직 확인 안 한 기타 요청
db.confirm_other_request(con, other_request_id, user_id, memo=None)
```

- 기타 요청 흐름: 교수 원문(`other_request.body`, `PENDING`) → 조교가 읽고 필요하면 `request_item`(`source='TA'`, `other_request_id`)을 직접 입력 → "확인함"(`CONFIRMED`). 응답당 하나.
- `request_item`은 조교가 기타 요청을 보고 남기는 기록이다. 11/24부터 솔버는 읽지 않는다: 분반 수는 `course_section`, 분반 연강·교차는 `pair_request`. `source`는 `FORM`(화면 항목) 또는 `TA`(조교 입력).

## 조율 회신 (`db.py`, 11/24)

교수가 자기 화면에서 답장을 쓰고(A안), 서버가 아래 함수를 불러 DB에 남깁니다. 모든 쓰기 함수는 실패하면 `rollback`, 성공하면 `commit`하고, 잘못된 요청은 한국어 이유를 담은 `ValueError`를 냅니다.

```python
db.professor_owns(con, professor_id, course_id, section_no=None)   # 본인 담당인지. None이면 그 과목의 어느 분반이든
mid = db.add_reply(con, proposal_id, professor_id, body, choices=['A', 'ETC'], reply_to_id=None, channel='APP')   # 하나 이상 필수
db.reply_choices(con, mid)                                          # -> [{'choice': 'A', 'option_id': 1}, ...]
db.save_interpretation(con, mid, 'CONDITIONAL', {...}, model_name=None, chosen_option_id=None)
db.decide_reply(con, mid, ta_user_id, 'CONFIRM' | 'EDIT' | 'KEEP' | 'OFFLINE', reason=None, conditions=None,
                proposal_action='move' | 'next' | 'pair' | None,   # CONFIRM 이면 proposal_action 필수
                option_id=None, pair_mode=None, pair_sections=None)  # 옮긴 대안 / 'pair' 면 NONE·BACK_TO_BACK·CROSS, 붙일 분반 순서
db.add_reply_request(con, mid, '실습 조교 배치')                     # 답장 기타의 시간표 밖 요청 → other_request
tt = db.manual_place(con, proposal_id, ta_user_id, [(분반, 회차, 칸, 강의실), ...], lock=True)   # OFFLINE 안건만
db.set_lock(con, tt, course_id, section_no, False)                   # 고정 풀기
new_tt = db.apply_option(con, proposal_id, ta_user_id, rows, reason=None,   # [확인]·[수정]·도우미 [적용] → 새 시간표 버전
                         course_id=None, base_timetable_id=None, check=None) # 규칙 검사는 엔진 solver_core.apply_option 이 붙여 부름
db.confirmed_conditions(con, proposal_id)                           # -> dict | None
new_id = db.open_next_proposal(con, prev_proposal_id, round_id, timetable_id=None)
db.carried_conditions(con, new_id)                                  # -> dict | None (이전 차수에서 확인한 조건)
db.set_pair_request(con, round_id, course_id, professor_id, 'BACK_TO_BACK', [3, 1])   # 분반 연강·교차 (과목 단위), NONE 이면 지움
db.pair_request(con, round_id, course_id, professor_id)              # -> ('BACK_TO_BACK', [3, 1]) 또는 ('NONE', [])
db.release_hold(con, proposal_id, ta_user_id, send=True)             # 일부 어긋남(HOLD): 보냄 → OPEN / send=False → KEPT
db.ack_no_option(con, proposal_id, ta_user_id)                       # 대안 없음(NO_OPTION) 확인 → OFFLINE
db.coord_board(con, round_id)                                        # 조교 화면: [(안건, 과목, 분반, 종류, 상태, 이유, 대안 수)]
```

| 함수 | 하는 일 | 막는 경우 (`ValueError`) |
|---|---|---|
| `add_reply` | 고른 값 `choices`(A·B·C·기타, 하나 이상, 여러 개 가능)를 `reply_choice`에 남긴다. 기타를 고르면 본문 필수, A·B·C는 그 안건의 대안 1·2·3번이 있어야 함. `message`에 `kind='REPLY'`, 보낸 사람=교수, 받는 사람=답하는 조율 메시지를 보낸 사람(없으면 첫 조교), `sent_at`, `delivery_status='RECEIVED'`. `reply_to_id`가 없으면 이 안건의 가장 최근 조율 메시지로 채움. `round_invite`가 있으면 `status='RESPONDED'`, `responded_at` | 없는 안건, 담당 교수 아님, 안건 상태가 `SENT`·`PROPOSED`가 아님(`OPEN`·`RESOLVED`·`KEPT`), 다른 안건의 메시지·답장(`REPLY`)을 가리킴, 받을 조교 없음 |
| `save_interpretation` | `reply_interpretation`을 만들거나 갱신하고 안건을 `PROPOSED`로 | 답장이 아님, 가장 최근 답장이 아님, 이미 결정한 답장·안건, 잘못된 `label`, 다른 안건의 대안, `extracted_json`이 JSON 객체가 아님 |
| `decide_reply` | `ta_action`·`ta_user_id`·`ta_at`·`ta_reason` 기록. `conditions`가 있으면 `extracted_json["confirmed_conditions"]`에 그대로 저장. 안건 상태는 아래 표 | 조교(`role='TA'`)가 아님, 해석이 없음, 이미 결정함, 안건이 `PROPOSED`가 아님, 가장 최근 답장이 아님, `CONFIRM`에 `proposal_action` 없음·잘못된 값, `'next'`에 조건이 비어 있음, `EDIT`에 사유 없음, `KEEP`에 조건을 넣음 |
| `confirmed_conditions` | 이 안건의 가장 최근 답장 중 `CONFIRM`·`EDIT`된 것의 `"confirmed_conditions"` | — (없으면 `None`) |
| `reply_choices` | 답장에서 고른 값(A·B·C·기타)과 가리키는 대안 | — |
| `add_reply_request` | 답장 기타 중 시간표 밖 요청을 `other_request`(`message_id`, `PENDING`)로. 조교는 `pending_other_requests`·`confirm_other_request`로 희망 입력의 기타 요청과 같이 처리 | 답장이 아님, 기타를 안 고른 답장, 빈 내용, 이미 있음 |
| `manual_place` | [따로 연락]한 안건의 분반을 조교가 정한 칸에 놓는다. 그 학기 최신 시간표를 복사한 `TA_EDIT` 시간표, 대상 분반 `MANUAL`·고정, 안건 `RESOLVED`. 하드 규칙 위반은 막지 않고 엔진 `check_timetable`로 경고 | 조교 아님, 안건이 `OFFLINE`이 아님, 대상 분반이 아님·빠진 분반, 없는 칸·강의실, 같은 칸 같은 강의실(DB가 막음, 되돌림) |
| `set_lock` | 분반 고정 걸기·풀기 | 없는 분반 배정 |
| `apply_option` | 조교 [확인]·[수정]·도우미 [적용]한 안을 **새 시간표 버전**으로 저장: 기준 버전(없으면 그 학기 최신)을 복사해 `TA_EDIT`·`parent_id`=기준 버전, rows에 나온 분반만 바꿈(나머지 그대로), 바꾼 분반 `DONE`, 안건 → `RESOLVED`, 사유 → `timetable.reason`. `check`를 주면 기준 버전에 없던 위반이 새로 생길 때 거부. 한 트랜잭션 | 조교 아님(`user_id`가 있을 때), 안건이 `KEPT`·`NEXT`, 안건 없이 `course_id`·`base_timetable_id` 없음, 안건의 분반이 아님, 빈 rows·없는 칸·강의실, 고정된 분반, 같은 칸 같은 강의실, 새 하드 규칙 위반(되돌림) |
| `open_next_proposal` | 다음 차수에 새 안건: 같은 과목·분반·이유·조율 대상 종류, `status='OPEN'`(대안은 엔진 `fill_options`로 채움, 없으면 `NO_OPTION`), `prev_proposal_id`=이전 안건. `timetable_id`가 없으면 이전 안건의 시간표(`NEXT`는 시간표를 바꾸지 않음). 이전 안건은 `NEXT` 그대로 둔다 | 없는 안건, 이전 안건이 `NEXT`가 아님, 이전 안건이 3차, 같은 학기의 바로 다음 차수가 아님, 다른 학기 시간표, 이미 다음 차수 안건이 있음(DB `UNIQUE`도 막음) |
| `carried_conditions` | `prev_proposal_id`가 가리키는 이전 안건의 `confirmed_conditions`. **한 단계만** (3차 안건은 2차에서 확인한 조건만) | 없는 안건 (이전 안건·조건이 없으면 `None`) |
| `set_pair_request` | 교수 입력의 분반 연강·교차를 과목 단위로 한 번 저장(바꾸면 덮어씀). 붙일 분반은 교수가 적은 순서대로, 없으면 맡은 분반 전부를 번호 순서로. `NONE`이면 지움 | 그 교수가 그 과목 분반을 둘 이상 맡지 않음, 붙일 분반이 둘 미만·중복, 그 교수가 맡지 않은 분반, 잘못된 모드 |
| `release_hold` | 일부 어긋남(`HOLD`) 안건: 조교가 보내기로 하면 `OPEN`(서버가 보냄), 안 보내면 `KEPT` | 조교 아님, `HOLD`가 아님 |
| `ack_no_option` | 대안 없음(`NO_OPTION`) 안건을 조교가 확인 → `OFFLINE`(따로 연락), 이후 `manual_place` | 조교 아님, `NO_OPTION`이 아님 |
| `coord_board` | 그 차수 안건 목록: 조율 대상 종류·상태·이유·대안 수 (조교 화면용) | — |

조교 결정과 안건 상태:

| 조교 결정 | `proposal_action` | 안건 상태 | 조건 |
|---|---|---|---|
| `CONFIRM` [확인] | `'move'` 처리안 "옮김" | `RESOLVED` | 있어도 없어도 됨 |
| `CONFIRM` [확인] | `'next'` 처리안 "다음 차수" | `NEXT` | **필수** (비면 `ValueError`) |
| `CONFIRM` [확인] | 없음 | — `ValueError` | |
| `EDIT` [수정] | 쓰지 않음 | `RESOLVED` | 있어도 없어도 됨, 사유 필수 |
| `CONFIRM` [확인] | `'pair'` 기타의 분반 연강·교차 요청 | `RESOLVED` (그 교수의 `pair_request`를 바꿈, 서버가 그 분반을 다시 풂) | `pair_mode` 필수, `pair_sections` 선택 |
| `KEEP` [현재대로 유지] | 쓰지 않음 | `KEPT` | 넣을 수 없음 |
| `OFFLINE` [따로 연락] | 쓰지 않음 | `OFFLINE` → 수동 배치(`manual_place`) 뒤 `RESOLVED` | 넣을 수 없음 |

다음 차수 흐름 (서버 `post_decide`의 `NEXT`와 같음):

```text
1차 안건 SENT → (답장) → PROPOSED → [확인] next + 조건 → NEXT          시간표는 그대로
   └ open_next_proposal(1차 안건, 2차 round_id) → 2차 안건 OPEN (prev_proposal_id = 1차 안건)
        cond = carried_conditions(2차 안건) → solver_core.alternatives(..., condition=cond)
        2차 안건 SENT → … → RESOLVED / KEPT / NEXT(→ 3차 안건) ; 3차 다음은 없음(조교가 직접 정함)
```

### 교수 답장 선택과 [따로 연락] (11/25)

교수가 "셋 다 어렵습니다"처럼 조건 없이 거절하면 처리안이 '다음 차수'인데 넘길 조건이 없어 [확인] 때 저장 오류가 났습니다. 그래서 답장을 이렇게 받습니다.

- 교수는 **대안 A·B·C와 기타 중 하나 이상을 골라야** 답장을 낼 수 있습니다(여러 개 가능). 화면·서버는 하나도 안 고르면 [보내기]를 막고, DB(`add_reply`)도 거부합니다.
- **기타 글칸은 하나**입니다(`message.body`). 시간 조건과 그 밖의 요청은 회신 해석(조율 NLP)이 나눕니다.

  | 기타에 적힌 것 | 해석 결과 | 가는 곳 |
  |---|---|---|
  | 시간 조건 ("목요일 오후면 됩니다") | `conditions` (`day_slots`·`end_before`) | `pick_best(condition=...)` 로 새 안, 맞는 안이 없으면 다음 차수 |
  | 실습 조교·장비·강의실 요청 | `note` | 서버가 `add_reply_request` → 기타 요청 표(조교 [확인함]) |
  | 두 분반 연강·교차 요청 | `note` | 조교 [확인] `proposal_action='pair'` → 그 교수의 `pair_request` |

- 여러 안을 고르면 [확인] 때 엔진 `pick_best`가 처리안을 고릅니다.
  - **버튼만 누른 경우**: 지금 시간표에 넣었을 때 **점수가 가장 좋은 안**.
  - **교수가 글로 순서를 밝힌 경우**("A가 제일 좋고 안 되면 B"): `respect_order=True`로 그 순서(해석의 `picks` 순서)를 점수보다 먼저 지킵니다. 앞 순서 안을 못 놓으면 다음 순서. 기타 시간 조건으로 만든 새 안은 밝힌 순서 뒤입니다.
  - 기타에 시간 조건이 있으면 그 조건에 맞는 새 안도 같이 비교합니다(그 안을 쓰면 `add_option`으로 4번 대안으로 저장).
- 기타만 고르고 시간 조건이 있으면 조건에 맞는 새 안을 바로 만들고, 없으면 지금처럼 조건을 들고 다음 차수(`NEXT`)로 넘깁니다.
- 고른 안을 지금은 놓을 수 없으면(그사이 다른 수업이 그 칸을 씀) 처리안은 '조교가 정함'입니다: [수정]·[현재대로 유지]·[따로 연락].
- **기타만 고르고 시간 얘기 없이 요청만 쓴 경우**("실습 조교 부탁드려요")는 A·B·C가 다 안 된다는 뜻인지 애매합니다. 그래서 **'조교가 정함'(따로 연락)** 처리안으로 보내고, 요청 메모(`note`)를 같이 보여 줍니다. 요청 자체는 `add_reply_request`로 기타 요청 표에도 남깁니다. 조교가 교수와 확인해 A·B·C 중 하나로 [수정]하거나 [따로 연락]합니다.
- 기타만 고르고 조율할 내용이 없으면("위의 대안에선 어렵다") 조교가 **[따로 연락](`OFFLINE`)**을 고르고 시스템 밖에서 교수와 정합니다. 정한 결과는 `manual_place`로 넣고, 그 분반은 **고정**(`timetable_section.locked=1`)되어 이후 모든 풀이에서 움직이지 않습니다. [따로 연락]은 답장 해석 뒤(`PROPOSED`) 언제든 고를 수 있습니다.

```text
답장(A·B·C·기타 하나 이상) → 해석(save_interpretation) → PROPOSED
  ├ A·B·C(+기타 조건) → pick_best → 놓을 수 있는 안 중 첫째 → [확인] move(option_id) → RESOLVED
  │     버튼만: 점수 순 / 글로 순서를 밝힘: respect_order=True, 밝힌 순서(새 안은 그 뒤)
  │                                  └ 하나도 못 놓음 → 조교가 정함: [수정] / [현재대로 유지] / [따로 연락]
  ├ 기타만, 시간 조건 → pick_best(조건) → 새 안 → [확인] move ; 맞는 안 없음 → [확인] next + 조건 → NEXT
  ├ 기타의 분반 연강·교차(note) → [확인] pair → RESOLVED (서버가 그 교수 분반을 다시 풂)
  ├ 기타의 시간표 밖 요청(note) → add_reply_request → 기타 요청 표 (A·B·C도 골랐으면 위 흐름과 함께)
  ├ 기타만, 요청만(시간 얘기 없음) → 조교가 정함(따로 연락) + 메모 표시 ; 요청은 add_reply_request
  └ 기타만, 내용 없음 → [따로 연락] → OFFLINE → manual_place(고정) → RESOLVED
```

### 처리안 반영을 새 시간표 버전으로 (11/25)

조교가 [확인]·[수정]해도 서버 어댑터의 `reassign()`이 메모리에서만 배정을 바꿔, 다음 차수의 대안·재풀이가 옛 시간표를 기준으로 계산했습니다. 그래서 `apply_option`이 고른 안을 **새 시간표 버전**으로 저장합니다.

```text
버전 7 (DRAFT) ──[확인] B안──▶ 버전 8 (TA_EDIT, parent 7, 사유) ──[수정] 다른 칸──▶ 버전 9 (TA_EDIT, parent 8)
                       옮긴 분반만 바뀌고 나머지는 7과 같음          다음 차수 alternatives·solve 는 최신 버전 기준
```

- 엔진에서 부를 때는 `solver_core.apply_option`(규칙 검사 `check_timetable`이 붙어 있음)을 씁니다. 대안 → rows는 `solver_core.option_rows(con, option_id=...)` 또는 `option_rows(con, option=대안, timetable_id=...)`.
- 허용 안건 상태: `KEPT`(현재대로 유지)·`NEXT`(다음 차수로)만 거부, 나머지(`OPEN`·`SENT`·`PROPOSED`·`OFFLINE`·`RESOLVED`·`HOLD`·`NO_OPTION`)는 허용. `decide_reply`가 먼저 `RESOLVED`로 바꿔도 됩니다.
- 거부 기준: **새로 생긴 위반만**. 이미 있던 위반(예: 경고를 받고 고정된 수동 배치)은 막지 않습니다.
- `manual_place`와의 차이: `manual_place`는 [따로 연락] 뒤 조교가 정한 칸을 위반이 있어도 저장하고 **고정**합니다. `apply_option`은 일반 [확인]·[수정]·도우미 [적용]용이고, 새 위반이 생기면 **거부**하며 고정하지 않습니다.
- **서버(어댑터)가 맞출 것** (`backend/app/solver/adapter.py`, 대원 담당, 이 변경에서는 고치지 않음): `reassign()`의 시그니처는 그대로 두고, 안에서 ① 그 분반의 열린 안건(`RESOLVED`·`KEPT`·`NEXT`가 아닌 가장 최근 것, 없으면 `None` = 도우미 [적용])을 DB에서 찾고 ② `sc.option_rows`로 rows를 만들어 ③ `sc.apply_option(con, 안건 또는 None, 조교 id 또는 None, rows, 사유, course_id=..., base_timetable_id=self.timetable_id)`를 부른 뒤 ④ `self.timetable_id`를 새 id로 바꾸고 `self.last_saved`(새 id·안건 등)에 남깁니다. 반환 `Timetable`은 지금 모양 그대로. 조교 id·사유를 넘기려면 어댑터에 따로 넣는 함수를 둡니다.

### 조율 대상과 1차 안건 (11/25)

못 놓은 분반에만 조율 메시지를 보내면 희망 시간·건물에서 어긋난 분반은 조율할 수 없어서, 조율 대상을 세 가지로 나눕니다. 엔진 `solver_core.coord_targets`가 대상을 찾고 `open_coord_proposals`가 대안을 만들어 안건으로 저장합니다.

| 종류 (`proposal.target_kind`) | 언제 | 안건 상태 | 메시지 |
|---|---|---|---|
| `UNPLACED` 못 놓음 | 회차가 하나라도 시간표에 없음 | `OPEN` | 대안 A·B·C와 함께 **자동으로** 보냄 |
| `MISMATCH` 희망에서 어긋남 | **모든 회차**가 희망 칸 밖, 또는 **모든 회차**가 희망 건물 밖 | `OPEN` | 대안 A·B·C와 함께 **자동으로** 보냄 |
| `PARTIAL` 일부 어긋남 | **일부 회차만** 희망 칸 밖 또는 희망 건물 밖 (한 칸이라도) | `HOLD` 조교 선택 대기 | 보내지 않고 조교 화면에. 조교가 고르면 `release_hold(send=True)` → `OPEN` → 보냄, 안 보내면 `send=False` → `KEPT` |
| (종류 상관없이) 대안이 하나도 없음 | | `NO_OPTION` 대안 없음 | 보내지 않음. 조교가 `ack_no_option`으로 "대안이 없어 보내지 못함"을 확인 → `OFFLINE` → 다른 연락망으로 정한 뒤 `manual_place` |

- 한 회차가 희망 칸에 맞다 = 그 회차가 차지한 칸이 **모두** 그 분반 응답의 희망(`PREFER`) 칸. 희망 칸을 칠하지 않은 분반(미회신 포함)은 시간으로는 대상이 아닙니다.
- 희망 건물에 맞다 = 그 회차 강의실이 담당 교수의 희망 건물. 희망 건물이 없는 교수는 건물로는 대상이 아닙니다. 미회신 교수의 전년도 건물은 희망이 아니므로 보지 않습니다.
- 고정된 분반(`locked`)·조교가 정한 분반(`MANUAL`)은 대상에서 뺍니다. 같은 차수에 그 분반 안건이 이미 있으면 다시 열지 않습니다.
- **같은 대안을 두 번 보내지 않습니다.** 한 안건의 A·B·C끼리, 그리고 같은 분반에 이전 차수까지 보낸 대안(`SENT` 이후 상태 안건의 대안)과 칸 묶음이 같으면 빼고 다음 안을 찾습니다. 요일 순서만 바뀐 안(화·목 ↔ 목·화)과 강의실만 다른 안도 같은 안입니다. 다음 차수 안건은 `open_next_proposal` 뒤 엔진 `fill_options`로 대안을 채우고, 하나도 없으면 `NO_OPTION`이 됩니다.
- 조교 화면 목록은 `db.coord_board(con, round_id)`: 안건마다 종류·상태·이유·대안 수.

- **재제출**: 교수가 조교 결정 전에 다시 쓰면 새 `REPLY` 행이 생기고 이전 답장·해석은 이력으로 남습니다. 해석·결정은 **가장 최근 답장만** 받습니다. 안건 상태는 바꾸지 않으므로(`PROPOSED`면 그대로), 서버가 새 답장을 해석해 `save_interpretation`을 불러야 결정할 수 있습니다. 조교가 결정한 뒤(`RESOLVED`·`KEPT`·`NEXT`)에는 그 안건에 답장을 받지 않습니다. `NEXT`면 다음 차수 안건에 답합니다.
- **조건 모양**: 서버 `conditions_json`(`backend/app/contracts.py`)·어댑터 `solver_condition`과 같은 모양을 **바꾸지 않고** 저장·반환합니다. 요일 키는 문자열입니다. 정수 키처럼 JSON으로 그대로 저장할 수 없는 모양은 거부합니다.

  ```json
  {"day_slots": {"1": ["09:00", "10:30"], "3": []},
   "end_before": [{"day": 2, "time": "17:00"}]}
  ```
  `day_slots`: 요일(0=월…4=금) → 그 요일에 되는 교시 시작 시각, 빈 목록 = 그 요일 아무 교시나. `end_before`: 요일별로 이 시각 전에 끝나야 함. 그대로 `solver_core.alternatives(condition=...)`에 넘길 수 있습니다(`../solver/SOLVER_API.md`).
- **`[확인]`에 조건을 안 넘기면** 확인된 조건은 `None`입니다. 해석한 조건을 다음 차수에 쓰려면 서버가 `[확인]` 때 그 조건을 `conditions`로 넘겨야 합니다.
- **분반이 아직 안 풀렸는지**는 `proposal.status`가 아니라 `timetable_section.status`(`COORD`/`DONE`)로 판단합니다. `NEXT`는 "이번 차수 조율을 처리했다"는 뜻일 뿐, 분반이 풀렸다는 뜻이 아닙니다. 둘이 어긋난 경우(예: `NEXT`인데 그 분반이 그 학기 최신 시간표에서 이미 `DONE`이고, 다음 차수 안건도 열지 않음)를 찾는 점검 쿼리:

  ```sql
  SELECT p.id, p.course_id, p.section_no, ts.status
  FROM proposal p
  JOIN timetable t   ON t.id = p.timetable_id
  JOIN timetable_section ts
       ON ts.timetable_id = (SELECT MAX(id) FROM timetable WHERE term_id = t.term_id)   -- 그 학기 최신 시간표
      AND ts.course_id = p.course_id
      AND (p.section_no IS NULL OR ts.section_no = p.section_no)
  WHERE p.status = 'NEXT' AND ts.status = 'DONE'
    AND NOT EXISTS (SELECT 1 FROM proposal n WHERE n.prev_proposal_id = p.id);
  ```
  나온 행은 다음 차수 안건을 열 필요가 없는지(조교가 따로 풀었는지) 확인합니다. `tests/test_reply.py`가 같은 쿼리를 검사합니다.
- **서버와 아직 연결되지 않았습니다.** 서버(`backend/`)는 조율 상태·답장·조교 결정을 메모리에만 두므로, 서버가 이 함수들을 부르기 전에는 화면에서 쓴 답장이 DB에 남지 않습니다.

## 피드백 반영 현황 (DB 쪽)

솔버 쪽 반영 내용은 `../solver/README.md`에 있습니다.

| 날짜 | 요청 | 상태 | 어디에 |
|---|---|---|---|
| 11/21 | `proposal`에 분반 번호 | 반영 | `proposal.section_no` |
| 11/21 | `reply_interpretation.label` 값 | 반영 | `ACCEPT / CONDITIONAL / REJECT / UNCLEAR` (DB `CHECK`). 한글 값은 거부됨. AI 응답 형식을 이 값에 맞추는 일은 AI 담당 |
| 11/21 | 외래키 검사가 꺼져 있는 문제 | 반영(`db.connect`) | 백엔드 서버가 `db.connect()`를 쓰도록 적용해야 함 (적용 여부 미확인) |
| 11/21 | 담당 교수를 과목마다 → **분반마다** | 반영 | `course_section`, `course_response.professor_id`, 뷰 |
| 11/21 | 주 1회 연강 3단계 | 11/24 두 단계로 | `course_response.single_day_pref` (MUST/NONE). PREFER는 006이 NONE으로 옮김 |
| 11/21 → 11/22 | 실습실 3단계 → **0/1** | 반영 | `course_response.lab_requirement` (INTEGER 0/1). 003이 MUST·PREFER→1, NONE→0으로 옮김 |
| 11/22 | "선호 시간을 제외하면 수업하기 어렵다" 버튼 | 11/24 삭제 | `course_response.prefer_only` (006에서 없앰) |
| 11/22 | 서버 단계 관리 (3차 조율 `ROUND3` 포함) | 반영 | `term.phase`, `phase_log`, `db.get_phase` `db.set_phase`. 004가 `ROUND3`를 추가 |
| 11/22 | 기타 요청은 AI 없이 조교가 확인 | 반영 | `other_request`, `request_item` 재설계. `note`와 `source='NLP'`는 없앰 |
| 11/22 | 시간표 칠하기에서 `AVOID` 제거 | 반영 | `response_slot.kind` = `PREFER`/`BLOCK` |
| 11/22 | 로그인 없이 교수·조교 화면 전환 (시연) | 프런트 일 | DB 변경 없음. 시연 계정은 `user` 행을 만들고 `password_hash`에 아무 값이나 넣는다 |
| 11/24 | 교수가 자기 화면에서 직접 답장 (A안): 답장↔조율 메시지 연결 | 반영 | `message.reply_to_id` (005), `db.add_reply` |
| 11/24 | 조율 안건 상태를 서버 상태 이름으로 고정 | 반영 | `proposal.status` `OPEN/SENT/PROPOSED/RESOLVED/KEPT` (005, `WAITING`→`OPEN`) |
| 11/24 | 조교가 [확인]한 조건을 DB에서 읽기 | 반영 | `db.decide_reply` → `db.confirmed_conditions`. 서버가 부르기 전까지는 미연결 |
| 11/24 | 서버 `NEXT` 상태 (조건을 들고 다음 차수로) | 반영 | `proposal.status` `NEXT`, `db.decide_reply(..., proposal_action='next')` (005) |
| 11/24 | 다음 차수에는 새 안건 (같은 안건을 되돌리지 않음) | 반영 | `proposal.prev_proposal_id` (005), `db.open_next_proposal`, `db.carried_conditions` |
| 11/24 | 분반이 안 풀렸는지는 배정 상태로 판단 | 반영 | `timetable_section.status` `DONE/COORD/MANUAL` (005), README 점검 쿼리. 서버가 쓰기 전까지는 모두 `DONE` |
| 11/24 | 선호 시간 외 불가 삭제 | 반영 | `course_response.prefer_only` 삭제 (006) |
| 11/24 | 분반은 오프라인 회의에서 정해진 상태로 시작 → 분반별로 저장 | 반영 | `course_section` 한 행 = 분반 하나 (006). 솔버는 `SECTION_COUNT`를 읽지 않음 |
| 11/24 | 희망 건물은 순위 없이 하나, 그 밖은 벌점 | 반영 | `professor_building_pref` 교수당 한 행, `rank` 삭제 (006) |
| 11/24 | 분반마다 교수가 수강 인원을 정함, 정원보다 많으면 그 강의실 제외 | 반영 | `course_section.enrollment`, `course.expected_enrollment` 삭제 (006). 솔버 하드 규칙 |
| 11/24 | 강의 언어 삭제 | 반영 | `course_response.language` 삭제 (006) |
| 11/24 | 두 분반 연강·교차를 교수 입력 칸으로 | 반영 | `course_response.section_pair` (006, 기존 `SECTION_PAIR` 요청을 옮김). 11/25에 `pair_request`로 옮김 (009) |
| 11/24 | 전공필수와 채플이 겹치지 않게 | 반영 | `chapel_slot` (006). 솔버 하드 규칙 |
| 11/25 | 못 놓은 분반에만 조율 메시지를 보내 희망 시간·건물에서 어긋난 분반은 조율할 수 없음 | 반영 | 조율 대상 종류 `proposal.target_kind`(못 놓음·어긋남 → 자동 보냄, 일부 어긋남 → `HOLD` 조교 선택), 대안 없음 `NO_OPTION`(조교 확인 → 따로 연락), 같은 대안 두 번 보내지 않기 (009, 엔진 `coord_targets`·`open_coord_proposals`·`fill_options`) |
| 11/25 | 희망 입력이 (과목, 교수) 단위라 분반마다 받을 수 없고, "가반 바로 뒤 나반"처럼 두 분반 사이의 관계를 분반 한 칸에 넣을 수 없음 | 반영 | `course_response.section_no`(시간·주 1회 연강·실습실은 분반마다, 인원은 `course_section`), 분반 연강·교차는 과목 단위 `pair_request`·`pair_request_section`(교수가 붙일 분반을 순서대로). 솔버는 앞 두 분반만, 셋째부터는 조교가 수동 배치·고정 (009) |
| 11/25 | 조교 [확인]·[수정]이 시간표 새 버전으로 저장되지 않아 다음 차수가 옛 시간표 기준 | 반영 | `apply_option`(TA_EDIT 새 버전, 새 위반 거부), 시간표 버전 사유 `timetable.reason` (008). 어댑터 연결은 서버 몫 |
| 11/25 | 조건 없는 거절("셋 다 어렵습니다") 뒤 [확인] 저장 오류 | 반영 | 답장 선택 `reply_choice`(하나 이상 필수), [따로 연락] `OFFLINE`, 수동 배치 `manual_place`·고정 `locked`, 분반 연강·교차 반영 `pair`, 답장 기타 요청 (007) |
| 11/24 | `message.kind`·`channel` 값 CHECK | 하지 않음 | ER 그림에 적힌 값(`NOTICE/REMINDER/ALTERNATIVE/REPLY`, `APP/EMAIL/SMS`)만 문서로 둠. 이번에는 건너뛰기로 결정 |

### 반영하지 않은 피드백 (결정 필요)

화면에서 받는 항목과 DB가 맞지 않는다는 지적 중 아직 정하지 않은 것입니다.

| 지적 | 현재 DB | 필요한 결정 |
|---|---|---|
| 강의실 (선택) | 칸 없음 | 특정 강의실 희망을 받을지 |

## 기존 DB 바꾸기

**파일을 복사해 두고**, 가진 DB의 버전에 맞게 차례로 한 번씩만 실행합니다.

```bash
cp ssuroom.db ssuroom.db.bak
sqlite3 ssuroom.db < db/migrations/001_20261121_feedback.sql            # archive/schema_v3로 만든 DB만
sqlite3 ssuroom.db < db/migrations/002_20261122_phase_other_request.sql # 001까지 된 DB
sqlite3 ssuroom.db < db/migrations/003_20261122_lab_binary_no_avoid.sql # 002까지 된 DB
sqlite3 ssuroom.db < db/migrations/004_20261122_phase_round3.sql        # 003까지 된 DB
sqlite3 -bail ssuroom.db < db/migrations/005_20261124_reply.sql        # 004까지 된 DB (-bail 필수)
sqlite3 -bail ssuroom.db < db/migrations/006_20261124_section.sql      # 005까지 된 DB (SQLite 3.35 이상)
sqlite3 -bail ssuroom.db < db/migrations/007_20261125_reply_choice.sql # 006까지 된 DB
sqlite3 -bail ssuroom.db < db/migrations/008_20261125_timetable_reason.sql # 007까지 된 DB
sqlite3 -bail ssuroom.db < db/migrations/009_20261125_section_response.sql # 008까지 된 DB
```

- **001**: 기존 응답의 `professor_id`는 그 과목의 담당 교수로, `single_day_pref`는 `NONE`으로 채웁니다(그때는 묻지 않았던 질문). `REQUIRE`는 `MUST`로, 한글 label은 영어 코드로 바꿉니다.
- **002**: `term`에 `phase`(기존 학기는 `COLLECTING`으로 시작. 이미 진행 중이면 직접 바꿀 것), `phase_log`, `other_request` 생성. 기존 `course_response.note`는 `other_request`에 `PENDING`으로 옮기고 칸은 없앱니다. `prefer_only`는 모두 0. `request_item`은 `source`가 `FORM`이 아니면 `TA`로.
- **003**: `AVOID` 칸은 지워집니다(= 상관없음). 실습실은 MUST·PREFER → 1, NONE → 0.
- **004**: `term` 테이블을 다시 만들어 `phase`에 `ROUND3`를 추가합니다. 학기 행과 지금 단계는 그대로 옮깁니다.
- **005**: `message`에 `reply_to_id`(기존 행은 NULL), `timetable_section`에 `status`(기존 행은 `DONE`)를 더하고, `proposal`을 다시 만들어 `status`를 6개 값으로 고정하고 `prev_proposal_id`(기존 행은 NULL, `UNIQUE`)를 더합니다. `WAITING`(옛 기본값)과 NULL은 `OPEN`으로 옮기고, 그 밖의 값이 있으면 **멈춥니다**(조용히 바꾸지 않음). 실행 전에 확인하는 SELECT가 파일 위 주석에 있습니다. `-bail` 없이 실행하면 sqlite3가 오류 뒤에도 다음 줄을 실행해 옛 `proposal`을 지울 수 있으니 꼭 붙입니다.
- **006**: `course_section`에 `enrollment`를 더하고 `course.expected_enrollment`의 값을 옮깁니다(분반 행이 있으면 인원 ÷ 분반 수 올림, 없으면 1분반 행을 만들어 그대로. 인원이 없으면 행을 만들지 않음). `course.expected_enrollment`, `course_response.prefer_only`·`language`는 지웁니다(`DROP COLUMN`이라 SQLite 3.35 이상). `professor_building_pref`는 교수당 한 행으로 다시 만들고 가장 높은 순위 건물 하나만 남깁니다. `course_response`는 다시 만들어 `section_pair`를 더하고(기존 `SECTION_PAIR` 요청의 가장 최근 값), 주 1회 연강 `PREFER`를 `NONE`으로 옮기며, 빈 `chapel_slot`을 만듭니다. **예전에 교수 요청(`SECTION_COUNT`)으로 분반이 여러 개였던 과목은 실행 뒤 조교가 `course_section`에 분반을 직접 넣어야 합니다** (확인 SELECT는 파일 주석).
- **009**: `course_response`를 분반 단위로 다시 만듭니다. 응답 하나 → 그 교수가 그 과목에서 맡은 분반마다 한 행(첫 분반은 id 그대로, 나머지는 새 id로 칠한 칸을 복사). 분반 행이 없는 과목이나 맡은 분반이 없으면 1분반. 기타 요청·`request_item`은 첫 분반 응답에 남습니다. `section_pair`가 `NONE`이 아닌 응답은 `pair_request`(붙일 분반 = 그 교수의 분반 번호 순서)로 옮기고 칸은 없앱니다. `proposal`을 다시 만들어 상태에 `HOLD`·`NO_OPTION`을, `target_kind`(기존 안건은 NULL)를 더합니다.
- **008**: `timetable`에 `reason`(이 버전을 만든 이유)을 더합니다. 기존 버전은 NULL.
- **007**: `reply_choice` 테이블을 만들고(기존 답장은 기록 없음), `proposal`을 다시 만들어 상태에 `OFFLINE`을 더하고, `timetable_section`에 `locked`(기존 행은 0)를 더하고, `other_request`를 다시 만들어 `message_id`를 더합니다(`response_id`·`message_id` 중 정확히 하나).
- 마지막 `PRAGMA foreign_key_check`가 아무것도 출력하지 않아야 정상입니다. 두 번 실행하면 오류가 납니다.
- **주의**: `term` 칸이 늘어서 `INSERT INTO term VALUES (...)`처럼 칸 이름 없이 넣던 코드는 칸 이름을 적어야 합니다. `message`·`timetable_section`도 005로 칸이 하나씩 늘었습니다(`solver_core.py`, `solver/tests/run_n3.py`의 `timetable_section` INSERT는 칸 이름을 적도록 고쳤습니다). 006으로 `course_section`은 칸이 늘고 `course`·`course_response`·`professor_building_pref`는 칸이 줄었습니다. 009로 `course_response`는 `section_no`가 늘고 `section_pair`가 없어졌습니다(칸 이름을 적어 넣으면 `section_no`는 기본 1).
- `tests/test_migration.py`가 v3→001→…→009, v4→002→…→009, v7→005→009, v8→006, v9→007, v10→008, v11→009 경로가 (005 뒤에는 `archive/schema_v8.sql`, 006 뒤에는 `schema_v9.sql`, 007 뒤에는) 최종 `schema.sql`과 같은 모양을 만들고, 데이터를 보존하며, 새 규칙(잘못된 단계·`NLP`·`AVOID`·`WAITING`·없는 `reply_to_id`·중복·없는 `prev_proposal_id`·잘못된 분반 `status` 거부, `NEXT` 허용)이 작동하는지, 목록 밖 `status`가 있으면 005가 멈추고 되돌릴 수 있는지 검사합니다.

## 알려진 한계

- "확인됨"은 가상 데이터로 검사한 것입니다. 실제 교수 응답이나 강의실 목록으로 해 본 것이 아닙니다.
- 외래키 검사는 `db.connect()`를 쓸 때만 켜집니다.
- 조교가 확인한 조건은 이제 `confirmed_conditions`로 남지만(11/24), **대안을 만들 때만** 쓰입니다. 이후 전체 재풀이(`solve`)에서도 지키려면 `response_slot`(`BLOCK`)으로 옮기는 방법이 있으나 정하지 않았습니다.
- 조율 회신 함수는 서버가 아직 부르지 않습니다(서버 상태는 메모리). 서버가 부르기 전까지 DB의 조율 기록은 비어 있습니다.
- `NEXT`와 다음 차수 안건은 DB 함수로만 있습니다. 서버가 [확인] 때 `proposal_action`·`conditions`를, 다음 차수를 열 때(`/rounds/next`) `open_next_proposal`을 불러야 기록됩니다. 안건을 차수마다 자동으로 여는 일은 DB가 하지 않습니다.
- `timetable_section.status`는 서버가 쓰기 전까지 모든 행이 `DONE`입니다(005가 기존 행을 `DONE`으로 채움). 그동안은 점검 쿼리가 `NEXT` 안건을 모두 어긋남으로 보여 줄 수 있습니다.
- `carried_conditions`는 한 단계만 봅니다. 1차 조건을 3차까지 들고 가려면 2차 [확인] 때 서버가 조건을 다시 넘겨야 합니다.
- `professor_owns(..., section_no=None)`은 `course.professor_id`가 그 교수면, `course_section`이 모든 분반을 다른 교수로 지정했어도 `True`입니다(`course_section`이 모든 분반을 담지 않을 수 있어서).
- `message.kind`·`channel`에는 CHECK가 없습니다. 답장은 `REPLY`, 그 밖의 것은 모두 조율 메시지로 봅니다.
- 답장 선택·[따로 연락]·수동 배치는 DB·엔진 함수로만 있습니다. 서버가 답장 화면(선택 없이 보내기 막기), [확인] 때 `pick_best`, [따로 연락] 버튼, 수동 배치 화면을 붙여야 합니다.
- 기존 답장(007 전)에는 고른 값 기록이 없습니다.
