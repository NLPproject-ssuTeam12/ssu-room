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

    def test_current_line(self):
        # 희망 밖에라도 놓인 분반: 지금 자리를 알리는 한 줄 (11/25). 없으면 그 줄도 없다
        i = inp(current="화·목 10:30~11:45 · 정보관 305")
        t = write_message(i).text
        self.assertIn("지금은 화·목 10:30~11:45 · 정보관 305에 배정되어 있습니다. 그대로 괜찮으시면 '지금 자리 그대로'를 골라 주세요.", t)
        self.assertEqual(check_message(t, i), [])
        self.assertNotIn("지금 자리 그대로", write_message(inp()).text)
        self.assertIn("지금 배정된 자리가 빠지거나 바뀜", check_message(write_message(inp()).text, i))

    def test_reveal_setting(self):
        self.assertIn("가 교수님의 자료구조 01 분반과 겹칩니다", write_message(inp()).text)
        t = write_message(inp(reveal=False)).text
        self.assertIn("다른 강의와 겹칩니다", t)
        self.assertNotIn("가 교수", t)

    def test_unknown_blocker_does_not_say_overlap(self):
        # 서버가 겹친 상대를 못 찾으면 '겹친다'고 단정하지 않는다 (밀린 이유가 실습실 부족·학년 규칙일 수도 있음)
        i = inp(blocker_prof=None, blocker_course=None)
        t = write_message(i).text
        self.assertIn("희망하신 시간(월·수 15:00)에 배정하지 못해 아래 대안을 드립니다.", t)
        self.assertNotIn("겹", t)
        self.assertEqual(check_message(t, i), [])
        # 언어 모델이 '겹친다'를 지어내면 막는다. 상대를 아는 1차는 그대로 허용
        self.assertIn("입력에 없는 이유를 덧붙임 ('겹')", coord.check_body("희망하신 월·수 15:00이 다른 강의와 겹칩니다.", i))
        self.assertEqual(coord.check_body("희망하신 월·수 15:00에 배정하지 못해 아래 대안을 마련했습니다.", i), [])
        self.assertEqual(coord.check_body("희망하신 월·수 15:00이 다른 강의와 겹칩니다.", inp(reveal=False)), [])

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
        self.assertEqual((r.kind, r.picks, r.conditions.day_slots), ("거절", [], {1: ["09:00", "10:30"], 3: ["09:00", "10:30"]}))
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual(p.action, "next")
        self.assertIn("화·목 오전", p.text)
        self.assertEqual(match_conditions(r, ALTS, round=3).action, "decide")

    def test_accept(self):
        r = parse_reply("A로 할게요.")
        self.assertEqual((r.kind, r.picks), ("수용", ["A"]))
        self.assertEqual(match_conditions(r, ALTS, round=2).key, "A")

    def test_screen_choice(self):
        self.assertEqual(parse_reply("", choice="B").picks, ["B"])
        r = parse_reply("", choice="none")
        # 조건 없이 거절 → 다음 차수에 넘길 조건이 없어 조교가 교수와 따로 정한다 (11/25 #17)
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual((r.kind, p.action), ("거절", "decide"))
        self.assertIn("[따로 연락]", p.text)

    def test_choices_buttons(self):
        # 새 화면 (#17): A·B·C·기타 중 하나 이상, 여러 개 가능
        self.assertEqual(parse_reply("", choices=["B", "C"]).picks, ["B", "C"])
        r = parse_reply("수요일은 5시 전에 끝나야 해요", choices=["B", "ETC"])
        self.assertEqual((r.kind, r.picks, [e.time for e in r.conditions.end_before]), ("조건부", ["B"], ["17:00"]))
        only_etc = parse_reply("화요일 오전이면 됩니다", choices=["ETC"])   # 기타만 = A·B·C는 안 고름
        self.assertEqual((only_etc.kind, only_etc.picks, list(only_etc.conditions.day_slots)), ("거절", [], [1]))
        self.assertEqual(match_conditions(only_etc, ALTS, round=1).action, "next")
        self.assertEqual(parse_reply("", choice="A", choices=["C"]).picks, ["C"])   # choices가 있으면 choices를 쓴다
        with self.assertRaises(ValueError):
            parse_reply("", choices=["D"])

    def test_order_stated_in_text(self):
        # 글로 순서를 밝히면 ordered (엔진 pick_best respect_order). 버튼 여러 개면 글 순서를 따른다
        r = parse_reply("C가 좋고 안 되면 B로 해 주세요", choices=["B", "C"])
        self.assertEqual((r.picks, r.ordered), (["C", "B"], True))
        r = parse_reply("A나 B 괜찮아요", choices=["A", "B"])
        self.assertEqual((r.picks, r.ordered), (["A", "B"], False))
        self.assertFalse(parse_reply("B가 제일 좋아요", choice="B").ordered)   # 하나만 고르면 순서 없음

    def test_keep(self):
        # '지금 자리 그대로' 버튼 → 처리안 keep ([현재대로 유지]) (11/25)
        r = parse_reply("", choices=["KEEP"])
        self.assertEqual((r.kind, r.picks, r.keep), ("수용", [], True))
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual((p.action, p.key), ("keep", None))
        self.assertIn("[현재대로 유지]", p.text)
        # 글로 "지금 그대로 괜찮아요"는 지금 자리가 있는 분반(can_keep)일 때만 keep
        self.assertTrue(parse_reply("지금 그대로 괜찮아요", choices=["ETC"], can_keep=True).keep)
        self.assertFalse(parse_reply("지금 그대로 괜찮아요", choices=["ETC"]).keep)
        # 안을 고르면 글의 "그대로"는 keep이 아니다 ("B로 하고 방은 지금 그대로 해 주세요")
        self.assertFalse(parse_reply("B로 하고 방은 지금 그대로 해 주세요", choices=["B"], can_keep=True).keep)

    def test_late_afternoon_and_ordinal(self):
        r = parse_reply("세 번째 안은 어렵고 늦은 오후면 좋겠습니다")
        self.assertEqual(r.picks, ["C"])   # 키워드 방식의 한계: '어렵다'고 한 안을 고른 것으로 읽음
        r = parse_reply("모두 어렵고 늦은 오후면 좋겠습니다")
        self.assertEqual(r.conditions.day_slots, {d: ["16:30"] for d in range(5)})   # 18:00은 저녁 (11/22). 요일 없으면 다섯 요일

    def test_day_letters_inside_words_are_ignored(self):
        r = parse_reply("지금 일정으로는 어렵습니다. 수업은 월수 저녁이면 됩니다")
        self.assertEqual(r.conditions.day_slots, {0: ["18:00", "19:30"], 2: ["18:00", "19:30"]})

    def test_except_day(self):
        self.assertEqual(parse_reply("목요일만 아니면 됩니다").conditions.day_slots, {0: [], 1: [], 2: [], 4: []})
        self.assertEqual(list(parse_reply("수요일은 어렵고 화, 목 오후면 됩니다").conditions.day_slots), [1, 3])

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

    def test_day_slots_each_day_its_own_slots(self):
        # 화 오전 / 목 오후 (11/22 요일별 교시): 요일마다 다른 시간을 가린다
        k = Conditions(day_slots={1: ["09:00", "10:30"], 3: ["13:30", "15:00", "16:30"]})
        alts = [Alternative(key="A", meetings=[Meeting(day=1, start="13:30", end="14:45", room="305"),
                                               Meeting(day=3, start="13:30", end="14:45", room="305")]),
                Alternative(key="B", meetings=[Meeting(day=1, start="10:30", end="11:45", room="305"),
                                               Meeting(day=3, start="15:00", end="16:15", room="305")])]
        p = match_conditions(ReplyParse(kind="조건부", picks=["A", "B"], conditions=k), alts, round=1)
        self.assertEqual((p.action, p.key), ("move", "B"))
        self.assertIn("화요일 가능 교시", p.checks[0].why)
        self.assertEqual(coord.cond_label(k), "화 오전, 목 오후")

    def test_end_before_label_groups_days(self):
        # 같은 시각이면 요일을 묶는다. 다섯 요일 모두면 "매일" (진짜 솔버 흐름 실험 11/23에서 다섯 줄로 길게 나옴)
        every = Conditions(end_before=[{"day": d, "time": "15:00"} for d in range(5)])
        self.assertEqual(coord.cond_label(every), "매일 15:00 전 종료")
        two = Conditions(end_before=[{"day": 0, "time": "17:00"}, {"day": 2, "time": "17:00"}, {"day": 4, "time": "12:00"}])
        self.assertEqual(coord.cond_label(two), "월·수요일 17:00 전 종료, 금요일 12:00 전 종료")
        self.assertEqual(coord.cond_label(Conditions(end_before=[{"day": 2, "time": "17:00"}])), "수요일 17:00 전 종료")

    def test_day_slots_one_day_means_that_day_included(self):
        # 요일 하나("목요일 오후면"): 목요일 수업만 오후면 되고 다른 하루는 자유
        a = Alternative(key="A", meetings=[Meeting(day=1, start="09:00", end="10:15", room="305"),
                                           Meeting(day=3, start="13:30", end="14:45", room="305")])
        self.assertTrue(coord._fits(a, Conditions(day_slots={3: ["13:30", "15:00", "16:30"]}))[0])
        self.assertFalse(coord._fits(ALTS[1], Conditions(day_slots={2: ["13:30", "15:00", "16:30"]}))[0])   # B는 수 12:00

    def test_old_shape_still_accepted(self):
        # 옛 모양 days·slots로 들어와도 요일 × 교시로 바꾸고, 옛 코드용 days·slots도 읽힌다
        k = Conditions(days=[1, 3], slots=["13:30"])
        self.assertEqual(k.day_slots, {1: ["13:30"], 3: ["13:30"]})
        self.assertEqual((k.days, k.slots), ([1, 3], ["13:30"]))
        k2 = Conditions(slots=["16:30", "13:30", "13:30"])
        self.assertEqual((k2.days, k2.slots), ([], ["13:30", "16:30"]))
        self.assertEqual(Conditions(days=[2]).slots, [])
        self.assertEqual(set(Conditions(days=[2]).model_dump()), {"day_slots", "end_before"})

    def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError):
            Conditions(slots=["14:00"])

    def test_unavailable_pick(self):
        r = parse_reply("A로 할게요.")
        p = match_conditions(r, ALTS, round=1, unavailable=["A"])
        # 조건 없이 고른 안을 못 쓰게 됨 → 다음 차수에 넘길 조건이 없으니 조교가 정한다 (빈 조건 next는 DB가 막음)
        self.assertEqual(p.action, "decide")
        self.assertIn("[따로 연락]", p.text)
        self.assertEqual(p.checks[0].why, "그사이 다른 강의가 들어감")


class LLMPath(unittest.TestCase):
    def test_no_key_falls_back(self):
        with mock.patch.object(coord, "generate_json", side_effect=LLMUnavailable("키 없음")):
            r = parse_reply("A로 할게요.", alternatives=ALTS, method="llm")
            self.assertEqual((r.method, r.fallback, r.fallback_reason), ("keyword", True, "키 없음"))
            m = write_message(inp(), method="llm")
            self.assertEqual((m.method, m.fallback), ("keyword", True))

    def test_fallback_accept_becomes_check(self):
        # 모델이 막혀 키워드로 넘어가면, 글만 보고 나온 수용·조건부는 확인 필요로 낮춘다 (거절을 수용으로 읽는 위험 오류 막기)
        with mock.patch.object(coord, "generate_json", side_effect=LLMUnavailable("호출 실패: ServerError: 503 UNAVAILABLE")):
            r = parse_reply("C는 괜찮은데 B도 될 것 같고 다음 주에 말씀드릴게요", alternatives=ALTS, method="llm")
            self.assertEqual((r.kind, r.picks, r.fallback_reason), ("확인 필요", [], "503 과부하"))
            self.assertIn("키워드 추정", r.note)
            p = match_conditions(r, ALTS, round=1)
            self.assertEqual(p.action, "decide")
            self.assertIn("AI 해석 실패", p.text)
            # 화면 버튼을 눌렀으면 글 해석이 필요 없으니 그대로 수용
            b = parse_reply("", choice="B", alternatives=ALTS, method="llm")
            self.assertEqual((b.kind, b.picks, b.fallback), ("수용", ["B"], True))
            # 거절은 원래 안전한 방향이라 그대로
            self.assertEqual(parse_reply("셋 다 어렵습니다", alternatives=ALTS, method="llm").kind, "거절")

    def test_llm_reply_is_checked(self):
        fake = coord._ReplyLLM(kind="조건부", picks=["B", "C"], end_before=[{"day": 2, "time": "17:00"}])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("제안해주신 B 괜찮은데 수요일은 5시 전에 끝나야 해요", alternatives=ALTS, method="llm")
        self.assertEqual((r.method, r.kind, r.picks), ("llm", "조건부", ["B", "C"]))
        self.assertEqual(r.conditions.end_before[0].time, "17:00")

    def test_llm_reply_contradiction(self):
        fake = coord._ReplyLLM(kind="수용", picks=[], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            self.assertEqual(parse_reply("네", alternatives=ALTS, method="llm").kind, "확인 필요")

    def test_llm_unsure_but_button_pressed(self):
        # 버튼으로 안을 골랐으면 모델이 '확인 필요'라고 해도 그 안을 받아들인 것. 모델이 거절이라고 하면 모순이라 확인 필요
        unsure = coord._ReplyLLM(kind="확인 필요", picks=[], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=unsure):
            r = parse_reply("넵 확인했습니다 감사합니다", choice="C", alternatives=ALTS, method="llm")
        self.assertEqual((r.kind, r.picks), ("수용", ["C"]))
        reject = coord._ReplyLLM(kind="거절", picks=[], end_before=[])
        with mock.patch.object(coord, "generate_json", return_value=reject):
            self.assertEqual(parse_reply("사실 다 안 돼요", choice="A", alternatives=ALTS, method="llm").kind, "확인 필요")

    def test_llm_choices_and_order(self):
        # 버튼 여러 개 + 글로 순서: 모델의 ordered를 받아 글 순서로. 순서 없으면 버튼 순서
        fake = coord._ReplyLLM(kind="수용", picks=["C", "B"], ordered=True)
        with mock.patch.object(coord, "generate_json", return_value=fake) as g:
            r = parse_reply("C가 좋고 안 되면 B요", choices=["B", "C"], alternatives=ALTS, method="llm")
        self.assertEqual((r.picks, r.ordered), (["C", "B"], True))
        self.assertIn("B안, C안 (여러 개 누름", g.call_args[0][0])   # 프롬프트에 누른 값이 들어감
        fake = coord._ReplyLLM(kind="수용", picks=["B", "C"], ordered=False)
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("둘 다 괜찮아요", choices=["C", "B"], alternatives=ALTS, method="llm")
        self.assertEqual((r.picks, r.ordered), (["C", "B"], False))

    def test_llm_etc_request_only_goes_to_ta(self):
        # 기타만 고르고 시간 얘기 없이 요청만 → 조교가 정함(따로 연락), 요청은 처리안 문구에 같이 보여 준다
        fake = coord._ReplyLLM(kind="확인 필요", picks=[], note="실습 조교 배치")
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("실습 조교 한 명 부탁드려요", choices=["ETC"], alternatives=ALTS, method="llm")
        p = match_conditions(r, ALTS, round=1)
        self.assertEqual((r.kind, r.note, p.action), ("거절", "실습 조교 배치", "decide"))
        self.assertIn("[따로 연락]", p.text)
        self.assertIn("실습 조교 배치", p.text)

    def test_llm_keep(self):
        # 모델의 keep은 지금 자리가 있는 분반에서만 받는다. 버튼을 누르면 모델 답과 상관없이 keep
        fake = coord._ReplyLLM(kind="수용", picks=[], keep=True)
        with mock.patch.object(coord, "generate_json", return_value=fake) as g:
            r = parse_reply("지금 시간 그대로 유지해 주세요", choices=["ETC"], alternatives=ALTS, method="llm", can_keep=True)
        self.assertEqual((r.kind, r.keep, match_conditions(r, ALTS, round=1).action), ("수용", True, "keep"))
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("지금 시간 그대로 유지해 주세요", choices=["ETC"], alternatives=ALTS, method="llm")
        self.assertFalse(r.keep)
        with mock.patch.object(coord, "generate_json", return_value=coord._ReplyLLM(kind="거절", picks=[])) as g:
            r = parse_reply("", choices=["KEEP"], alternatives=ALTS, method="llm")
        self.assertEqual((r.kind, r.keep), ("수용", True))
        self.assertIn("지금 자리 그대로", g.call_args[0][0])

    def test_llm_days_kept_when_days_written_together(self):
        # '화목'처럼 붙여 쓴 요일은 지킨다. 요일이 없는 답장에서 만든 요일만 버린다
        fake = coord._ReplyLLM(kind="거절", picks=[], day_slots=[{"day": 1, "slots": ["15:00"]}, {"day": 3, "slots": ["15:00"]}])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            self.assertEqual(parse_reply("다 안됩니다. 화목 15시 부탁드려요", alternatives=ALTS, method="llm").conditions.day_slots, {1: ["15:00"], 3: ["15:00"]})
            self.assertEqual(parse_reply("다 안됩니다. 3시로 부탁드려요", alternatives=ALTS, method="llm").conditions.day_slots,
                             {d: ["15:00"] for d in range(5)})   # 요일은 지어낸 것 → 교시만 다섯 요일에

    def test_llm_day_slots_kept_per_day(self):
        fake = coord._ReplyLLM(kind="거절", picks=[], day_slots=[{"day": 1, "slots": ["09:00", "10:30"]},
                                                              {"day": 3, "slots": ["13:30", "15:00"]}])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("다 어려워요. 화요일은 오전, 목요일은 1시반이나 3시", alternatives=ALTS, method="llm")
        self.assertEqual(r.conditions.day_slots, {1: ["09:00", "10:30"], 3: ["13:30", "15:00"]})
        self.assertFalse(r.fallback)

    def test_llm_note_keeps_conditional(self):
        # 확인할 요청(계단식 강의실 등)만 있어도 조건부로 남기고, 처리안 문구에 요청을 붙인다
        fake = coord._ReplyLLM(kind="조건부", picks=["A"], end_before=[], note="계단식 강의실")
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("A로 할게요. 계단식 강의실이면요", alternatives=ALTS, method="llm")
        self.assertEqual((r.kind, r.note), ("조건부", "계단식 강의실"))
        self.assertIn("계단식 강의실", match_conditions(r, ALTS, round=1).text)

    def test_room_request_already_met_is_accept(self):
        # "강의실 그대로라면요": 고른 안이 이미 그 방이면 할 일이 없으니 수용 (모델이 note에도 적었으면 같이 지운다)
        for note in ["", "정보관 305 유지"]:
            fake = coord._ReplyLLM(kind="조건부", picks=["A"], end_before=[], rooms=["305"], note=note)
            with mock.patch.object(coord, "generate_json", return_value=fake):
                r = parse_reply("A로 할게요, 강의실이 305 그대로라면요", alternatives=ALTS, method="llm")
            self.assertEqual((r.kind, r.note), ("수용", ""))

    def test_room_request_not_met_is_conditional(self):
        # 화요일만 다른 방인 안에서 "둘 다 306으로" → 조교가 바꿔야 하니 조건부, 요청을 note에 남긴다
        mixed = [Alternative(key="A", meetings=[Meeting(day=1, start="13:30", end="14:45", room="정보관 305"),
                                                Meeting(day=3, start="13:30", end="14:45", room="정보관 306")])]
        fake = coord._ReplyLLM(kind="조건부", picks=["A"], end_before=[], rooms=["306"])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("A로 할게요. 둘 다 306으로 맞춰 주세요", alternatives=mixed, method="llm")
        self.assertEqual(r.kind, "조건부")
        self.assertIn("306", r.note)
        # [수정]은 A·B·C만 고르므로 강의실만 바꾸는 길(AI 도우미)을 처리안 문구에 알려 준다
        p = match_conditions(r, mixed, round=1)
        self.assertEqual(p.action, "move")
        self.assertIn("AI 도우미", p.text)
        # 강의실과 상관없는 요청에는 붙이지 않는다
        other = coord._ReplyLLM(kind="조건부", picks=["A"], end_before=[], note="목요일만 10:30으로 조정 희망")
        with mock.patch.object(coord, "generate_json", return_value=other):
            r2 = parse_reply("A로 할게요. 목요일만 10시 반이면 좋겠어요", alternatives=mixed, method="llm")
        self.assertNotIn("AI 도우미", match_conditions(r2, mixed, round=1).text)

    def test_few_minutes_early_end_is_professor_choice(self):
        # A는 17:45 종료. "17:30에 끝낼 수 있으면"(15분 이내)은 재량 → 수용. "16:00 전"(105분)은 조건으로 남아 A가 어긋난다
        for t, want in [("17:30", ("수용", [])), ("16:00", ("조건부", ["16:00"]))]:
            fake = coord._ReplyLLM(kind="조건부", picks=["A"], end_before=[{"day": 2, "time": t}])
            with mock.patch.object(coord, "generate_json", return_value=fake):
                r = parse_reply("A로 할게요. 수요일은 일찍 끝나면 좋겠어요", alternatives=ALTS, method="llm")
            self.assertEqual((r.kind, [e.time for e in r.conditions.end_before]), want)

    def test_llm_reply_bad_time_falls_back(self):
        fake = coord._ReplyLLM(kind="거절", picks=[], day_slots=[{"day": 1, "slots": ["오후"]}])
        with mock.patch.object(coord, "generate_json", return_value=fake):
            r = parse_reply("화요일 오후면 됩니다", alternatives=ALTS, method="llm")
        self.assertTrue(r.fallback)

    def _llm(self, body, i):
        with mock.patch.object(coord, "generate_json", return_value=coord._MessageLLM(text=body)):
            return write_message(i, method="llm")

    def test_llm_message_ok(self):
        # 언어 모델은 설명 문단만 쓰고, 인사·제목 줄·대안·마지막 문장은 틀이 붙인다
        i = inp()
        m = self._llm("교수님께서 희망하신 월·수 15:00이 가 교수님의 자료구조 01 분반과 겹쳐\n아래 대안 가운데 가능한 안을 여쭙습니다.", i)
        self.assertEqual((m.method, m.fallback), ("llm", False))
        lines = m.text.splitlines()
        self.assertEqual(lines[1], "2027-1학기 객체지향프로그래밍 02 분반 시간표 1차 조율 안내드립니다.")
        self.assertEqual(lines[3], "교수님께서 희망하신 월·수 15:00이 가 교수님의 자료구조 01 분반과 겹쳐 아래 대안 가운데 가능한 안을 여쭙습니다.")
        self.assertEqual(check_message(m.text, i), [])

    def test_llm_message_that_breaks_rules_is_not_sent(self):
        # 사람 평가(11/23)에서 나온 모양: 이유 지어내기, 대안 잘못 설명, 입력에 없는 시각, 희망 빠짐
        i2 = inp(round=2, prev_conditions=Conditions(day_slots={d: ["13:30", "15:00", "16:30"] for d in range(5)}))
        cases = [
            (i2, "처음 희망하신 월·수 15:00 시간대에 다른 과목이 배정되어, 지난 회신의 조건(오후)을 반영했습니다.", "입력에 없는 이유를 덧붙임 ('배정되')"),
            (i2, "조건(오후)을 반영했습니다. 처음 희망하신 월·수 15:00은 다른 강의와 겹쳤습니다.", "입력에 없는 이유를 덧붙임 ('겹')"),
            (i2, "조건(오후)을 반영했고, 처음 희망하신 월·수 15:00도 대안 C로 포함했습니다.", "설명 문단에서 대안 A·B·C를 따로 설명함"),
            (inp(), "희망하신 월·수 15:00이 겹쳐 월·수 16:30 등을 마련했습니다.", "설명 문단에 입력에 없는 시각을 씀 (16:30)"),
            (inp(), "희망하신 시간이 가 교수님 강의와 겹칩니다.", "본인 희망 시간이 빠지거나 바뀜"),
            (inp(), "  ", "설명 문단이 비었음"),
            # 2차 채점(11/23) g08: 프롬프트 예시의 자리표시를 그대로 베낌
            (inp(), "희망하신 월·수 15:00이 (상대 교수) 교수님의 자료구조 01 분반과 겹칩니다.", "설명 문단에 자리표시가 남음"),
            (inp(), "희망하신 월·수 15:00이 다른 강의와 겹칩니다.", "1차인데 겹친 상대 교수·강의 이름이 빠지거나 바뀜"),
        ]
        for i, body, why in cases:
            m = self._llm(body, i)
            self.assertEqual((m.method, m.fallback), ("keyword", True), body)
            self.assertIn(why, m.problems)
            self.assertEqual(check_message(m.text, i), [])

    def test_body_check_allows_course_letters_and_round1_overlap(self):
        i = inp(course="C프로그래밍 01", blocker_course="AI개론 02")
        self.assertEqual(coord.check_body("희망하신 월·수 15:00이 가 교수님의 AI개론 02 분반과 겹칩니다.", i), [])
        i2 = inp(round=2, prev_conditions=Conditions(end_before=[{"day": 2, "time": "17:00"}]))
        self.assertEqual(coord.check_body("지난 회신에서 주신 조건(수요일 17:00 전 종료)을 반영했습니다. 처음 희망하신 시간은 월·수 15:00입니다.", i2), [])


@unittest.skipUnless(os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY가 없어 실제 호출은 건너뜀")
class LiveLLM(unittest.TestCase):
    def test_parse_reply_live(self):
        r = parse_reply("두 번째 안으로 부탁드립니다.", alternatives=ALTS, message=write_message(inp()).text, method="llm")
        self.assertFalse(r.fallback)
        self.assertEqual(r.picks, ["B"])


if __name__ == "__main__":
    unittest.main()
