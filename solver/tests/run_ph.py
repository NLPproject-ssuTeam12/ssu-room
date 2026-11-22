from test_data import build   # 경로 설정은 test_data가 한다
import db
c = build()
print("시작 단계:", db.get_phase(c, 1))
print("→", db.set_phase(c, 1, "ROUND1", user_id=None)["label"])
for bad, kw in [("FINAL", {}), ("COLLECTING", {}), ("엉뚱", {})]:
    try: db.set_phase(c, 1, bad, **kw); print("막히지 않음!!", bad)
    except ValueError as e: print(f"막힘({bad}):", str(e)[:70])
print("→", db.set_phase(c, 1, "ROUND2")["label"], "→", db.set_phase(c, 1, "FINAL")["label"])
print("되돌리기(force):", db.set_phase(c, 1, "COLLECTING", force=True)["label"])
print("기록:", c.execute("select from_phase, to_phase from phase_log order by id").fetchall())
try: c.execute("UPDATE term SET phase='아무거나' WHERE id=1"); print("DB가 막지 않음!!")
except Exception as e: print("DB 직접 수정도 막힘:", type(e).__name__)

# 기타 요청: 교수가 쓰면 PENDING → 조교가 확인
c.execute("INSERT INTO user(id,role,name,password_hash) VALUES (900,'TA','조교','demo')")
rid = c.execute("select id from course_response order by id limit 1").fetchone()[0]
c.execute("INSERT INTO other_request(response_id, body) VALUES (?, '분반 2개 개설하고 싶고 교차 배정 부탁드립니다')", (rid,)); c.commit()
print("\n미확인 기타 요청:", db.pending_other_requests(c, 1))
oid = c.execute("select id from other_request").fetchone()[0]
# 조교가 읽고 구조화 요청을 입력 → 확인함
c.execute("INSERT INTO request_item(response_id, other_request_id, type, value_int, created_by) VALUES (?,?,?,?,?)", (rid, oid, 'SECTION_COUNT', 2, 900))
db.confirm_other_request(c, oid, 900, memo="분반 2개로 입력, 교차는 수동 처리")
print("확인 뒤 미확인:", db.pending_other_requests(c, 1))
print("기록:", c.execute("select status, confirmed_by, ta_memo from other_request").fetchall())
print("구조화 요청 출처:", c.execute("select type, value_int, source, other_request_id from request_item where other_request_id is not null").fetchall())
try: c.execute("INSERT INTO other_request(response_id, body) VALUES (?, '두번째')", (rid,)); print("같은 응답에 두 번째 글 허용됨!!")
except Exception as e: print("응답당 기타 요청은 하나만:", type(e).__name__)
try: c.execute("INSERT INTO request_item(response_id,type,source) VALUES (?,?,?)", (rid,'X','NLP')); print("NLP 허용됨!!")
except Exception as e: print("옛 값 'NLP' 거부:", type(e).__name__)
