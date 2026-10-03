import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import job_alerts as a
from n8n import worker


class WorkerTests(unittest.TestCase):
    def test_metadata_survives_empty_and_filtered_inputs(self):
        senior = a.make_job("Senior DevOps Engineer", "A", "India", "test", "https://example.com/1", datetime.now(a.UTC).isoformat())
        data = worker.operation("/filter", {"sources": [{"jobs": [a.asdict(senior)], "warnings": ["source down"], "message_ids": ["m1"]}, {"jobs": []}]})
        passed = [row for row in data["items"] if row["eligible"]]
        self.assertEqual(len(passed), 2)
        self.assertTrue(all(row["kind"] == "metadata" for row in passed))
        self.assertEqual(passed[0]["warnings"], ["source down"])
        self.assertEqual(passed[0]["message_ids"], ["m1"])

    def test_prepare_does_not_mark_delivered_commit_does(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(a, "ROOT", Path(directory)):
            (a.ROOT / "data").mkdir()
            initial = {"seen": {}, "processed_messages": [], "jsearch_usage": {}}
            a.save_state(initial)
            job = a.make_job("DevOps Engineer", "A", "India", "test", "https://example.com/1", datetime.now(a.UTC).isoformat(), "1-3 years")
            result = worker.operation("/prepare", {"sources": [{"jobs": [a.asdict(job)]}]})
            self.assertEqual(result["count"], 1)
            self.assertEqual(worker.state()["seen"], {})
            worker.operation("/commit", {"token": result["token"]})
            self.assertTrue(worker.state()["seen"])
            duplicate = worker.operation("/prepare", {"sources": [{"jobs": [a.asdict(job)]}]})
            self.assertEqual(duplicate["count"], 0)
            self.assertIn("No new jobs today", duplicate["html"])


if __name__ == "__main__":
    unittest.main()
