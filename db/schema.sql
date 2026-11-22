PRAGMA foreign_keys = ON;

-- ===== 기초 정보 (거의 안 바뀌는 것) =====
CREATE TABLE department (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, college TEXT   -- 단과대 (타 학과 확장 대비)
);
CREATE TABLE user (
  id INTEGER PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('TA','PROF')),
  name TEXT NOT NULL, email TEXT, phone TEXT,
  department_id INTEGER REFERENCES department(id),
  password_hash TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE time_grid (                      -- 시간 격자 한 벌 (예: 75분 교시제). 다른 방식이 필요하면 한 벌 더
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE time_slot (                      -- 교수가 화면에서 고르는 칸 하나
  id INTEGER PRIMARY KEY,
  grid_id INTEGER NOT NULL REFERENCES time_grid(id),
  day TEXT NOT NULL, period_no INTEGER NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT NOT NULL, label TEXT,
  UNIQUE (grid_id, day, period_no)
);
CREATE TABLE term (
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, semester TEXT NOT NULL,
  grid_id INTEGER NOT NULL REFERENCES time_grid(id),
  UNIQUE (year, semester)
);
CREATE TABLE building (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE room (
  id INTEGER PRIMARY KEY,
  building_id INTEGER NOT NULL REFERENCES building(id),
  room_no TEXT NOT NULL,
  capacity INTEGER, is_lab INTEGER DEFAULT 0,
  reserved_department_id INTEGER REFERENCES department(id),
  UNIQUE (building_id, room_no)
);
CREATE TABLE course (                         -- 조교가 입력한 과목. 분반은 결과에서 생김
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  department_id INTEGER REFERENCES department(id),
  code TEXT, name TEXT NOT NULL,
  professor_id INTEGER NOT NULL REFERENCES user(id),   -- 담당 교수
  category TEXT, target_year TEXT,
  expected_enrollment INTEGER,                         -- 과목 전체 예상 인원
  session_count INTEGER NOT NULL DEFAULT 1,            -- 주당 수업 횟수
  slots_per_session INTEGER NOT NULL DEFAULT 1         -- 1회 수업이 차지하는 칸 수
);
CREATE TABLE rule_config (                    -- 배정 규칙 켜기/끄기/가중치. 규칙이 늘어도 테이블은 그대로
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  rule_key TEXT NOT NULL,                              -- 예: PROF_NO_OVERLAP, BUILDING_PREF
  kind TEXT NOT NULL CHECK (kind IN ('HARD','SOFT')),
  weight REAL, enabled INTEGER DEFAULT 1, params_json TEXT,
  UNIQUE (term_id, rule_key)
);

-- ===== 1차: 희망 수집 =====
CREATE TABLE round (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  round_no INTEGER NOT NULL,
  opened_at TEXT, deadline_at TEXT NOT NULL,
  status TEXT DEFAULT 'OPEN',
  UNIQUE (term_id, round_no)
);
CREATE TABLE round_invite (
  round_id INTEGER REFERENCES round(id),
  professor_id INTEGER REFERENCES user(id),
  status TEXT DEFAULT 'PENDING', responded_at TEXT,
  PRIMARY KEY (round_id, professor_id)
);
CREATE TABLE course_response (                -- 교수가 과목별로 낸 응답
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  needs_lab INTEGER DEFAULT 0, language TEXT,
  note TEXT, submitted_at TEXT,
  UNIQUE (round_id, course_id)
);
CREATE TABLE response_slot (                  -- 시간표에서 고른 칸
  response_id INTEGER REFERENCES course_response(id),
  slot_id INTEGER REFERENCES time_slot(id),
  kind TEXT NOT NULL CHECK (kind IN ('PREFER','AVOID','BLOCK')),  -- BLOCK = 절대 불가
  PRIMARY KEY (response_id, slot_id)
);
CREATE TABLE request_item (
  id INTEGER PRIMARY KEY,
  response_id INTEGER NOT NULL REFERENCES course_response(id),
  type TEXT NOT NULL, value_int INTEGER, value_text TEXT,
  source TEXT DEFAULT 'NLP', status TEXT DEFAULT 'EXTRACTED',
  confirmed_by INTEGER REFERENCES user(id), confirmed_at TEXT
);
CREATE TABLE professor_building_pref (
  professor_id INTEGER REFERENCES user(id),
  building_id INTEGER REFERENCES building(id),
  rank INTEGER NOT NULL,
  PRIMARY KEY (professor_id, building_id)
);

-- ===== 솔버와 시간표 버전 =====
CREATE TABLE solver_run (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  started_at TEXT, finished_at TEXT, status TEXT,
  objective_value REAL, time_limit_sec INTEGER,
  weights_json TEXT, note TEXT
);
CREATE TABLE timetable (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  round_id INTEGER REFERENCES round(id),
  kind TEXT NOT NULL CHECK (kind IN ('DRAFT','TA_EDIT','FINAL')),
  solver_run_id INTEGER REFERENCES solver_run(id),
  parent_id INTEGER REFERENCES timetable(id),
  created_by INTEGER REFERENCES user(id),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE timetable_section (              -- 이 버전에서 열리는 분반
  timetable_id INTEGER REFERENCES timetable(id),
  course_id INTEGER REFERENCES course(id),
  section_no INTEGER,
  planned_enrollment INTEGER,
  PRIMARY KEY (timetable_id, course_id, section_no)
);
CREATE TABLE assignment (                     -- 분반의 수업 회차가 차지한 칸 하나당 한 행
  timetable_id INTEGER, course_id INTEGER, section_no INTEGER,
  session_no INTEGER,
  slot_id INTEGER REFERENCES time_slot(id),
  room_id INTEGER NOT NULL REFERENCES room(id),
  PRIMARY KEY (timetable_id, course_id, section_no, session_no, slot_id),
  FOREIGN KEY (timetable_id, course_id, section_no)
    REFERENCES timetable_section(timetable_id, course_id, section_no)
);
CREATE UNIQUE INDEX ux_assign_room ON assignment(timetable_id, room_id, slot_id);  -- 같은 시간·같은 강의실 불가 (DB가 막음)
CREATE INDEX ix_assign_slot  ON assignment(timetable_id, slot_id);

-- ===== 2차: 대안과 회신 =====
CREATE TABLE proposal (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  timetable_id INTEGER NOT NULL REFERENCES timetable(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  reason TEXT, status TEXT DEFAULT 'WAITING'
);
CREATE TABLE proposal_option (
  id INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES proposal(id),
  option_no INTEGER NOT NULL, source TEXT,
  UNIQUE (proposal_id, option_no)
);
CREATE TABLE proposal_option_slot (
  option_id INTEGER REFERENCES proposal_option(id),
  section_no INTEGER, session_no INTEGER,
  slot_id INTEGER REFERENCES time_slot(id),
  room_id INTEGER NOT NULL REFERENCES room(id),
  PRIMARY KEY (option_id, section_no, session_no, slot_id)
);
CREATE TABLE message (
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  proposal_id INTEGER REFERENCES proposal(id),
  sender_id INTEGER REFERENCES user(id),
  receiver_id INTEGER NOT NULL REFERENCES user(id),
  kind TEXT NOT NULL, channel TEXT,
  body TEXT, sent_at TEXT, delivery_status TEXT
);
CREATE TABLE reply_interpretation (
  message_id INTEGER PRIMARY KEY REFERENCES message(id),
  label TEXT, chosen_option_id INTEGER REFERENCES proposal_option(id),
  extracted_json TEXT, model_name TEXT,
  ta_action TEXT, ta_reason TEXT,
  ta_user_id INTEGER REFERENCES user(id), ta_at TEXT
);

-- ===== 조회·검사용 뷰 (테이블이 아니라 저장된 질의) =====
CREATE VIEW v_schedule AS                     -- 강의실별·건물별·교수별 조회의 기반
SELECT a.timetable_id, a.course_id, c.name AS course_name, a.section_no,
       c.professor_id, u.name AS professor_name, a.session_no,
       MIN(ts.day) AS day, MIN(ts.start_time) AS start_time, MAX(ts.end_time) AS end_time,
       b.id AS building_id, b.name AS building, r.id AS room_id, r.room_no
FROM assignment a
JOIN course c ON c.id=a.course_id
JOIN user u ON u.id=c.professor_id
JOIN time_slot ts ON ts.id=a.slot_id
JOIN room r ON r.id=a.room_id
JOIN building b ON b.id=r.building_id
GROUP BY a.timetable_id, a.course_id, a.section_no, a.session_no;
CREATE VIEW v_professor_conflict AS           -- 같은 칸에 한 교수가 두 분반을 맡은 경우 (규칙 위반 표시용)
SELECT a.timetable_id, c.professor_id, a.slot_id,
       COUNT(DISTINCT a.course_id || '-' || a.section_no) AS n
FROM assignment a JOIN course c ON c.id=a.course_id
GROUP BY a.timetable_id, c.professor_id, a.slot_id HAVING n > 1;
