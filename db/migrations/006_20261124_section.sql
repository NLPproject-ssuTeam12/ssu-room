-- 변경 SQL 006 (2026-11-24, 분반·건물·수강 인원 피드백)
-- 대상: 005까지 적용한 DB (archive/schema_v8.sql 모양)  →  현재 schema.sql 과 같은 모양
--
-- 바뀌는 것
--   1. 분반은 오프라인 회의에서 정해진 뒤 프로그램을 쓴다 → 분반마다 한 행(course_section)이 기준.
--      course_section.enrollment 추가 (분반 수강 인원, 교수가 정함, NULL = 아직 모름, 0 이하 불가).
--      솔버는 더 이상 교수 요청(request_item SECTION_COUNT)으로 분반 수를 정하지 않는다.
--      course_section 에 행이 없는 과목은 course.professor_id 가 맡는 1분반 하나로 본다.
--   2. course.expected_enrollment(과목 전체 예상 인원) 삭제 → 분반 수강 인원으로 대신.
--      수강 인원이 강의실 정원보다 많으면 그 강의실은 후보에서 뺀다(솔버 하드 규칙).
--   3. course_response.prefer_only('선호 시간 외에는 수업하기 어려움') 삭제.
--   4. course_response.language(강의 언어) 삭제.
--   5. professor_building_pref: 건물 순위(rank) 대신 교수당 희망 건물 하나 (professor_id 가 기본키).
--      그 밖의 건물에 배정하면 솔버가 벌점을 준다.
--
-- 기존 데이터 처리
--   - 분반 행이 있는 과목: 각 분반 enrollment = 과목 예상 인원 ÷ 분반 수 (올림). 예전 솔버가 쓰던 값과 같다.
--   - 분반 행이 없고 예상 인원이 있는 과목: 1분반 행을 만들어(담당 = course.professor_id) 예상 인원을 넣는다.
--     예상 인원이 없는(NULL·0) 과목은 행을 만들지 않는다 (1분반, 인원 미정으로 본다).
--     ※ 예전에 교수 요청(SECTION_COUNT)으로 분반이 여러 개였던 과목은 실행 뒤 조교가 course_section 에 분반을 직접 넣어야 한다.
--       확인: SELECT r.course_id, MAX(i.value_int) FROM request_item i JOIN course_response r ON r.id = i.response_id
--             WHERE i.type = 'SECTION_COUNT' GROUP BY r.course_id;
--   - request_item 의 SECTION_COUNT 행은 지우지 않는다 (기록으로 남김, 솔버는 읽지 않음).
--   - 건물: 교수마다 가장 높은 순위(rank 가 가장 작은) 건물 하나만 남긴다. 같은 순위가 여럿이면 번호가 작은 건물.
--     2순위 이하는 버린다.
--   - prefer_only, language 값은 버린다.
--
-- 실행 방법 (SQLite 3.35 이상, DROP COLUMN 때문): 파일 전체를 한 번에, 실행 전에 DB 파일 복사. 두 번 실행하면 오류가 난다.
--   sqlite3 -bail ssuroom.db < db/migrations/006_20261124_section.sql
--   (Python 의 executescript 는 첫 오류에서 멈춘다. 멈추면 con.rollback() 으로 되돌린다.)

PRAGMA foreign_keys = OFF;
BEGIN;

-- 1. 분반 수강 인원
ALTER TABLE course_section ADD COLUMN enrollment INTEGER CHECK (enrollment IS NULL OR enrollment > 0);   -- 분반 수강 인원 (교수가 정함)

UPDATE course_section
SET enrollment = (SELECT (c.expected_enrollment + n.cnt - 1) / n.cnt
                  FROM course c
                  JOIN (SELECT course_id, COUNT(*) AS cnt FROM course_section GROUP BY course_id) n ON n.course_id = c.id
                  WHERE c.id = course_section.course_id AND c.expected_enrollment > 0);

INSERT INTO course_section(course_id, section_no, professor_id, enrollment)
SELECT id, 1, professor_id, expected_enrollment FROM course
WHERE expected_enrollment > 0 AND id NOT IN (SELECT course_id FROM course_section);

-- 2. 과목 전체 예상 인원 삭제
ALTER TABLE course DROP COLUMN expected_enrollment;

-- 3·4. 선호 시간 외 불가, 강의 언어 삭제
ALTER TABLE course_response DROP COLUMN prefer_only;
ALTER TABLE course_response DROP COLUMN language;

-- 5. 희망 건물: 교수당 하나
CREATE TABLE professor_building_pref_new (       -- 교수가 고른 희망 건물 하나. 그 밖의 건물은 솔버 벌점
  professor_id INTEGER PRIMARY KEY REFERENCES user(id),
  building_id INTEGER NOT NULL REFERENCES building(id)
);
INSERT INTO professor_building_pref_new(professor_id, building_id)
SELECT p.professor_id, MIN(p.building_id) FROM professor_building_pref p
WHERE p.professor_id IS NOT NULL AND p.building_id IS NOT NULL
  AND p.rank = (SELECT MIN(q.rank) FROM professor_building_pref q WHERE q.professor_id = p.professor_id)
GROUP BY p.professor_id;
DROP TABLE professor_building_pref;
ALTER TABLE professor_building_pref_new RENAME TO professor_building_pref;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;   -- 아무것도 출력되지 않아야 정상
