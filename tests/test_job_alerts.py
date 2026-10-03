import base64
import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import job_alerts as a


class Filters(unittest.TestCase):
    def job(self, **kw):
        values = dict(title="DevOps Engineer", company="Acme", location="India", source="test", url="https://example.com/jobs/1", posted=datetime.now(timezone.utc).isoformat())
        values.update(kw)
        return a.Job(**values)

    def test_experience_boundaries(self):
        for value in ["0-1 Yrs", "0-2 years", "0-3 years", "1-3 years", "2-3 years", "1-4 years", "2-5 Yrs", "up to 3 years", "3+ years", "fresher", ""]:
            with self.subTest(value=value):
                self.assertTrue(a.experience(self.job(experience=value))[0])
        for value in ["3-5 Yrs", "4-8 years", "5+ years", "7 years", "over 3 years", "2 years AWS and 5+ years total experience"]:
            with self.subTest(value=value):
                self.assertFalse(a.experience(self.job(experience=value))[0])

    def test_structured_wins_and_senior_rejected(self):
        self.assertTrue(a.experience(self.job(experience="2-3 Yrs", description="5 years old company"))[0])
        for title in ["Senior DevOps Engineer", "Sr. Cloud Engineer", "Staff Platform Engineer", "AWS Architect", "DevOps Lead"]:
            self.assertFalse(a.experience(self.job(title=title))[0])
        self.assertEqual(a.experience(self.job())[1], "Not specified")

    def test_freshness_and_geography(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(a.eligible(self.job(), now + timedelta(seconds=1)))
        for job in [self.job(posted=""), self.job(posted=(now-timedelta(hours=25)).isoformat()), self.job(location="Remote"), self.job(location="Brazil"), self.job(title="Cloud Sales Engineer"), self.job(title="Software Engineer", description="AWS and Kubernetes")]:
            self.assertFalse(a.eligible(job, now))

    def test_html_cards_never_mix_experience(self):
        body = '<table><tr data-company="A" data-location="India" data-posted="2026-10-03T02:00:00Z" data-experience="2-3 Yrs"><td><a href="https://example.com/1">DevOps Engineer</a></td></tr><tr data-company="B" data-location="UK" data-experience="5+ Yrs"><td><a href="https://example.com/2">Cloud Engineer</a></td></tr></table>'
        jobs = a.parse_alert(body, "Naukri <alerts@naukri.com>", datetime.now(timezone.utc))
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].company, "A")
        self.assertEqual(jobs[0].experience, "2-3 Yrs")
        self.assertTrue(a.experience(jobs[0])[0])
        self.assertFalse(a.experience(jobs[1])[0])
        self.assertEqual(jobs[1].posted, "")
        fallback = a.parse_alert(body, "Naukri", datetime.now(timezone.utc), "alert_received")
        self.assertIn("NOT verified", fallback[1].date_basis)

    def test_canonical_dedupe_and_safe_html(self):
        j = self.job(title="DevOps Engineer <script>", description='<script>alert("x")</script>')
        other = self.job(title=j.title, url=j.url + "?utm_source=mail#top")
        self.assertEqual(j.ids(), other.ids())
        output = a.digest([j], [], datetime.now(timezone.utc))
        self.assertNotIn("<script>", output)
        self.assertEqual(a.safe_url("javascript:alert(1)"), "")

    def test_mime_base64(self):
        value = base64.urlsafe_b64encode(b"<b>Hello</b>").decode().rstrip("=")
        self.assertEqual(a.message_body({"parts": [{"mimeType":"text/html", "body":{"data":value}}]}, None, "id"), "<b>Hello</b>")

    def test_smtp_failure_does_not_acknowledge(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "config.json").write_text('{}')
            initial = {"seen": {}, "processed_messages": [], "jsearch_usage": {}}
            (root / "data/state.json").write_text(json.dumps(initial))
            stack.enter_context(patch.object(a, "ROOT", root))
            for name in ["remotive", "remoteok", "himalayas", "wwr", "adzuna"]:
                stack.enter_context(patch.object(a, name, return_value=[]))
            stack.enter_context(patch.object(a, "jsearch", return_value=([], [])))
            stack.enter_context(patch.object(a, "gmail", return_value=([self.job()], ["message1"], object(), [])))
            stack.enter_context(patch.object(a, "send", side_effect=RuntimeError("SMTP rejected")))
            ack = stack.enter_context(patch.object(a, "mark_processed"))
            with self.assertRaises(RuntimeError):
                a.run(SimpleNamespace(demo=False, dry_run=False))
            self.assertEqual(json.loads((root / "data/state.json").read_text()), initial)
            ack.assert_not_called()


if __name__ == "__main__":
    unittest.main()
