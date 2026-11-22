"""조율 NLP 테스트. backend 폴더에서 실행: python -m unittest discover -s tests -v

여기 문장은 동작 확인용이다. 평가 문장(eval/)이 아니다.
언어 모델 테스트는 실제로 부르지 않고 가짜 응답으로 확인한다. 실제 호출 확인은 GEMINI_API_KEY가 있을 때만 한다.
"""
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.nlp import coord  # noqa: E402
from app.nlp.coord import (alt_label, check_message, match_conditions, parse_reply,  # noqa: E402
                           write_message)
from app.nlp.coord_models import Alternative, Conditions, Meeting, MessageInput, ReplyParse  # noqa: E402
from app.nlp.llm import LLMUnavailable  # noqa: E402


def two(key, d1, d2, s, e, room):
    return Alternative(key=key, meetings=[Meeting(day=d1, start=s, end=e, room=room), Meeting(day=d2, start=s, end=e, room=room)])


# 시안 v4의 객체지향프로그래밍 02 대안 (월·수)
ALTS = [two("A", 0, 2, "16:30", "17:45", "정보관 305"),
        two("B", 0, 2, "12:00", "13:15", "정보관 305"),
        two("C", 0, 2, "18:00", "19:15", "정보관 305")]


def inp(**kw):
    base = dict(professor="나", course="객체지향프로그래밍 02", round=1, wish="월·수 15:00", alternatives=ALTS,
                blocker_prof="가", blocker_course="자료구조 01", hidden=["실습 조교 1명 배정을 부탁드립니다."])
    base.update(kw)
    return MessageInput(**base)


class Label(unittest.TestCase):
    def test_two_days(self):
        self.assertEqual(alt_label(ALTS[0]), "월·수 16:30~17:45 · 정보관 305")

    def test_long_class(self):
        a = Alternative(key="A", meetings=[Meeting(day=2, start="13:30", end="16:15", room="정보관 210")])
        self.assertEqual(alt_label(a), "수 13:30~16:15 연강 · 정보관 210")

    def test_different_times_and_rooms(self):
        a = Alternative(key="B", meetings=[Meeting(day=1, start="10:30", end="11:45", room="문화관 201"),
                                           Meeting(day=3, start="13:30", end="14:45", room="미래관 410")])
        self.assertEqual(alt_label(a), "화 10:30~11:45 / 목 13:30~14:45 · 화 문화관 201 / 목 미래관 410")


class WriteAndCheck(unittest.TestCase):
    def test_template_passes_check(self):
        for i in [inp(), inp(reveal=False), inp(round=2)]:
            m = write_message(i)
            self.assertEqual(check_message(m.text, i), [], m.text)

    def test_reveal_setting(self):
        self.assertIn("가 교수님의 자료구조 01 분반과 겹칩니다", write_message(inp()).text)
        t = write_message(inp(reveal=False)).text
        self.assertIn("다른 강의와 겹칩니다", t)
        self.assertNotIn("가 교수", t)

    def test_check_catches_problems(self):
        i = inp(reveal=False)
        good = write_message(i).text
        self.assertIn("연차·우선순위 이유를 썼음 ('연차')", check_message(good + "\n연차 순서에 따라 정했습니다.", i))
        self.assertIn("상대 교수의 사정(기타 요청)을 썼음", check_message(good + "\n실습 조교 1명 배정을 부탁드립니다.", i))
        self.assertIn("상대 교수 이름을 썼음 (학과 설정: 알리지 않음)", check_message(good + "\n가 교수님 강의와 겹칩니다.", i))
        self.assertIn("B안이 빠지거나 바뀜", check_message(good.replace("월·수 12:00~13:15", "월·수 12:00~13:30"), i))
        self.assertIn("본인 희망 시간이 빠지거나 바뀜", check_message(good.replace("월·수 15:00", "월수 오후"), i))


class KeywordReply(unittest.TestCase):
    def test_pick_with_end_condition(self):
        r = parse_reply("A나 B 괜찮아요. 수요일은 17시 전에 끝나야 해요.")
        self.assertEqual((r.kind, r.picks), ("조건부", ["A", "B"]))
        self.assertEqual([(e.day, e.time) for e in r.conditions.end_before], [(2, "17:00")])
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual((p.action, p.key), ("move", "B"))
        self.assertFalse(p.checks[0].ok)
        self.assertIn("17:45 종료", p.checks[0].why)

    def test_reject_with_days_and_slots(self):
        r = parse_reply("셋 다 어렵습니다. 화요일, 목요일 오전이면 됩니다.")
        self.assertEqual((r.kind, r.picks, r.conditions.days, r.conditions.slots), ("거절", [], [1, 3], ["09:00", "10:30"]))
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual(p.action, "next")
        self.assertIn("화·목요일, 오전", p.text)
        self.assertEqual(match_conditions(r, ALTS, round=3).action, "decide")

    def test_accept(self):
        r = parse_reply("A로 할게요.")
        self.assertEqual((r.kind, r.picks), ("수용", ["A"]))
        self.assertEqual(match_conditions(r, ALTS, round=2).key, "A")

    def test_screen_choice(self):
        self.assertEqual(parse_reply("", choice="B").picks, ["B"])
        r = parse_reply("", choice="none")
        self.assertEqual((r.kind, match_conditions(r, ALTS, round=1).action), ("거절", "next"))

    def test_late_afternoon_and_ordinal(self):
        r = parse_reply("세 번째 안은 어렵고 늦은 오후면 좋겠습니다")
        self.assertEqual(r.picks, ["C"])   # 키워드 방식의 한계: '어렵다'고 한 안을 고른 것으로 읽음
        r = parse_reply("모두 어렵고 늦은 오후면 좋겠습니다")
        self.assertEqual(r.conditions.slots, ["16:30"])   # 18:00은 저녁 (11/22)

    def test_day_letters_inside_words_are_ignored(self):
        r = parse_reply("지금 일정으로는 어렵습니다. 수업은 월수 저녁이면 됩니다")
        self.assertEqual(r.conditions.days, [0, 2])
        self.assertEqual(r.conditions.slots, ["18:00", "19:30"])

    def test_except_day(self):
        self.assertEqual(parse_reply("목요일만 아니면 됩니다").conditions.days, [0, 1, 2, 4])
        self.assertEqual(parse_reply("수요일은 어렵고 화, 목 오후면 됩니다").conditions.days, [1, 3])

    def test_unclear_needs_check(self):
        r = parse_reply("제안해주신 시간 괜찮습니다")   # 키워드 방식은 어느 안인지 모름 → 조교가 확인
        self.assertEqual(r.kind, "확인 필요")
        self.assertEqual(match_conditions(r, ALTS, round=1).action, "decide")

    def test_slots_check_long_class_needs_both_slots(self):
        long = [Alternative(key="A", meetings=[Meeting(day=1, start="13:30", end="16:15", room="정보과학관 21301")]),
                Alternative(key="B", meetings=[Meeting(day=1, start="15:00", end="17:45", room="정보과학관 21301")])]
        r = ReplyParse(kind="조건부", picks=["B", "A"], conditions=Conditions(slots=["13:30", "15:00"]))
        p = match_conditions(r, long, round=1)
        self.assertEqual((p.action, p.key), ("move", "A"))
        self.assertIn("가능 교시", p.checks[0].why)
        self.assertFalse(p.checks[0].ok)

    def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError):
            Conditions(slots=["14:00"])

    def test_unavailable_pick(self):
        r = parse_reply("A로 할게요.")
        p = match_conditions(r, ALTS, round=1, unavailable=["A"])
        self.assertEqual(p.action, "next")
        self.assertEqual(p.checks[0].why, "그사이 다른 강의가 들어감")


class LLMPath(unittest.TestCase):
    def test_no_key_falls_back(self):
        with mock.patch.object(coord, "generate_json", side_effect=LLMUnavailable("키 없음")):
            r = parse_reply("A로 할게요.", alternatives=ALTS, method="llm")
            self.assertEqual((r.method, r.fallback, r.picks), ("keyword", True, ["A"]))
            m = write_message(inp(), method="llm")
            self.assertEqual((m.method, m.fallback), ("keyword", True))

    def test_llm_reply_is_checked(self):
        fake = coord._ReplyLLM(kind="조건부", picks=["B", "C"], days=[], slots=[],
                               end_before=[{"day": 2, "time": "17:00"}])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("제안해주신 B 괜찮은데 수요일은 5시 전에 끝나야 해요", alternatives=ALTS, method="llm")
        self.assertEqual((r.method, r.kind, r.picks), ("llm", "조건부", ["B", "C"]))
        self.assertEqual(r.conditions.end_before[0].time, "17:00")

    def test_llm_reply_contradiction(self):
        fake = coord._ReplyLLM(kind="수용", picks=[], days=[], slots=[], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            self.assertEqual(parse_reply("네", alternatives=ALTS, method="llm").kind, "확인 필요")

    def test_llm_days_kept_when_days_written_together(self):
        # '화목'처럼 붙여 쓴 요일은 지킨다. 요일이 없는 답장에서 만든 요일만 버린다
        fake = coord._ReplyLLM(kind="거절", picks=[], days=[1, 3], slots=["15:00"], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            self.assertEqual(parse_reply("다 안됩니다. 화목 15시 부탁드려요", alternatives=ALTS, method="llm").conditions.days, [1, 3])
            self.assertEqual(parse_reply("다 안됩니다. 3시로 부탁드려요", alternatives=ALTS, method="llm").conditions.days, [])

    def test_llm_note_keeps_conditional(self):
        # 확인할 요청(계단식 강의실 등)만 있어도 조건부로 남기고, 처리안 문구에 요청을 붙인다
        fake = coord._ReplyLLM(kind="조건부", picks=["A"], days=[], slots=[], end_before=[], note="계단식 강의실")
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("A로 할게요. 계단식 강의실이면요", alternatives=ALTS, method="llm")
        self.assertEqual((r.kind, r.note), ("조건부", "계단식 강의실"))
        self.assertIn("계단식 강의실", match_conditions(r, ALTS, round=1).text)

    def test_room_request_already_met_is_accept(self):
        # "강의실 그대로라면요": 고른 안이 이미 그 방이면 할 일이 없으니 수용 (모델이 note에도 적었으면 같이 지운다)
        for note in ["", "정보관 305 유지"]:
            fake = coord._ReplyLLM(kind="조건부", picks=["A"], days=[], slots=[], end_before=[], rooms=["305"], note=note)
            with mock.patch.object(coord, "generate_json", return_value=fake):
                r = parse_reply("A로 할게요, 강의실이 305 그대로라면요", alternatives=ALTS, method="llm")
            self.assertEqual((r.kind, r.note), ("수용", ""))

    def test_room_request_not_met_is_conditional(self):
        # 화요일만 다른 방인 안에서 "둘 다 306으로" → 조교가 바꿔야 하니 조건부, 요청을 note에 남긴다
        mixed = [Alternative(key="A", meetings=[Meeting(day=1, start="13:30", end="14:45", room="정보관 305"),
                                                Meeting(day=3, start="13:30", end="14:45", room="정보관 306")])]
        fake = coord._ReplyLLM(kind="조건부", picks=["A"], days=[], slots=[], end_before=[], rooms=["306"])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("A로 할게요. 둘 다 306으로 맞춰 주세요", alternatives=mixed, method="llm")
        self.assertEqual(r.kind, "조건부")
        self.assertIn("306", r.note)

    def test_few_minutes_early_end_is_professor_choice(self):
        # A는 17:45 종료. "17:30에 끝낼 수 있으면"(15분 이내)은 재량 → 수용. "16:00 전"(105분)은 조건으로 남아 A가 어긋난다
        for t, want in [("17:30", ("수용", [])), ("16:00", ("조건부", ["16:00"]))]:
            fake = coord._ReplyLLM(kind="조건부", picks=["A"], days=[], slots=[], end_before=[{"day": 2, "time": t}])
            with mock.patch.object(coord, "generate_json", return_value=fake):
                r = parse_reply("A로 할게요. 수요일은 일찍 끝나면 좋겠어요", alternatives=ALTS, method="llm")
            self.assertEqual((r.kind, [e.time for e in r.conditions.end_before]), want)

    def test_llm_reply_bad_time_falls_back(self):
        fake = coord._ReplyLLM(kind="거절", picks=[], days=[1], slots=["오후"], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("화요일 오후면 됩니다", alternatives=ALTS, method="llm")
        self.assertTrue(r.fallback)

    def test_llm_message_that_breaks_rules_is_not_sent(self):
        i = inp()
        bad = write_message(i).text.replace("A  월·수 16:30~17:45 · 정보관 305", "A  월·수 오후 늦게 · 정보관 305")
        with mock.patch.object(coord, "generate_json", return_value=coord._MessageLLM(text=bad)):
            m = write_message(i, method="llm")
        self.assertEqual((m.method, m.fallback), ("keyword", True))
        self.assertIn("A안이 빠지거나 바뀜", m.problems)
        self.assertEqual(check_message(m.text, i), [])

    def test_llm_message_ok(self):
        i = inp()
        good = write_message(i).text.replace("안녕하세요. 학과사무실입니다.", "안녕하세요. 학과사무실 조교입니다.")
        with mock.patch.object(coord, "generate_json", return_value=coord._MessageLLM(text=good)):
            m = write_message(i, method="llm")
        self.assertEqual((m.method, m.fallback), ("llm", False))


@unittest.skipUnless(os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY가 없어 실제 호출은 건너뜀")
class LiveLLM(unittest.TestCase):
    def test_parse_reply_live(self):
        r = parse_reply("두 번째 안으로 부탁드립니다.", alternatives=ALTS, message=write_message(inp()).text, method="llm")
        self.assertFalse(r.fallback)
        self.assertEqual(r.picks, ["B"])


if __name__ == "__main__":
    unittest.main()
