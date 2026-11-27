-- 변경 SQL 012 (2026-11-27, 학기별 강의실 켜기·학기별 희망 건물·희망 입력 요청 기록)
-- 대상: 011까지 적용한 DB (archive/schema_v14.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   ① term_room(학기, 강의실) 추가: 그 학기에 배정에 쓰는(켠) 강의실. 행 없음 = 꺼짐.
--      건물은 따로 켜지 않는다. 켜진 강의실이 하나라도 있는 건물이 그 학기에 고를 수 있는 건물이다.
--      배정 엔진은 켜진 강의실만 후보로 쓴다(고정·움직이지 않는 분반은 이미 놓인 방 그대로).
--   ② 기본값 트리거
--      trg_room_on     강의실을 새로 넣으면 확정(FINAL) 전 모든 학기에 켠다.
--      trg_term_rooms  학기를 새로 넣으면 바로 전 학기(연도·학기 순)에 켠 강의실을 그대로 켠다. 전 학기가 없으면 모든 강의실을 켠다.
--      그래서 강의실·학기를 직접 INSERT 하는 시드·테스트도 지금처럼 모든 강의실을 쓴다.
--   ③ professor_building_pref 를 학기별로: (term_id, professor_id) 가 키. 그 학기에 켜진 건물만 고를 수 있다(db.set_building_pref).
--   ④ round_invite.invited_at(요청 보낸 시각)·reminded_at(마지막 재알림 시각) 추가.
--
-- 기존 데이터 처리
--   term_room: 모든 학기 × 모든 강의실을 켠다 (지금까지와 같은 배정 범위).
--   professor_building_pref: 기존 교수당 한 행을 모든 학기에 복사한다.
--   round_invite: invited_at·reminded_at = NULL.
--
-- 주의: professor_building_pref 에 term_id 없이 INSERT 하던 코드는 실패한다(NOT NULL). 칸 이름과 학기를 적어 넣는다.
--
-- 실행 방법: sqlite3 -bail ssuroom.db < db/migrations/012_20261127_term_room_invite.sql   (두 번 실행하면 오류)

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE term_room (                      -- 그 학기에 배정에 쓰는(켠) 강의실. 행 없음 = 꺼짐. 켜진 강의실이 하나라도 있는 건물이 그 학기에 고를 수 있는 건물 (012)
  term_id INTEGER NOT NULL REFERENCES term(id),
  room_id INTEGER NOT NULL REFERENCES room(id),
  PRIMARY KEY (term_id, room_id)
);
INSERT INTO term_room(term_id, room_id) SELECT t.id, r.id FROM term t CROSS JOIN room r;

CREATE TABLE professor_building_pref_new (   -- 교수가 그 학기에 고른 희망 건물 하나. 그 밖의 건물은 솔버 벌점. 그 학기에 켜진 건물만 고를 수 있다 (012에서 학기별로)
  term_id INTEGER NOT NULL REFERENCES term(id),
  professor_id INTEGER NOT NULL REFERENCES user(id),
  building_id INTEGER NOT NULL REFERENCES building(id),
  PRIMARY KEY (term_id, professor_id)
);
INSERT INTO professor_building_pref_new(term_id, professor_id, building_id)
  SELECT t.id, p.professor_id, p.building_id FROM professor_building_pref p CROSS JOIN term t;
DROP TABLE professor_building_pref;
ALTER TABLE professor_building_pref_new RENAME TO professor_building_pref;

ALTER TABLE round_invite ADD COLUMN invited_at TEXT;    -- 요청을 보낸 시각 (012)
ALTER TABLE round_invite ADD COLUMN reminded_at TEXT;   -- 마지막으로 다시 알린 시각 (012)

CREATE TRIGGER trg_room_on AFTER INSERT ON room      -- 새 강의실은 확정(FINAL) 전 모든 학기에 켠다
BEGIN
  INSERT OR IGNORE INTO term_room(term_id, room_id) SELECT id, NEW.id FROM term WHERE phase <> 'FINAL';
END;
CREATE TRIGGER trg_term_rooms AFTER INSERT ON term    -- 새 학기는 바로 전 학기(연도·학기 순)에 켠 강의실을 그대로 (전 학기가 없으면 전부)
BEGIN
  INSERT OR IGNORE INTO term_room(term_id, room_id)
    SELECT NEW.id, tr.room_id FROM term_room tr
    WHERE tr.term_id = (SELECT p.id FROM term p WHERE p.id <> NEW.id
                          AND (p.year < NEW.year OR (p.year = NEW.year AND p.semester < NEW.semester))
                        ORDER BY p.year DESC, p.semester DESC LIMIT 1);
  INSERT OR IGNORE INTO term_room(term_id, room_id)
    SELECT NEW.id, r.id FROM room r
    WHERE NOT EXISTS (SELECT 1 FROM term p WHERE p.id <> NEW.id
                        AND (p.year < NEW.year OR (p.year = NEW.year AND p.semester < NEW.semester)));
END;

COMMIT;
PRAGMA foreign_keys = ON;
