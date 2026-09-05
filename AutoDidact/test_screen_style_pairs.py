import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import screen_style_pairs as screen
from screen_style_pairs import validate


class JudgmentTests(unittest.TestCase):
    def test_accept(self):
        value = {"verdict": "accept", "style_present": True, "reason": "All claims preserved."}
        self.assertEqual(validate(value), value)

    def test_missing_or_extra_fields(self):
        for value in ({}, [], {"verdict": "accept", "style_present": True, "reason": "ok", "extra": 1}):
            with self.assertRaises(ValueError):
                validate(value)

    def test_non_boolean_style(self):
        for style in ("true", 1, None):
            with self.assertRaises(ValueError):
                validate({"verdict": "accept", "style_present": style, "reason": "ok"})

    def test_invalid_verdict_or_reason(self):
        for verdict, reason in (("yes", "ok"), ("accept", " "), ("reject", None)):
            with self.assertRaises(ValueError):
                validate({"verdict": verdict, "style_present": True, "reason": reason})

    def test_calibration_resume_and_complete_export_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            candidates = directory / "candidates"
            candidates.mkdir()
            for split, rows in [("train", [{"id": "one", "input": "good", "output": "good <3"},
                                           {"id": "two", "input": "bad", "output": "changed"}]),
                                ("validation", [{"id": "three", "input": "plain", "output": "plain"}])]:
                with (candidates / f"{split}.candidates.jsonl").open("w") as out:
                    for row in rows:
                        screen.write_row(out, row)
            labels = {(a, b): label for a, b, label in screen.CALIBRATION}
            calls = []

            def fake(url, payload, **kwargs):
                pair = json.loads(payload["messages"][-1]["content"])
                source, rewrite = pair["SOURCE"], pair["REWRITE"]
                calls.append(source)
                judgment = {"verdict": labels.get((source, rewrite), "reject" if source == "bad" else "accept"),
                            "style_present": source != "plain", "reason": "test judgment"}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(judgment)}}]}

            def run(phase, *extra):
                with patch("sys.argv", ["screen", phase, "--directory", tmp, *extra]):
                    screen.main()

            with patch.object(screen, "get_json", side_effect=fake), patch("sys.stdout", new_callable=io.StringIO):
                run("calibrate")
                run("screen", "--limit", "1")
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    run("export")
                run("screen")
                run("screen")
                self.assertEqual(len(calls), len(screen.CALIBRATION) + 3)
                run("export")
                accepted = list(screen.read_rows(directory / "accepted" / "train.jsonl"))
                self.assertEqual([r["id"] for r in accepted], ["one"])
                self.assertEqual(list(screen.read_rows(directory / "accepted" / "validation.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
