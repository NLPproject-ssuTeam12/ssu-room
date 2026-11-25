-- 변경 SQL 008 (2026-11-25, 조교 [확인]·[수정]을 새 시간표 버전으로 저장)
-- 대상: 007까지 적용한 DB (archive/schema_v10.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. timetable.reason 추가 (NULL 허용): 이 버전을 만든 이유. 조교 [수정]의 사유, AI 도우미 [적용]의 사유 등.
--      db.apply_option 이 고른 안으로 바꾼 새 버전(kind='TA_EDIT', parent_id=이전 버전)에 적는다.
--
-- 기존 데이터 처리
--   - 기존 시간표 버전은 reason 이 NULL.
--
-- 실행 방법: 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 -bail ssuroom.db < db/migrations/008_20261125_timetable_reason.sql

BEGIN;
ALTER TABLE timetable ADD COLUMN reason TEXT;   -- 이 버전을 만든 이유 (조교 [수정] 사유, 도우미 [적용] 사유 등)
COMMIT;
