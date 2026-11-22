# db — 데이터베이스

SSU:room의 SQLite 스키마, 변경 SQL, 연결·단계 관리 함수입니다. 배정 엔진은 `../solver/`에 있습니다.
교수 응답·시간표 버전·조율 기록이 모두 이 DB에 저장됩니다.

## 파일

| 파일 | 내용 |
|---|---|
| `schema.sql` | **최종 DB 스키마** (테이블 27개, 뷰 2개). 새 DB는 이 파일로 만든다 |
| `db.py` | DB 연결(`connect`, **항상 이걸로** 외래키 검사를 켠다), 서버 단계(`get_phase` `set_phase`), 기타 요청 확인(`pending_other_requests` `confirm_other_request`) |
| `seed_time_slot.py` | 시간 칸(75분 교시) 기본 데이터 |
| `migrations/001_20261121_feedback.sql` | `archive/schema_v3.sql`로 만든 DB → 11/21 피드백 반영 모양 |
| `migrations/002_20261122_phase_other_request.sql` | 001까지 적용한 DB → 단계 관리, 선호 시간 외 불가, 기타 요청 재설계 |
| `migrations/003_20261122_lab_binary_no_avoid.sql` | 002까지 적용한 DB → `AVOID` 제거, 실습실 0/1 |
| `docs/c1.png` `c2.png` `c3.png` | ER 다이어그램 (원본 `c1.mmd` `c2.mmd` `c3.mmd`) |
| `tests/test_migration.py` | 변경 SQL 검사 |
| `archive/schema_v1~v5.sql` | 지난 버전 (참고용). v4 = 001까지, v5 = 002까지 적용한 모양 |

ER 다이어그램: `c1.png` 기초 정보(학과·교수·강의실·과목·분반 교수·시간 칸·학기 단계), `c2.png` 1차 응답 수집·기타 요청, `c3.png` 시간표·대안·메시지.

## 빠른 시작

```bash
# 저장소 맨 위에서
python -c "
import sys; sys.path.insert(0, 'db')
import db
con = db.connect('ssuroom.db')
con.executescript(open('db/schema.sql').read())
"
python db/tests/test_migration.py    # 변경 SQL 검사 (오류 없이 '모든 통과')
```

**연결은 항상 `db.connect()`로 합니다.** SQLite는 연결마다 외래키 검사가 꺼진 채로 시작해서, `sqlite3.connect`를 직접 쓰면 잘못된 번호가 에러 없이 저장됩니다.

## 용어 (섞어 쓰지 말 것)

| 용어 | 뜻 | DB에서 어디 |
|---|---|---|
| **주 1회 연강** | 한 분반이 **하루에 2칸을 이어서** 수업 (예: 화 3·4교시). MUST 하루에 이어서 / PREFER 가능하면 / NONE 이틀 나눠도 됨 | 교수 응답 `course_response.single_day_pref` |
| **분반 연강** | 두 분반을 맡을 때 **가반이 끝나자마자 나반** | `request_item` `SECTION_PAIR` = `BACK_TO_BACK` |
| **교차** | 분반 연강을 엇갈려서 (가반 월1·목2 / 나반 월2·목1) | `SECTION_PAIR` = `CROSS` |
| **실습실** | 1 쓴다(실습실만 배정) / 0 안 쓴다 | `course_response.lab_requirement` |
| **선호 시간 외 불가** | 희망으로 칠한 칸 밖에서는 수업하기 어려움 | `course_response.prefer_only` (0/1) |
| **칠한 칸** | 희망 `PREFER` / 불가 `BLOCK`. 칠하지 않은 칸은 상관없음 | `response_slot.kind` |
| **분반 담당 교수** | 분반마다 교수가 다를 수 있음. `course_section`에 행이 있으면 그 교수, 없으면 `course.professor_id` | `course_section` (조교 입력) |
| **서버 단계** | `COLLECTING` 희망 수집 → `ROUND1` 1차 조율 → `ROUND2` 2차 조율 → `FINAL` 확정 | `term.phase`, `phase_log` |
| **기타 요청** | 교수가 자연어로 쓴 글. AI 없이 조교가 읽고 "확인함"을 누른다 | `other_request` |

## 단계와 기타 요청 (`db.py`)

```python
db.get_phase(con, term_id)                    # ('ROUND1', '1차 조율')
db.set_phase(con, term_id, 'ROUND2', user_id) # 한 칸씩만. 건너뛰기·되돌리기는 force=True. phase_log에 기록
db.pending_other_requests(con, round_id)      # 조교가 아직 확인 안 한 기타 요청
db.confirm_other_request(con, other_request_id, user_id, memo=None)
```

- 기타 요청 흐름: 교수 원문(`other_request.body`, `PENDING`) → 조교가 읽고 필요하면 `request_item`(`source='TA'`, `other_request_id`)을 직접 입력 → "확인함"(`CONFIRMED`). 응답당 하나.
- `request_item`은 솔버가 쓰는 구조화 요청(분반 수 `SECTION_COUNT`, 분반 연강·교차 `SECTION_PAIR`)만 담는다. `source`는 `FORM`(화면 항목) 또는 `TA`(조교 입력).

## 피드백 반영 현황 (DB 쪽)

솔버 쪽 반영 내용은 `../solver/README.md`에 있습니다.

| 날짜 | 요청 | 상태 | 어디에 |
|---|---|---|---|
| 11/21 | `proposal`에 분반 번호 | 반영 | `proposal.section_no` |
| 11/21 | `reply_interpretation.label` 값 | 반영 | `ACCEPT / CONDITIONAL / REJECT / UNCLEAR` (DB `CHECK`). 한글 값은 거부됨. AI 응답 형식을 이 값에 맞추는 일은 AI 담당 |
| 11/21 | 외래키 검사가 꺼져 있는 문제 | 반영(`db.connect`) | 백엔드 서버가 `db.connect()`를 쓰도록 적용해야 함 (적용 여부 미확인) |
| 11/21 | 담당 교수를 과목마다 → **분반마다** | 반영 | `course_section`, `course_response.professor_id`, 뷰 |
| 11/21 | 주 1회 연강 3단계 | 반영 | `course_response.single_day_pref` (MUST/PREFER/NONE) |
| 11/21 → 11/22 | 실습실 3단계 → **0/1** | 반영 | `course_response.lab_requirement` (INTEGER 0/1). 003이 MUST·PREFER→1, NONE→0으로 옮김 |
| 11/22 | "선호 시간을 제외하면 수업하기 어렵다" 버튼 | 반영 | `course_response.prefer_only` |
| 11/22 | 서버 단계 관리 | 반영 | `term.phase`, `phase_log`, `db.get_phase` `db.set_phase` |
| 11/22 | 기타 요청은 AI 없이 조교가 확인 | 반영 | `other_request`, `request_item` 재설계. `note`와 `source='NLP'`는 없앰 |
| 11/22 | 시간표 칠하기에서 `AVOID` 제거 | 반영 | `response_slot.kind` = `PREFER`/`BLOCK` |
| 11/22 | 로그인 없이 교수·조교 화면 전환 (시연) | 프런트 일 | DB 변경 없음. 시연 계정은 `user` 행을 만들고 `password_hash`에 아무 값이나 넣는다 |

### 반영하지 않은 피드백 (결정 필요)

화면에서 받는 항목과 DB가 맞지 않는다는 지적 중 아직 정하지 않은 것입니다.

| 지적 | 현재 DB | 필요한 결정 |
|---|---|---|
| 분반별 인원 | 과목 전체 예상 인원만 있음 | 분반 인원을 입력으로 받을지 |
| 강의실 (선택) | 칸 없음 | 특정 강의실 희망을 받을지 |
| 건물 선호 | 교수 단위로 저장, 화면은 분반마다 받음 | 어느 단위로 통일할지 |
| 칸 단위 "꼭" | `prefer_only`는 분반 단위 한 번 | 분반 단위로 충분한지 |

## 기존 DB 바꾸기

**파일을 복사해 두고**, 가진 DB의 버전에 맞게 차례로 한 번씩만 실행합니다.

```bash
cp ssuroom.db ssuroom.db.bak
sqlite3 ssuroom.db < db/migrations/001_20261121_feedback.sql            # archive/schema_v3로 만든 DB만
sqlite3 ssuroom.db < db/migrations/002_20261122_phase_other_request.sql # 001까지 된 DB
sqlite3 ssuroom.db < db/migrations/003_20261122_lab_binary_no_avoid.sql # 002까지 된 DB
```

- **001**: 기존 응답의 `professor_id`는 그 과목의 담당 교수로, `single_day_pref`는 `NONE`으로 채웁니다(그때는 묻지 않았던 질문). `REQUIRE`는 `MUST`로, 한글 label은 영어 코드로 바꿉니다.
- **002**: `term`에 `phase`(기존 학기는 `COLLECTING`으로 시작. 이미 진행 중이면 직접 바꿀 것), `phase_log`, `other_request` 생성. 기존 `course_response.note`는 `other_request`에 `PENDING`으로 옮기고 칸은 없앱니다. `prefer_only`는 모두 0. `request_item`은 `source`가 `FORM`이 아니면 `TA`로.
- **003**: `AVOID` 칸은 지워집니다(= 상관없음). 실습실은 MUST·PREFER → 1, NONE → 0.
- 마지막 `PRAGMA foreign_key_check`가 아무것도 출력하지 않아야 정상입니다. 두 번 실행하면 오류가 납니다.
- **주의**: `term` 칸이 늘어서 `INSERT INTO term VALUES (...)`처럼 칸 이름 없이 넣던 코드는 칸 이름을 적어야 합니다.
- `tests/test_migration.py`가 v3→001→002→003, v4→002→003 두 경로가 최종 `schema.sql`과 같은 모양을 만들고, 데이터를 보존하며, 새 규칙(잘못된 단계·`NLP`·`AVOID` 거부)이 작동하는지 검사합니다.

## 알려진 한계

- "확인됨"은 가상 데이터로 검사한 것입니다. 실제 교수 응답이나 강의실 목록으로 해 본 것이 아닙니다.
- 외래키 검사는 `db.connect()`를 쓸 때만 켜집니다.
- 조율에서 받은 조건은 DB에 남지 않습니다. 이후 전체 재풀이에서 유지하려면 `response_slot`(`BLOCK`)으로 저장하는 방법이 있으나 정하지 않았습니다.
