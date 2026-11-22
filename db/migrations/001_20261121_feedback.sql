-- 변경 SQL 001 (2026-11-21 피드백 반영)
-- 대상: schema_v3.sql 로 만든 기존 DB  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. course_section 새 테이블: 분반별 담당 교수
--   2. course_response: professor_id 추가(교수별 응답), lab_requirement 값 REQUIRE→MUST,
--                       single_day_pref(주 1회 연강 MUST/PREFER/NONE) 추가, UNIQUE (round_id, course_id, professor_id)
--   3. proposal: section_no 추가
--   4. reply_interpretation.label: ACCEPT/CONDITIONAL/REJECT/UNCLEAR 만 허용 (기존 한글 값은 변환)
--   5. 뷰 v_schedule, v_professor_conflict: 분반 담당 교수 기준으로 다시 만듦
--
-- 기존 데이터 처리
--   - 기존 응답의 professor_id 는 그 과목의 담당 교수(course.professor_id)로 채운다.
--   - 기존 응답의 single_day_pref 는 'NONE'(그때는 이 질문을 받지 않았으므로 기존 동작 유지).
--
-- 실행 방법 (SQLite): 반드시 이 파일 전체를 한 번에, 외래키를 끈 채로 실행한다.
--   sqlite3 ssuroom.db < migrations/001_20261121_feedback.sql
-- 실행 전에 DB 파일을 복사해 두는 것을 권장한다. 두 번 실행하면 오류가 난다(이미 적용된 DB에는 쓰지 말 것).

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 분반별 담당 교수
CREATE TABLE course_section (                -- 분반별 담당 교수 (조교가 입력). 행이 없는 분반은 course.professor_id가 담당
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER NOT NULL,
  professor_id INTEGER NOT NULL REFERENCES user(id),
  PRIMARY KEY (course_id, section_no)
);

-- 2. course_response 다시 만들기 (CHECK/NOT NULL 변경은 ALTER 로 안 되므로 새로 만들어 옮긴다)
CREATE TABLE course_response_new (                -- 교수가 과목별로 낸 응답
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 응답한 교수 (분반마다 교수가 다를 수 있어 교수별로 받음)
  lab_requirement TEXT NOT NULL CHECK (lab_requirement IN ('MUST','PREFER','NONE')),      -- 실습실: 무조건/선호/필요 없음 (사이트에서 필수 입력)
  single_day_pref TEXT NOT NULL CHECK (single_day_pref IN ('MUST','PREFER','NONE')),    -- 주 1회 연강(한 분반이 하루에 2칸 이어서): 무조건/선호/필요 없음
  language TEXT,
  note TEXT, submitted_at TEXT,
  UNIQUE (round_id, course_id, professor_id)
);

INSERT INTO course_response_new(id, round_id, course_id, professor_id, lab_requirement, single_day_pref, language, note, submitted_at)
SELECT r.id, r.round_id, r.course_id, c.professor_id,
       CASE r.lab_requirement WHEN 'REQUIRE' THEN 'MUST' ELSE r.lab_requirement END,
       'NONE', r.language, r.note, r.submitted_at
FROM course_response r JOIN course c ON c.id = r.course_id;
DROP TABLE course_response;
ALTER TABLE course_response_new RENAME TO course_response;

-- 3. proposal 에 분반 번호
ALTER TABLE proposal ADD COLUMN section_no INTEGER;

-- 4. reply_interpretation.label 영어 코드
CREATE TABLE reply_interpretation_new (
  message_id INTEGER PRIMARY KEY REFERENCES message(id),
  label TEXT CHECK (label IN ('ACCEPT','CONDITIONAL','REJECT','UNCLEAR')),  -- 수용/조건부/거절/확인 필요
  chosen_option_id INTEGER REFERENCES proposal_option(id),
  extracted_json TEXT, model_name TEXT,
  ta_action TEXT, ta_reason TEXT,
  ta_user_id INTEGER REFERENCES user(id), ta_at TEXT
);

INSERT INTO reply_interpretation_new(message_id, label, chosen_option_id, extracted_json, model_name, ta_action, ta_reason, ta_user_id, ta_at)
SELECT message_id,
       CASE WHEN label IS NULL THEN NULL
            WHEN label IN ('수용', 'ACCEPT') THEN 'ACCEPT'
            WHEN label IN ('조건부', 'CONDITIONAL') THEN 'CONDITIONAL'
            WHEN label IN ('거절', 'REJECT') THEN 'REJECT'
            ELSE 'UNCLEAR' END,
       chosen_option_id, extracted_json, model_name, ta_action, ta_reason, ta_user_id, ta_at
FROM reply_interpretation;
DROP TABLE reply_interpretation;
ALTER TABLE reply_interpretation_new RENAME TO reply_interpretation;

-- 5. 뷰 다시 만들기
DROP VIEW IF EXISTS v_schedule;
DROP VIEW IF EXISTS v_professor_conflict;
CREATE VIEW v_schedule AS                     -- 강의실별·건물별·교수별 조회의 기반
SELECT a.timetable_id, a.course_id, c.name AS course_name, a.section_no,
       COALESCE(cs.professor_id, c.professor_id) AS professor_id, u.name AS professor_name, a.session_no,
       MIN(ts.day) AS day, MIN(ts.start_time) AS start_time, MAX(ts.end_time) AS end_time,
       b.id AS building_id, b.name AS building, r.id AS room_id, r.room_no
FROM assignment a
JOIN timetable_section s ON s.timetable_id=a.timetable_id AND s.course_id=a.course_id AND s.section_no=a.section_no
JOIN course c ON c.id=a.course_id
LEFT JOIN course_section cs ON cs.course_id=a.course_id AND cs.section_no=a.section_no
JOIN user u ON u.id=COALESCE(cs.professor_id, c.professor_id)
JOIN time_slot ts ON ts.id=a.slot_id
JOIN room r ON r.id=a.room_id
JOIN building b ON b.id=r.building_id
GROUP BY a.timetable_id, a.course_id, a.section_no, a.session_no;
CREATE VIEW v_professor_conflict AS           -- 같은 칸에 한 교수가 두 분반을 맡은 경우 (규칙 위반 표시용)
SELECT a.timetable_id, COALESCE(cs.professor_id, c.professor_id) AS professor_id, a.slot_id,
       COUNT(DISTINCT a.course_id || '-' || a.section_no) AS n
FROM assignment a JOIN course c ON c.id=a.course_id
LEFT JOIN course_section cs ON cs.course_id=a.course_id AND cs.section_no=a.section_no
GROUP BY a.timetable_id, COALESCE(cs.professor_id, c.professor_id), a.slot_id HAVING n > 1;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
