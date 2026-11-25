-- 변경 SQL 007 (2026-11-25, 교수 답장 선택·따로 연락·수동 배치 고정)
-- 대상: 006까지 적용한 DB (archive/schema_v9.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 배경: 교수가 "셋 다 어렵습니다"처럼 조건 없이 거절하면 처리안이 '다음 차수'인데 넘길 조건이 없어 [확인] 때 저장 오류가 났다.
-- 바뀌는 것
--   1. reply_choice 추가: 교수 답장마다 고른 값 A / B / C / 기타(ETC). 하나 이상 골라야 답장을 낼 수 있고 여러 개 골라도 된다.
--      A·B·C 는 그 안건의 대안(proposal_option option_no 1·2·3)을 가리킨다. 기타 글은 답장 본문(message.body).
--   2. proposal.status 에 'OFFLINE' 추가: 조교가 [따로 연락]을 고름 → 시스템 밖(전화·메일 등)에서 조율 중.
--      조교가 수동 배치를 기록하면 RESOLVED 가 된다. (CHECK 를 바꾸려고 proposal 을 다시 만든다)
--   3. timetable_section.locked 추가 (0/1, 기본 0): 고정된 분반. 이후 모든 풀이(부분 재풀이·대안·전체 재풀이)에서 움직이지 않는다.
--   4. other_request 가 답장에서도 나올 수 있게: message_id 추가, response_id 는 NULL 허용.
--      희망 입력의 기타 요청(response_id) 또는 답장 기타의 시간표 밖 요청(message_id) 중 정확히 하나를 가리킨다.
--      (NOT NULL·CHECK 를 바꾸려고 other_request 를 다시 만든다. request_item 이 가리키는 연결은 이름으로 이어져 유지된다)
--
-- 기존 데이터 처리
--   - 기존 답장에는 고른 값 기록이 없다(reply_choice 비어 있음). 새 답장부터 기록한다.
--   - proposal 은 id·회차·시간표·과목·분반·이유·상태·이전 안건을 그대로 옮긴다.
--   - timetable_section 의 기존 행은 locked = 0.
--   - other_request 는 그대로 옮기고 message_id 는 NULL.
--
-- 실행 방법: 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 -bail ssuroom.db < db/migrations/007_20261125_reply_choice.sql
--   (Python 의 executescript 는 첫 오류에서 멈춘다. 멈추면 con.rollback() 으로 되돌린다.)

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 답장에서 고른 값
CREATE TABLE reply_choice (                  -- 교수 답장에서 고른 값 (하나 이상, 여러 개 가능)
  message_id INTEGER NOT NULL REFERENCES message(id),
  choice TEXT NOT NULL CHECK (choice IN ('A','B','C','ETC')),   -- 대안 A / B / C / 기타(답장 본문)
  option_id INTEGER REFERENCES proposal_option(id),    -- A·B·C 가 가리키는 대안 (기타는 NULL)
  PRIMARY KEY (message_id, choice)
);

-- 2. 조율 안건 상태에 따로 연락(OFFLINE)
CREATE TABLE proposal_new (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  timetable_id INTEGER NOT NULL REFERENCES timetable(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER,                                  -- 어느 분반의 조율인지 (NULL = 과목 전체)
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN'
         CHECK (status IN ('OPEN','SENT','PROPOSED','RESOLVED','KEPT','NEXT','OFFLINE')),   -- 보내기 전 / 답 기다림 / 조교 확인 대기 / 반영됨 / 현재대로 유지 / 다음 차수로 / 따로 연락 중
  prev_proposal_id INTEGER REFERENCES proposal(id)     -- 이어받은 이전 차수 안건 (NULL = 1차 또는 처음 연 안건)
);
INSERT INTO proposal_new(id, round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id)
SELECT id, round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id FROM proposal;
DROP TABLE proposal;
ALTER TABLE proposal_new RENAME TO proposal;
CREATE UNIQUE INDEX ux_proposal_prev ON proposal(prev_proposal_id);   -- 한 안건에서 다음 차수 안건은 하나만

-- 3. 고정된 분반
ALTER TABLE timetable_section ADD COLUMN locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0,1));   -- 1 = 고정 (조교 수동 배치 등)

-- 4. 기타 요청: 희망 입력 또는 답장
CREATE TABLE other_request_new (             -- 교수가 '기타'에 자연어로 쓴 시간표 밖 요청. AI가 시간표 조건으로 쓰지 않고 조교가 읽고 '확인'을 누른다
  id INTEGER PRIMARY KEY,
  response_id INTEGER UNIQUE REFERENCES course_response(id),   -- 희망 입력의 기타 요청 (응답당 하나)
  message_id INTEGER UNIQUE REFERENCES message(id),            -- 조율 답장의 기타 중 시간표 밖 요청 (답장당 하나)
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','CONFIRMED')),  -- 미확인 / 조교 확인함
  confirmed_by INTEGER REFERENCES user(id), confirmed_at TEXT,
  ta_memo TEXT,                                        -- 조교 메모 (예: "분반 2개로 입력함", "수동 처리")
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  CHECK ((response_id IS NULL) <> (message_id IS NULL))   -- 둘 중 정확히 하나
);
INSERT INTO other_request_new(id, response_id, message_id, body, status, confirmed_by, confirmed_at, ta_memo, created_at)
SELECT id, response_id, NULL, body, status, confirmed_by, confirmed_at, ta_memo, created_at FROM other_request;
DROP TABLE other_request;
ALTER TABLE other_request_new RENAME TO other_request;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
