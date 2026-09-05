"""Offline checks for collection integrity; no teacher or HF access required."""

import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_style_dataset as dataset


class StyleDatasetTests(unittest.TestCase):
    def test_complete_text_filter_dedup_and_grouping(self):
        rows = [
            {"_id": 1, "src": "Fix: original sentence", "tgt": "  Hello   friend! "},
            {"_id": 2, "src": "Fix: other", "tgt": "hello friend!"},
            {"_id": 3, "src": "Edit: original sentence", "tgt": "Greetings friend!"},
            {"_id": 4, "tgt": "x" * 161},
            {"_id": 5, "tgt": ""},
        ]
        chosen, stats = dataset.select_inputs(rows, {"dataset": "grammarly/coedit"}, "tgt", 5, 160, 0, 42)
        self.assertEqual(stats["unique_short"], 2)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual({r["input"] for r in chosen}, {"Hello friend!", "Greetings friend!"})
        self.assertEqual(chosen[0]["group_id"], chosen[1]["group_id"])
        self.assertEqual(chosen[0]["split"], chosen[1]["split"])
        again, _ = dataset.select_inputs(rows, {"dataset": "grammarly/coedit"}, "tgt", 5, 160, 0, 42)
        self.assertEqual(chosen, again)

    def test_quality_flags(self):
        self.assertEqual(dataset.quality_flags("Port 1337 works.", "port 1337 works milady <3", "stop"), [])
        self.assertEqual(dataset.quality_flags("Port 1337 works.", "port 1337 works milady!", "stop"), [])
        self.assertIn("truncated", dataset.quality_flags("hi", "hello", "length"))
        self.assertIn("symbol_run", dataset.quality_flags("hi", "hello " + "💖" * 15, "stop"))
        self.assertIn("repeated_phrase", dataset.quality_flags("hi", "hello sweet friend " * 4, "stop"))
        self.assertIn("urls_changed", dataset.quality_flags("hi", "hello https://invented.example", "stop"))

    def test_resume_config_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            records = [
                {"id": "one", "input": "hello friend", "split": "train", "source": {}},
                {"id": "two", "input": "good morning", "split": "validation", "source": {}},
            ]
            with (directory / "inputs.jsonl").open("w") as out:
                for row in records:
                    dataset.write_row(out, row)
            dataset.dump(directory / "source.json", {"stats": {"selected": 2}})
            args = SimpleNamespace(directory=directory, base_url="http://example.test/v1", model="milady",
                                   max_tokens=160, temperature=0.7, repetition_penalty=1.15,
                                   teacher_directory=None, limit=1, export_directory=None, only_passing=True)
            calls = []

            def fake(url, payload=None, **kwargs):
                if url.endswith("/models"):
                    return {"data": [{"id": "milady"}]}
                calls.append(payload["messages"][0]["content"])
                return {"choices": [{"message": {"content": "gm friend!"},
                                     "finish_reason": "stop" if len(calls) == 1 else "length"}]}

            with patch.object(dataset, "get_json", side_effect=fake), patch("sys.stdout", new_callable=io.StringIO):
                dataset.generate(args)
                dataset.generate(args)
                dataset.generate(args)
                self.assertEqual(calls, ["hello friend", "good morning"])
                saved = list(dataset.read_rows(directory / "pairs.jsonl"))
                self.assertEqual(len(saved), 2)
                self.assertEqual(saved[0]["review_status"], "unreviewed")
                self.assertIn("truncated", saved[1]["quality_flags"])
                dataset.export(args)
                candidates = list(dataset.read_rows(directory / "train.candidates.jsonl"))
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["messages"][0]["content"], "hello friend")
                self.assertEqual(candidates[0]["completion"], "gm friend!")
                self.assertEqual(list(dataset.read_rows(directory / "validation.candidates.jsonl")), [])
                with self.assertRaises(ValueError):
                    dataset.export(args)
                args.export_directory = directory / "export2"
                args.only_passing = False
                dataset.export(args)
                self.assertEqual(len(list(dataset.read_rows(args.export_directory / "validation.sft.jsonl"))), 1)
                args.temperature = 0.8
                with self.assertRaisesRegex(ValueError, "settings"):
                    dataset.generate(args)

    def test_concurrent_failure_drains_successes_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rows = [{"id": str(i), "input": f"input {i}", "split": "train", "source": {}} for i in range(6)]
            with (directory / "inputs.jsonl").open("w") as out:
                for row in rows:
                    dataset.write_row(out, row)
            dataset.dump(directory / "source.json", {"stats": {"selected": 6}})
            args = SimpleNamespace(directory=directory, base_url="http://example.test/v1", model="milady",
                                   max_tokens=160, temperature=0.7, repetition_penalty=1.15,
                                   teacher_directory=None, limit=0, concurrency=3)
            barrier = threading.Barrier(3, timeout=5)
            calls = []
            first_run = True

            def fake(url, payload=None, **kwargs):
                if url.endswith("/models"):
                    return {"data": [{"id": "milady"}]}
                text = payload["messages"][0]["content"]
                calls.append(text)
                if first_run:
                    barrier.wait()
                    if text == "input 0":
                        raise ValueError("bad response")
                    time.sleep(0.02)
                return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}

            with patch.object(dataset, "get_json", side_effect=fake), patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaisesRegex(RuntimeError, "successful responses saved"):
                    dataset.generate(args)
                self.assertEqual(len(calls), 3)
                self.assertEqual(len(list(dataset.read_rows(directory / "pairs.jsonl"))), 2)
                first_run = False
                dataset.generate(args)
                saved = list(dataset.read_rows(directory / "pairs.jsonl"))
                self.assertEqual({r["id"] for r in saved}, {str(i) for i in range(6)})
                self.assertEqual(len(saved), 6)
                self.assertEqual(len(calls), 7)

    def test_corrupt_log_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pairs.jsonl"
            path.write_text('{"id": "ok"}\n{"id":')
            with self.assertRaisesRegex(ValueError, "partial line"):
                list(dataset.read_rows(path))


if __name__ == "__main__":
    unittest.main()
