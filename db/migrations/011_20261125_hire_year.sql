-- 변경 SQL 011 (2026-11-25, 교수 연차)
-- 대상: 010까지 적용한 DB (archive/schema_v13.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   user.hire_year (임용 연도, 비어 있어도 됨) 추가. 배정 엔진이 희망 칸을 두고 분반끼리 점수가 같을 때
--   ① 가능한 시간이 적은 분반 → ② 먼저 임용된 교수 → ③ 과목·분반 번호 순서로 정한다. 비어 있으면 ②를 건너뛴다.
--
-- 기존 데이터 처리: 모든 사용자 hire_year = NULL.
--
-- 실행 방법: sqlite3 -bail ssuroom.db < db/migrations/011_20261125_hire_year.sql   (두 번 실행하면 오류)

BEGIN;
ALTER TABLE user ADD COLUMN hire_year INTEGER CHECK (hire_year IS NULL OR hire_year BETWEEN 1950 AND 2100);   -- 교수 임용 연도 (연차)
COMMIT;
