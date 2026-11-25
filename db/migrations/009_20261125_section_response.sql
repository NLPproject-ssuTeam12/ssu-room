-- 변경 SQL 009 (2026-11-25, 분반별 희망 입력·분반 연강·교차 요청·조율 대상 구분)
-- 대상: 008까지 적용한 DB (archive/schema_v11.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 배경 1: 희망 입력이 (과목, 교수) 단위라 분반마다 다른 시간·실습실·주 1회 연강을 받을 수 없고,
--         "가반 바로 뒤 나반"처럼 두 분반 사이의 관계는 분반 한 칸에 넣을 수 없다.
-- 배경 2: 못 놓은 분반에만 조율 메시지를 보내면 희망 시간·건물에서 어긋난 분반은 조율할 수 없다.
--
-- 바뀌는 것
--   1. course_response 를 분반 단위로: section_no 추가. 칠한 칸(response_slot)·실습실·주 1회 연강은 분반마다.
--      인원은 지금처럼 course_section.enrollment(분반마다). 기타 요청(other_request)도 응답(=분반)마다 하나.
--      UNIQUE (차수, 과목, 분반, 교수): 분반 담당 교수가 바뀌면 이전 교수의 응답은 남지만 솔버는 담당 교수 응답만 읽는다.
--   2. section_pair 칸을 없애고 pair_request · pair_request_section 으로: 같은 교수가 한 과목에서 두 분반 이상 맡을 때
--      과목 단위로 한 번, 연강(BACK_TO_BACK) / 교차(CROSS)와 붙일 분반을 교수가 적은 순서대로. 상관없음 = 행 없음.
--      솔버는 앞 두 분반만 붙인다. 셋째 분반부터는 조교가 수동 배치·고정한다.
--   3. proposal: status 에 HOLD(조교 선택 대기)·NO_OPTION(대안 없음, 조교 확인) 추가,
--      target_kind(UNPLACED 못 놓음 / MISMATCH 희망에서 어긋남 / PARTIAL 일부 어긋남) 추가.
--
-- 기존 데이터 처리
--   - 응답 하나 → 그 교수가 그 과목에서 맡은 분반마다 한 행 (course_section 기준). 첫 분반은 id 그대로,
--     나머지 분반은 새 id 로 만들고 칠한 칸을 복사한다. 기타 요청·request_item 은 첫 분반 응답에 그대로 남는다.
--     course_section 에 행이 없는 과목, 또는 그 교수가 맡은 분반이 없으면 1분반.
--   - section_pair 가 NONE 이 아닌 응답 → pair_request 한 행, 붙일 분반 = 그 교수가 맡은 분반을 번호 순서대로.
--   - proposal 은 그대로 옮기고 target_kind 는 NULL.
--
-- 실행 방법: 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 -bail ssuroom.db < db/migrations/009_20261125_section_response.sql
--   (Python 의 executescript 는 첫 오류에서 멈춘다. 멈추면 con.rollback() 으로 되돌린다.)

PRAGMA foreign_keys = OFF;
BEGIN;

-- 2. 분반 연강·교차 요청 (course_response 를 다시 만들기 전에 옛 section_pair 를 옮긴다)
CREATE TABLE pair_request (                  -- 같은 교수가 한 과목에서 두 분반 이상 맡을 때 분반 사이의 관계 (과목 단위로 한 번). 상관없음 = 행 없음
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  professor_id INTEGER NOT NULL REFERENCES user(id),
  mode TEXT NOT NULL CHECK (mode IN ('BACK_TO_BACK','CROSS')),   -- 연강(앞 분반 바로 뒤 다음 분반) / 교차
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (round_id, course_id, professor_id)
);
CREATE TABLE pair_request_section (          -- 붙일 분반, 교수가 적은 순서대로. 솔버는 앞 두 분반만 붙이고 셋째부터는 조교가 수동 배치·고정
  request_id INTEGER NOT NULL REFERENCES pair_request(id),
  seq INTEGER NOT NULL,                                -- 1, 2, 3, …
  section_no INTEGER NOT NULL,
  PRIMARY KEY (request_id, seq),
  UNIQUE (request_id, section_no)
);
INSERT INTO pair_request(round_id, course_id, professor_id, mode)
SELECT round_id, course_id, professor_id, section_pair FROM course_response WHERE section_pair <> 'NONE';
INSERT INTO pair_request_section(request_id, seq, section_no)
SELECT p.id, (SELECT COUNT(*) FROM course_section s2 WHERE s2.course_id = s.course_id AND s2.professor_id = s.professor_id
              AND s2.section_no <= s.section_no), s.section_no
FROM pair_request p JOIN course_section s ON s.course_id = p.course_id AND s.professor_id = p.professor_id;

-- 1. 분반 단위 응답
CREATE TABLE course_response_new (            -- 교수가 분반마다 낸 희망 입력 (칠한 칸·실습실·주 1회 연강). 인원은 course_section.enrollment
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER NOT NULL DEFAULT 1,               -- 어느 분반의 응답인지
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 응답한 교수 (솔버는 그 분반 담당 교수의 응답만 읽는다)
  lab_requirement INTEGER NOT NULL CHECK (lab_requirement IN (0,1)),      -- 실습실: 1=쓴다(실습실만 배정) / 0=안 쓴다 (사이트에서 필수 입력)
  single_day_pref TEXT NOT NULL CHECK (single_day_pref IN ('MUST','NONE')),    -- 주 1회 연강(한 분반이 하루에 2칸 이어서): 무조건 / 필요 없음(주 2회)
  submitted_at TEXT,
  UNIQUE (round_id, course_id, section_no, professor_id)
);
INSERT INTO course_response_new(id, round_id, course_id, section_no, professor_id, lab_requirement, single_day_pref, submitted_at)
SELECT r.id, r.round_id, r.course_id,
       COALESCE((SELECT MIN(s.section_no) FROM course_section s WHERE s.course_id = r.course_id AND s.professor_id = r.professor_id), 1),
       r.professor_id, r.lab_requirement, r.single_day_pref, r.submitted_at
FROM course_response r;
INSERT INTO course_response_new(round_id, course_id, section_no, professor_id, lab_requirement, single_day_pref, submitted_at)
SELECT r.round_id, r.course_id, s.section_no, r.professor_id, r.lab_requirement, r.single_day_pref, r.submitted_at
FROM course_response r JOIN course_section s ON s.course_id = r.course_id AND s.professor_id = r.professor_id
WHERE s.section_no > (SELECT MIN(s2.section_no) FROM course_section s2 WHERE s2.course_id = r.course_id AND s2.professor_id = r.professor_id)
ORDER BY r.id, s.section_no;
INSERT INTO response_slot(response_id, slot_id, kind)
SELECT n.id, rs.slot_id, rs.kind
FROM course_response_new n
JOIN course_response r ON r.round_id = n.round_id AND r.course_id = n.course_id AND r.professor_id = n.professor_id AND r.id <> n.id
JOIN response_slot rs ON rs.response_id = r.id
WHERE n.id NOT IN (SELECT id FROM course_response);
DROP TABLE course_response;
ALTER TABLE course_response_new RENAME TO course_response;

-- 3. 조율 안건: 보류·대안 없음 상태와 조율 대상 종류
CREATE TABLE proposal_new (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  timetable_id INTEGER NOT NULL REFERENCES timetable(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER,                                  -- 어느 분반의 조율인지 (NULL = 과목 전체)
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN'
         CHECK (status IN ('OPEN','SENT','PROPOSED','RESOLVED','KEPT','NEXT','OFFLINE','HOLD','NO_OPTION')),
         -- 보내기 전 / 답 기다림 / 조교 확인 대기 / 반영됨 / 현재대로 유지 / 다음 차수로 / 따로 연락 중 / 조교 선택 대기(일부 어긋남) / 대안 없음(조교 확인)
  prev_proposal_id INTEGER REFERENCES proposal(id),    -- 이어받은 이전 차수 안건 (NULL = 1차 또는 처음 연 안건)
  target_kind TEXT CHECK (target_kind IN ('UNPLACED','MISMATCH','PARTIAL'))   -- 조율 대상 종류: 못 놓음 / 희망(시간·건물)에서 어긋남 / 일부 어긋남. NULL = 009 전 안건
);
INSERT INTO proposal_new(id, round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id)
SELECT id, round_id, timetable_id, course_id, section_no, reason, status, prev_proposal_id FROM proposal;
DROP TABLE proposal;
ALTER TABLE proposal_new RENAME TO proposal;
CREATE UNIQUE INDEX ux_proposal_prev ON proposal(prev_proposal_id);   -- 한 안건에서 다음 차수 안건은 하나만

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
