-- 변경 SQL 004 (2026-11-22 밤)
-- 대상: 003까지 적용한 DB (archive/schema_v6.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   term.phase 에 'ROUND3'(3차 조율)을 추가한다. 단계 순서: COLLECTING → ROUND1 → ROUND2 → ROUND3 → FINAL
--   (SQLite 는 CHECK 를 고칠 수 없어서 term 테이블을 다시 만든다. 다른 테이블이 term 을 가리키는 연결은 이름으로 이어져 그대로 유지된다.)
--
-- 기존 데이터 처리
--   - 모든 학기의 id, 연도, 학기, 시간 격자, 지금 단계, 단계 바뀐 시각을 그대로 옮긴다.
--
-- 실행 방법 (SQLite): 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행해도 오류는 없지만 하지 않는 편이 안전하다.
--   sqlite3 ssuroom.db < db/migrations/004_20261122_phase_round3.sql

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE term_new (
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, semester TEXT NOT NULL,
  grid_id INTEGER NOT NULL REFERENCES time_grid(id),
  phase TEXT NOT NULL DEFAULT 'COLLECTING'
        CHECK (phase IN ('COLLECTING','ROUND1','ROUND2','ROUND3','FINAL')),   -- 지금 단계: 희망 수집 / 1차 조율 / 2차 조율 / 3차 조율 / 확정
  phase_changed_at TEXT,
  UNIQUE (year, semester)
);

INSERT INTO term_new(id, year, semester, grid_id, phase, phase_changed_at)
SELECT id, year, semester, grid_id, phase, phase_changed_at FROM term;
DROP TABLE term;
ALTER TABLE term_new RENAME TO term;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
