PRAGMA foreign_keys = ON;

-- ===== 기본 정보 =====
CREATE TABLE user (
  id INTEGER PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('TA','PROF')),   -- 조교 / 교수
  name TEXT NOT NULL,
  email TEXT, phone TEXT,                              -- 독촉 발송용
  department TEXT,
  password_hash TEXT NOT NULL,                         -- 비밀번호 원문은 저장 금지
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE term (
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, semester TEXT NOT NULL,
  UNIQUE (year, semester)
);
CREATE TABLE building (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE room (
  id INTEGER PRIMARY KEY,
  building_id INTEGER NOT NULL REFERENCES building(id),
  room_no TEXT NOT NULL,
  capacity INTEGER, is_lab INTEGER DEFAULT 0, reserved_dept TEXT,
  UNIQUE (building_id, room_no)
);
CREATE TABLE course (                      -- 조교가 입력한 과목 (교수는 이미 배정됨). 분반은 결과에서 생김
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  code TEXT, name TEXT NOT NULL,
  professor_id INTEGER NOT NULL REFERENCES user(id),
  department TEXT, category TEXT, target_year TEXT,
  expected_enrollment INTEGER,                        -- 과목 전체 예상 수강 인원
  session_count INTEGER NOT NULL DEFAULT 1,           -- 주당 수업 횟수
  session_minutes INTEGER NOT NULL DEFAULT 75         -- 1회 길이(분)
);

-- ===== 1차: 희망 수집 =====
CREATE TABLE round (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  round_no INTEGER NOT NULL,                          -- 1 = 희망 수집, 2 = 대안 조율
  opened_at TEXT, deadline_at TEXT NOT NULL,
  status TEXT DEFAULT 'OPEN',                         -- OPEN / CLOSED / DONE
  UNIQUE (term_id, round_no)
);
CREATE TABLE round_invite (                           -- 이 차수에 응답해야 하는 교수
  round_id INTEGER REFERENCES round(id),
  professor_id INTEGER REFERENCES user(id),
  status TEXT DEFAULT 'PENDING',                      -- PENDING / RESPONDED / LATE
  responded_at TEXT,
  PRIMARY KEY (round_id, professor_id)
);
CREATE TABLE course_response (                        -- 교수가 과목별로 낸 응답
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  course_id INTEGER NOT NULL REFERENCES course(id),
  needs_lab INTEGER DEFAULT 0,                        -- 실습실 사용 여부
  language TEXT,                                      -- 강의 언어
  note TEXT,                                          -- 기타 요청사항 원문 (예: 분반 2개 원함)
  submitted_at TEXT,
  UNIQUE (round_id, course_id)
);
CREATE TABLE request_item (                           -- 기타 요청사항을 해석한 구조화 값
  id INTEGER PRIMARY KEY,
  response_id INTEGER NOT NULL REFERENCES course_response(id),
  type TEXT NOT NULL,                                 -- SECTION_COUNT / ROOM / OTHER ...
  value_int INTEGER, value_text TEXT,
  source TEXT DEFAULT 'NLP',                          -- FORM / NLP / TA
  status TEXT DEFAULT 'EXTRACTED',                    -- EXTRACTED / CONFIRMED / CORRECTED
  confirmed_by INTEGER REFERENCES user(id), confirmed_at TEXT
);
CREATE TABLE response_slot (                          -- 희망/불가 시간
  id INTEGER PRIMARY KEY,
  response_id INTEGER NOT NULL REFERENCES course_response(id),
  day TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('PREFER','AVOID'))
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
  started_at TEXT, finished_at TEXT,
  status TEXT,                                        -- OPTIMAL / FEASIBLE / INFEASIBLE
  objective_value REAL, time_limit_sec INTEGER,
  weights_json TEXT, note TEXT
);
CREATE TABLE timetable (                              -- 시간표 한 벌 = 한 버전
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  round_id INTEGER REFERENCES round(id),
  kind TEXT NOT NULL CHECK (kind IN ('DRAFT','TA_EDIT','FINAL')),
  solver_run_id INTEGER REFERENCES solver_run(id),
  parent_id INTEGER REFERENCES timetable(id),         -- 어느 버전을 고친 것인지
  created_by INTEGER REFERENCES user(id),             -- NULL이면 시스템
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE timetable_section (                      -- 이 버전에서 과목이 몇 개 분반으로 열리는지
  timetable_id INTEGER REFERENCES timetable(id),
  course_id INTEGER REFERENCES course(id),
  section_no INTEGER,                                 -- 1,2,3 (가,나,다는 화면에서 변환)
  planned_enrollment INTEGER,                         -- 이 분반에 배분한 인원
  PRIMARY KEY (timetable_id, course_id, section_no)
);
CREATE TABLE assignment (                             -- 분반별 시간·강의실
  timetable_id INTEGER, course_id INTEGER, section_no INTEGER, session_no INTEGER,
  day TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  room_id INTEGER NOT NULL REFERENCES room(id),
  PRIMARY KEY (timetable_id, course_id, section_no, session_no),
  FOREIGN KEY (timetable_id, course_id, section_no)
    REFERENCES timetable_section(timetable_id, course_id, section_no)
);

-- ===== 2차: 대안과 회신 =====
CREATE TABLE proposal (                               -- 바꿔야 하는 과목 1건
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  timetable_id INTEGER NOT NULL REFERENCES timetable(id),
  course_id INTEGER NOT NULL REFERENCES course(id),   -- 교수는 course.professor_id
  reason TEXT,                                        -- 왜 못 맞췄는지
  status TEXT DEFAULT 'WAITING'                       -- WAITING / ACCEPTED / REJECTED / TA_FIXED
);
CREATE TABLE proposal_option (                        -- 대안 (보통 3개)
  id INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES proposal(id),
  option_no INTEGER NOT NULL, source TEXT,            -- SOLVER / TA
  UNIQUE (proposal_id, option_no)
);
CREATE TABLE proposal_option_slot (                   -- 대안 하나의 시간·강의실
  option_id INTEGER REFERENCES proposal_option(id),
  section_no INTEGER, session_no INTEGER,
  day TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  room_id INTEGER NOT NULL REFERENCES room(id),
  PRIMARY KEY (option_id, section_no, session_no)
);
CREATE TABLE message (                                -- 안내·독촉·대안·회신 전부
  id INTEGER PRIMARY KEY,
  round_id INTEGER NOT NULL REFERENCES round(id),
  proposal_id INTEGER REFERENCES proposal(id),
  sender_id INTEGER REFERENCES user(id),              -- NULL이면 시스템
  receiver_id INTEGER NOT NULL REFERENCES user(id),
  kind TEXT NOT NULL,                                 -- NOTICE / REMINDER / ALTERNATIVE / REPLY
  channel TEXT,                                       -- APP / EMAIL / SMS
  body TEXT, sent_at TEXT, delivery_status TEXT
);
CREATE TABLE reply_interpretation (                   -- 교수 회신의 해석과 조교 확인
  message_id INTEGER PRIMARY KEY REFERENCES message(id),
  label TEXT,                                         -- ACCEPT / CONDITIONAL / REJECT / UNCLEAR
  chosen_option_id INTEGER REFERENCES proposal_option(id),
  extracted_json TEXT, model_name TEXT,
  ta_action TEXT,                                     -- CONFIRM / EDIT / KEEP
  ta_reason TEXT, ta_user_id INTEGER REFERENCES user(id), ta_at TEXT
);
