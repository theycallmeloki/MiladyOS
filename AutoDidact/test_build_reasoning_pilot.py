import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_reasoning_pilot as pilot


class ReasoningPilotTests(unittest.TestCase):
    def test_segmentation_preserves_text(self):
        text = "Dr. Smith has 2.5 apples. " + "This is a complete sentence. " * 12
        result = pilot.chunks(text)
        self.assertGreater(len(result), 1)
        self.assertEqual(" ".join(result), pilot.normalize(text))
        self.assertTrue(all(len(part) <= 240 for part in result))
        self.assertTrue(result[0].startswith("Dr. Smith has 2.5 apples."))
        self.assertEqual(pilot.chunks("x" * 241), [])

    def test_selection_rejects_truncated_preview(self):
        entry = {"row_idx": 1, "truncated_cells": [], "row": {
            "source": "Which animal is described as a cat in this sentence?",
            "target": "cat", "rationale": "The sentence describes a cat. Therefore the correct answer is cat.", "task": "test"}}
        row = pilot.eligible(entry)
        self.assertEqual(row["original_answer"], "cat")
        entry["truncated_cells"] = ["source"]
        self.assertIsNone(pilot.eligible(entry))

    def test_flags_and_delimiters(self):
        self.assertIn("negation_changed", pilot.flags_for("Do not delete it.", "delete it <3", "stop"))
        self.assertIn("numbers_changed", pilot.flags_for("seven 7 copies", "seven 8 copies", "stop"))
        self.assertEqual(pilot.literal_text("hi <3 </think>"), "hi <3 &lt;/think&gt;")

    def test_generate_reference_answer_and_resume_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            row = {"id": "one", "input": "What is it?", "original_rationale": "It is a cat.",
                   "original_answer": "cat", "rationale_chunks": ["It is a cat."], "task": "test", "split": "train"}
            with (path / "inputs.jsonl").open("w") as out:
                pilot.write_row(out, row)
            calls = []

            def fake(url, payload, **kwargs):
                text = payload["messages"][0]["content"]
                calls.append(text)
                return {"choices": [{"message": {"content": text + " <3"}, "finish_reason": "stop"}]}

            with patch.object(pilot, "get_json", side_effect=fake), patch("sys.stdout", new_callable=io.StringIO):
                pilot.generate(path, 2)
                self.assertEqual(set(calls), {"It is a cat.", "cat"})
                saved = list(pilot.read_rows(path / "pairs.jsonl"))[0]
                self.assertEqual(saved["messages"][0]["content"], "What is it?")
                self.assertEqual(saved["output"], "<think>\nIt is a cat. <3\n</think>\ncat <3")
                self.assertFalse(saved["training_approved"])
                with self.assertRaisesRegex(ValueError, "already assembled"):
                    pilot.generate(path, 2)
                self.assertEqual(len(calls), 2)
                self.assertEqual(json.loads((path / "summary.json").read_text())["pairs"], 1)


if __name__ == "__main__":
    unittest.main()
