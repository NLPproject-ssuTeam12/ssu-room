"""평가 스크립트가 도는지 확인 (키워드 방식만, 언어 모델은 부르지 않는다)."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))
import run_coord  # noqa: E402

FX = pathlib.Path(__file__).parent / "fixtures"


class EvalScript(unittest.TestCase):
    def test_reply_keyword(self):
        with tempfile.TemporaryDirectory() as d:
            s = run_coord.main(["reply", "--method", "keyword", "--replies", str(FX / "replies.csv"),
                                "--gold", str(FX / "gold_a.csv"), "--out", d, "--show", "0"])
            self.assertEqual(s["n"], 5)
            self.assertEqual(s["키워드로 넘어간 건수"], 0)
            self.assertEqual(len(list(pathlib.Path(d).glob("reply_keyword_*.csv"))), 1)

    def test_agree(self):
        r = run_coord.main(["agree", str(FX / "gold_a.csv"), str(FX / "gold_b.csv")])
        self.assertEqual(r["공통 문장"], 5)
        self.assertEqual(r["판정 일치율"], 0.6)
        self.assertEqual(r["조건 일치율"], 1.0)   # '늦은 오후'와 16:30-17:45는 같은 값

    def test_message_keyword(self):
        with tempfile.TemporaryDirectory() as d:
            rows = run_coord.main(["message", "--method", "keyword", "--out", d])
            self.assertTrue(all(r["recheck"] == "통과" for r in rows))

    def test_bad_label_stops(self):
        with self.assertRaises(SystemExit):
            run_coord.gold_row({"id": "x", "kind": "수락"})


if __name__ == "__main__":
    unittest.main()
