# SSU:room

AI소프트웨어학부 시간표 자동 배정 시스템.
조교가 과목을 입력하면 교수님이 희망 시간을 내고, CP-SAT 솔버가 초안을 만든 뒤 조율(2차)을 거쳐 확정합니다.

## DB

SQLite 기준 스키마입니다. 테이블 24개, 조회용 뷰 2개로 구성됩니다.

### 만드는 법

```bash
cd db
python -c "import sqlite3; c=sqlite3.connect('ssuroom.db'); c.executescript(open('schema.sql', encoding='utf-8').read())"
python seed_time_slot.py ssuroom.db   # 75분 시간 칸 채우기
```

> Windows에서는 한글 주석 때문에 `encoding='utf-8'`을 꼭 지정해야 합니다.
> `ssuroom.db`는 `.gitignore`에 들어 있으니 각자 만들어 쓰세요.

### 파일

| 파일 | 내용 |
|---|---|
| `db/schema.sql` | 전체 테이블·인덱스·뷰 정의 |
| `db/seed_time_slot.py` | `time_grid`, `time_slot`에 75분 칸을 넣는 스크립트 (처음 세팅할 때 한 번 실행) |
| `db/docs/c1.*` | ER 그림: 기초 정보 (학과, 사용자, 시간 칸, 학기, 건물·강의실, 과목, 규칙) |
| `db/docs/c2.*` | ER 그림: 1차 희망 수집 (차수, 응답, 고른 칸, 요청 해석, 희망 건물) |
| `db/docs/c3.*` | ER 그림: 배정·조율 (솔버 실행, 시간표 버전, 배정, 대안, 메시지, 회신 해석) |

`.mmd`는 Mermaid 원본입니다. 테이블을 고치면 `.mmd`를 수정하고 다시 렌더링하세요.

```bash
npx -p @mermaid-js/mermaid-cli mmdc -i db/docs/c1.mmd -o db/docs/c1.png -s 2 -b white
```

### 설계 요점

- **시간은 `time_slot` 번호로 통일.** 교수 응답(`response_slot`), 배정(`assignment`), 대안(`proposal_option_slot`) 모두 칸 번호를 가리킵니다.
- **시간표는 버전으로 저장.** 초안(DRAFT), 조교 수정본(TA_EDIT), 확정본(FINAL)이 각각 `timetable` 한 줄이고, `parent_id`로 원본을 추적합니다.
- **같은 시간·같은 강의실은 DB가 막습니다.** `ux_assign_room` 유니크 인덱스 (시간표 버전별).
  강의실을 맞바꿀 때는 한쪽을 지우고 다시 넣는 순서로 처리해야 합니다.
- **교수 시간 겹침은 뷰로 감지합니다.** `v_professor_conflict`
- **강의실별·건물별·교수별 조회**는 `v_schedule`에서 `WHERE`로 거릅니다.

### 현재 가정 (확정되면 수정)

- 1교시 09:00 시작, 하루 8교시, 월~금 (`seed_time_slot.py`의 `first_start`, `periods`, `days`로 변경)
- 예비교수 기능은 보류. 다시 넣을 때 필요한 작업:
  예비교수 후보 테이블 추가 / `timetable_section`에 교수 열 추가(겹침 뷰도 분반 기준으로 변경) / `course_response`에 응답한 교수 열 추가
