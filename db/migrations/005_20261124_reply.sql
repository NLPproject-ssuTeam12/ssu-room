-- 변경 SQL 005 (2026-11-24, 교수 직접 회신)
-- 대상: 004까지 적용한 DB (archive/schema_v7.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. message.reply_to_id 추가 (NULL 허용): 교수 답장(kind='REPLY')이 답하는 조율 메시지의 id
--   2. proposal.status 에 값 6개만 허용 (CHECK), 기본값 'WAITING' → 'OPEN'. 서버 조율 상태와 같은 이름
--        OPEN     메시지를 보내기 전
--        SENT     메시지를 보내 교수 답을 기다림
--        PROPOSED 답장을 읽어 처리안이 나옴, 조교 확인 대기
--        RESOLVED 조교가 [확인](처리안 '옮김') 또는 [수정]해 반영됨
--        KEPT     조교가 [현재대로 유지]
--        NEXT     조교가 [확인](처리안 '다음 차수'). 이번 차수는 처리했고, 확인된 조건을 들고 다음 차수로 넘어감
--   3. proposal.prev_proposal_id 추가 (NULL 허용, 자기 참조): 다음 차수 안건이 이어받은 이전 차수 안건.
--      다음 차수에는 같은 안건을 되돌리지 않고 새 행을 만든다. 한 안건에서 다음 차수 안건은 하나만 (UNIQUE).
--   4. timetable_section.status 추가 (DONE / COORD / MANUAL, 기본값 'DONE'): 분반 배정 상태. 서버 assignment.status 와 같은 이름
--        DONE   희망대로 놓였거나 조율이 끝남
--        COORD  조율 중 (아직 안 풀림)
--        MANUAL 조교가 직접 정함
--      분반이 아직 안 풀렸는지는 proposal.status 가 아니라 이 값으로 판단한다.
--      (SQLite 는 CHECK 를 고칠 수 없어서 proposal 테이블을 다시 만든다. 004의 term 과 같은 방식.
--       proposal_option, message 가 proposal 을 가리키는 연결은 이름으로 이어져 그대로 유지된다.)
--
-- 기존 데이터 처리
--   - message 의 기존 행은 reply_to_id 가 NULL 이 된다 (어느 메시지에 대한 답인지 기록이 없었으므로).
--   - timetable_section 의 기존 행은 status 가 'DONE' 이 된다 (조율 중이었다는 기록이 없었으므로). 조율 중인 분반은 서버가 'COORD' 로 바꾼다.
--   - proposal 의 id, 회차, 시간표, 과목, 분반, 이유를 그대로 옮긴다. prev_proposal_id 는 NULL. status 'WAITING'(옛 기본값)과 NULL 은 'OPEN' 으로 옮긴다.
--   - 위 6개와 WAITING·NULL 밖의 status 가 있으면 CHECK 에 걸려 멈춘다 (조용히 바꾸지 않는다). 실행 전에 확인:
--       SELECT id, status FROM proposal WHERE status IS NOT NULL
--         AND status NOT IN ('WAITING','OPEN','SENT','PROPOSED','RESOLVED','KEPT','NEXT');
--     나온 행이 있으면 어떤 상태로 옮길지 정해 직접 UPDATE 한 뒤 실행한다.
--
-- 실행 방법 (SQLite): 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다(이미 적용된 DB에는 쓰지 말 것).
--   sqlite3 -bail ssuroom.db < db/migrations/005_20261124_reply.sql
--   -bail 을 꼭 붙인다: 붙이지 않으면 sqlite3 가 오류 뒤에도 다음 줄을 계속 실행해, 옮기기가 실패해도 옛 proposal 을 지울 수 있다.
--   (Python 의 executescript 는 첫 오류에서 멈춘다. 멈추면 con.rollback() 으로 되돌린다.)

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 답장이 가리키는 조율 메시지
ALTER TABLE message ADD COLUMN reply_to_id INTEGER REFERENCES message(id);   -- 교수 답장(REPLY)이 답하는 조율 메시지

-- 2. 분반 배정 상태
ALTER TABLE timetable_section ADD COLUMN status TEXT NOT NULL DEFAULT 'DONE'
      CHECK (status IN ('DONE','COORD','MANUAL'));   -- 끝남 / 조율 중 / 조교가 직접 정함

-- 3. 조율 안건 상태, 이전 차수 안건
CREATE TABLE proposal_new (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  timetable_id INTEGER NOT NULL REFERENCES timetable(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  section_no INTEGER,                                  -- 어느 분반의 조율인지 (NULL = 과목 전체)
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN'
         CHECK (status IN ('OPEN','SENT','PROPOSED','RESOLVED','KEPT','NEXT')),   -- 보내기 전 / 답 기다림 / 조교 확인 대기 / 반영됨 / 현재대로 유지 / 다음 차수로
  prev_proposal_id INTEGER REFERENCES proposal(id)     -- 이어받은 이전 차수 안건 (NULL = 1차 또는 처음 연 안건)
);

INSERT INTO proposal_new(id, round_id, timetable_id, course_id, section_no, reason, status)
SELECT id, round_id, timetable_id, course_id, section_no, reason,
       CASE WHEN status IS NULL OR status = 'WAITING' THEN 'OPEN' ELSE status END
FROM proposal;
DROP TABLE proposal;
ALTER TABLE proposal_new RENAME TO proposal;
CREATE UNIQUE INDEX ux_proposal_prev ON proposal(prev_proposal_id);   -- 한 안건에서 다음 차수 안건은 하나만 (NULL 은 여러 개 가능)

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
