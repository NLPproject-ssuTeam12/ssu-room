-- 변경 SQL 010 (2026-11-25, 실습실 값 이름 MUST/NONE, 답장 선택 '지금 자리 그대로')
-- 대상: 009까지 적용한 DB (archive/schema_v12.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. course_response.lab_requirement: 정수 1/0 → 글자 'MUST'(필요, 실습실만 배정) / 'NONE'(필요 없음).
--      주 1회 연강(single_day_pref)과 같은 이름으로 맞춘다. (CHECK·형을 바꾸려고 course_response 를 다시 만든다)
--   2. reply_choice.choice 에 'KEEP'(지금 자리 그대로) 추가. 이미 자리가 있는 분반(희망에서 어긋남·일부 어긋남)의
--      조율 답장에서만 고를 수 있고, 혼자 또는 기타와만 같이 고른다. 처리안은 [현재대로 유지].
--
-- 기존 데이터 처리
--   - lab_requirement 1 → 'MUST', 0 → 'NONE'. 응답 id·칠한 칸·기타 요청 연결은 그대로.
--   - reply_choice 는 그대로 옮긴다.
--
-- 실행 방법: 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 -bail ssuroom.db < db/migrations/010_20261125_lab_must_keep.sql

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 실습실 값 이름
CREATE TABLE course_response_new (            -- 교수가 분반마다 낸 희망 입력 (칠한 칸·실습실·주 1회 연강). 인원은 course_section.enrollment
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER NOT NULL DEFAULT 1,               -- 어느 분반의 응답인지
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 응답한 교수 (솔버는 그 분반 담당 교수의 응답만 읽는다)
  lab_requirement TEXT NOT NULL CHECK (lab_requirement IN ('MUST','NONE')),   -- 실습실: 필요(실습실만 배정) / 필요 없음 (사이트에서 필수 입력)
  single_day_pref TEXT NOT NULL CHECK (single_day_pref IN ('MUST','NONE')),    -- 주 1회 연강(한 분반이 하루에 2칸 이어서): 무조건 / 필요 없음(주 2회)
  submitted_at TEXT,
  UNIQUE (round_id, course_id, section_no, professor_id)
);
INSERT INTO course_response_new(id, round_id, course_id, section_no, professor_id, lab_requirement, single_day_pref, submitted_at)
SELECT id, round_id, course_id, section_no, professor_id,
       CASE lab_requirement WHEN 1 THEN 'MUST' WHEN 0 THEN 'NONE' END, single_day_pref, submitted_at
FROM course_response;
DROP TABLE course_response;
ALTER TABLE course_response_new RENAME TO course_response;

-- 2. 답장 선택에 '지금 자리 그대로'
CREATE TABLE reply_choice_new (              -- 교수 답장에서 고른 값 (하나 이상, 여러 개 가능)
  message_id INTEGER NOT NULL REFERENCES message(id),
  choice TEXT NOT NULL CHECK (choice IN ('A','B','C','ETC','KEEP')),   -- 대안 A / B / C / 기타(답장 본문) / 지금 자리 그대로
  option_id INTEGER REFERENCES proposal_option(id),    -- A·B·C 가 가리키는 대안 (기타·지금 자리 그대로는 NULL)
  PRIMARY KEY (message_id, choice)
);
INSERT INTO reply_choice_new(message_id, choice, option_id) SELECT message_id, choice, option_id FROM reply_choice;
DROP TABLE reply_choice;
ALTER TABLE reply_choice_new RENAME TO reply_choice;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
