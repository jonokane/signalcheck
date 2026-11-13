"""A whole run with a fake web layer: results files, CSV, CLI errors. No network.

    python -m unittest discover -s tests
"""

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck import cli  # noqa: E402
from signalcheck import run as runmod  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402

ASHBY = "https://jobs.ashbyhq.com/initech/9a5d6f84-0000-4000-8000-000000000001"
ASHBY_GONE = "https://jobs.ashbyhq.com/initech/9a5d6f84-0000-4000-8000-00000000dead"
PAGE = "https://careers.example.com/jobs/42"
FEED = {"jobs": [{"id": "9a5d6f84-0000-4000-8000-000000000001", "title": "Staff Product Designer", "location": "Remote"}]}


class FakeWeb:
    def __init__(self):
        self.closed = False

    def get_text(self, url):
        assert "api.ashbyhq.com" in url, url
        return 200, json.dumps(FEED)

    def get_page(self, url):
        return PageSnapshot(url=url, status=404, final_url=url, title="", text="", settled=True, via="plain HTTP")

    def load(self, url, extract=None):
        raise AssertionError("a plain-HTTP 404 needs no browser")

    def close(self):
        self.closed = True


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.jobs = self.dir / "jobs.csv"
        self.jobs.write_text("company,title,url\n"
                             f"Initech,Staff Product Designer,{ASHBY}\n"
                             f"Initech,Design Lead,{ASHBY_GONE}\n"
                             f"Example,Design Manager,{PAGE}\n")

    def test_results_files(self):
        web = FakeWeb()
        out = self.dir / "results"
        with mock.patch.object(runmod, "log"):
            self.assertEqual(runmod.run(self.jobs, out, web_factory=lambda: web), 0)
        self.assertTrue(web.closed)
        doc = json.loads((out / "latest.json").read_text())
        self.assertEqual(doc["counts"], {"LIVE": 1, "GONE": 2, "CHANGED": 0, "CANT_TELL": 0})
        self.assertEqual([r["verdict"] for r in doc["results"]], ["LIVE", "GONE", "GONE"])
        self.assertEqual(doc["results"][0]["evidence"], "feed")
        self.assertNotIn("kind", doc["results"][0])
        day = doc["runAt"][:10]
        self.assertEqual((out / f"{day}.json").read_text(), (out / "latest.json").read_text())
        md = (out / f"{day}.md").read_text()
        self.assertIn("**3 checked:** 1 live, 2 gone", md)
        rows = list(csv.DictReader((out / "latest.csv").read_text().splitlines()))
        self.assertEqual([r["verdict"] for r in rows], ["LIVE", "GONE", "GONE"])
        self.assertEqual(rows[2]["url"], PAGE)

    def test_one_prints_json(self):
        buf = io.StringIO()
        with mock.patch.object(runmod, "log"), contextlib.redirect_stdout(buf):
            runmod.one(ASHBY, web_factory=FakeWeb)
        self.assertEqual(json.loads(buf.getvalue())["verdict"], "LIVE")


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.entry(list(argv))
        return rc, err.getvalue()

    def test_bad_input_is_one_failed_line(self):
        rc, err = self.run_cli("run", "/nonexistent/jobs.txt")
        self.assertEqual(rc, 2)
        self.assertEqual(err.strip(), "FAILED: file not found: /nonexistent/jobs.txt")

    def test_unexpected_error_ends_with_failed_line(self):
        with mock.patch.object(runmod, "run", side_effect=RuntimeError("boom")):
            rc, err = self.run_cli("run", "jobs.txt")
        self.assertEqual(rc, 1)
        self.assertEqual(err.strip().splitlines()[-1], "FAILED: RuntimeError: boom")


if __name__ == "__main__":
    unittest.main()
