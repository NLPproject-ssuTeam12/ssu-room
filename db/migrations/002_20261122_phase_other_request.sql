-- 변경 SQL 002 (2026-11-22 피드백 반영)
-- 대상: 변경 SQL 001까지 적용한 DB (schema_v4.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. term: phase(지금 단계: COLLECTING 희망 수집 / ROUND1 1차 조율 / ROUND2 2차 조율 / FINAL 확정), phase_changed_at 추가
--            phase_log 새 테이블(단계가 바뀐 기록)
--   2. course_response: prefer_only(선호 시간 외에는 수업하기 어려움 버튼) 추가, note 칸 제거
--   3. other_request 새 테이블: 교수가 쓴 기타 요청 자연어 원문 + 조교 확인 여부 (AI 해석 없이 조교가 확인함을 누름)
--   4. request_item: 솔버가 쓰는 구조화 요청만 남김. status/confirmed_by/confirmed_at 제거,
--                    other_request_id(어느 기타 요청을 보고 만들었는지), created_by, created_at 추가,
--                    source 값을 FORM(화면 항목) / TA(조교 입력) 로 제한
--
-- 기존 데이터 처리
--   - 기존 term 은 phase 가 'COLLECTING'(희망 수집)으로 시작한다. 이미 진행 중인 학기라면 실행 뒤에 직접 바꿀 것.
--   - 기존 course_response.note 는 other_request 로 옮기고 status 는 'PENDING'(미확인)으로 둔다. 조교가 다시 확인하면 된다.
--   - 기존 request_item: source 가 'FORM'이면 그대로, 그 밖('NLP' 등)은 'TA'. confirmed_by/confirmed_at 은 created_by/created_at 으로 옮긴다.
--   - 기존 course_response.prefer_only 는 모두 0.
--
-- 실행 방법 (SQLite): 반드시 이 파일 전체를 한 번에 실행한다. 실행 전에 DB 파일을 복사해 두는 것을 권장한다.
--   sqlite3 ssuroom.db < migrations/002_20261122_phase_other_request.sql
-- 두 번 실행하면 오류가 난다(이미 적용된 DB에는 쓰지 말 것).
-- 주의: term 에 칸이 늘어서, 칸 이름 없이 INSERT INTO term VALUES (...) 로 넣던 코드는 칸 이름을 적도록 고쳐야 한다.

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 서버 단계
ALTER TABLE term ADD COLUMN phase TEXT NOT NULL DEFAULT 'COLLECTING'
      CHECK (phase IN ('COLLECTING','ROUND1','ROUND2','FINAL'));   -- 지금 단계: 희망 수집 / 1차 조율 / 2차 조율 / 확정
ALTER TABLE term ADD COLUMN phase_changed_at TEXT;
CREATE TABLE phase_log (                      -- 단계가 바뀐 기록 (누가, 언제)
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  from_phase TEXT, to_phase TEXT NOT NULL,
  changed_by INTEGER REFERENCES user(id),
  changed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 3. 기타 요청 (먼저 만들고, 기존 note 를 옮긴다)
CREATE TABLE other_request (                 -- 교수가 '기타 요청사항'에 자연어로 쓴 글. AI가 해석하지 않고 조교가 읽고 '확인'을 누른다
  id INTEGER PRIMARY KEY,
  response_id INTEGER NOT NULL UNIQUE REFERENCES course_response(id),
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','CONFIRMED')),  -- 미확인 / 조교 확인함
  confirmed_by INTEGER REFERENCES user(id), confirmed_at TEXT,
  ta_memo TEXT,                                        -- 조교 메모 (예: "분반 2개로 입력함", "수동 처리")
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO other_request(response_id, body, status)
SELECT id, note, 'PENDING' FROM course_response WHERE note IS NOT NULL AND TRIM(note) <> '';

-- 2. course_response 다시 만들기 (prefer_only 추가, note 제거)
CREATE TABLE course_response_new (                -- 교수가 과목별로 낸 응답
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 응답한 교수 (분반마다 교수가 다를 수 있어 교수별로 받음)
  lab_requirement TEXT NOT NULL CHECK (lab_requirement IN ('MUST','PREFER','NONE')),      -- 실습실: 무조건/선호/필요 없음 (사이트에서 필수 입력)
  single_day_pref TEXT NOT NULL CHECK (single_day_pref IN ('MUST','PREFER','NONE')),    -- 주 1회 연강(한 분반이 하루에 2칸 이어서): 무조건/선호/필요 없음
  prefer_only INTEGER NOT NULL DEFAULT 0 CHECK (prefer_only IN (0,1)),   -- 1 = '선호 시간 외에는 수업하기 어려움': 희망 칸 밖에는 배정하지 않음
  language TEXT,
  submitted_at TEXT,
  UNIQUE (round_id, course_id, professor_id)
);

INSERT INTO course_response_new(id, round_id, course_id, professor_id, lab_requirement, single_day_pref, prefer_only, language, submitted_at)
SELECT id, round_id, course_id, professor_id, lab_requirement, single_day_pref, 0, language, submitted_at FROM course_response;
DROP TABLE course_response;
ALTER TABLE course_response_new RENAME TO course_response;

-- 4. request_item 다시 만들기
CREATE TABLE request_item_new (                   -- 솔버가 쓰는 구조화된 요청 (분반 수, 분반 연강·교차 등). 조교가 기타 요청을 읽고 입력하거나 화면 항목에서 바로 생성
  id INTEGER PRIMARY KEY,
  response_id INTEGER NOT NULL REFERENCES course_response(id),
  other_request_id INTEGER REFERENCES other_request(id),   -- 어느 기타 요청을 보고 만들었는지 (화면 항목에서 만들면 NULL)
  type TEXT NOT NULL, value_int INTEGER, value_text TEXT,
  params_json TEXT,                                    -- 요일·교시 등 상세 조건
  source TEXT NOT NULL DEFAULT 'TA' CHECK (source IN ('FORM','TA')),   -- 화면 항목 / 조교 입력
  created_by INTEGER REFERENCES user(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO request_item_new(id, response_id, other_request_id, type, value_int, value_text, params_json, source, created_by, created_at)
SELECT id, response_id, NULL, type, value_int, value_text, params_json,
       CASE source WHEN 'FORM' THEN 'FORM' ELSE 'TA' END,
       confirmed_by, COALESCE(confirmed_at, datetime('now'))
FROM request_item;
DROP TABLE request_item;
ALTER TABLE request_item_new RENAME TO request_item;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
