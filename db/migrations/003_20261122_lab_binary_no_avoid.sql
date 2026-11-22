-- 변경 SQL 003 (2026-11-22 저녁 피드백 반영)
-- 대상: 002까지 적용한 DB (schema_v5.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. response_slot.kind 에서 'AVOID' 제거: 교수가 칠하는 것은 희망(PREFER)/불가(BLOCK) 둘뿐, 칠하지 않은 칸은 상관없음
--   2. course_response.lab_requirement: 'MUST'/'PREFER'/'NONE' → 정수 1(실습실 쓴다)/0(안 쓴다)
--
-- 기존 데이터 처리
--   - AVOID 칸은 지운다(= 상관없음으로 돌아감).
--   - lab_requirement: MUST, PREFER → 1 / NONE → 0.
--
-- 실행 방법 (SQLite): 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 ssuroom.db < migrations/003_20261122_lab_binary_no_avoid.sql

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE response_slot_new (                  -- 시간표에서 고른 칸
  response_id INTEGER REFERENCES course_response(id),
  slot_id INTEGER REFERENCES time_slot(id),
  kind TEXT NOT NULL CHECK (kind IN ('PREFER','BLOCK')),  -- PREFER 희망 / BLOCK 불가 (칠하지 않은 칸은 상관없음)
  PRIMARY KEY (response_id, slot_id)
);

INSERT INTO response_slot_new(response_id, slot_id, kind)
SELECT response_id, slot_id, kind FROM response_slot WHERE kind IN ('PREFER','BLOCK');
DROP TABLE response_slot;
ALTER TABLE response_slot_new RENAME TO response_slot;

CREATE TABLE course_response_new (                -- 교수가 과목별로 낸 응답
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 응답한 교수 (분반마다 교수가 다를 수 있어 교수별로 받음)
  lab_requirement INTEGER NOT NULL CHECK (lab_requirement IN (0,1)),      -- 실습실: 1=쓴다(실습실만 배정) / 0=안 쓴다 (사이트에서 필수 입력)
  single_day_pref TEXT NOT NULL CHECK (single_day_pref IN ('MUST','PREFER','NONE')),    -- 주 1회 연강(한 분반이 하루에 2칸 이어서): 무조건/선호/필요 없음
  prefer_only INTEGER NOT NULL DEFAULT 0 CHECK (prefer_only IN (0,1)),   -- 1 = '선호 시간 외에는 수업하기 어려움': 희망 칸 밖에는 배정하지 않음
  language TEXT,
  submitted_at TEXT,
  UNIQUE (round_id, course_id, professor_id)
);

INSERT INTO course_response_new(id, round_id, course_id, professor_id, lab_requirement, single_day_pref, prefer_only, language, submitted_at)
SELECT id, round_id, course_id, professor_id,
       CASE lab_requirement WHEN 'NONE' THEN 0 ELSE 1 END,
       single_day_pref, prefer_only, language, submitted_at FROM course_response;
DROP TABLE course_response;
ALTER TABLE course_response_new RENAME TO course_response;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
