"""Offline tests of the evidence rules. No network.

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.detect import detect, title_differs  # noqa: E402
from signalcheck.systems import BoardRead, ashby_verdicts, greenhouse_verdicts, page_verdict  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402


def row(url, title="Head of Research", rid="r1"):
    r = {"id": rid, "company": "X", "title": title, "url": url}
    r["_detect"] = detect(url, {})
    return r


class Detect(unittest.TestCase):
    def test_systems(self):
        cases = {
            "https://job-boards.greenhouse.io/acme/jobs/4000000001": ("greenhouse", "acme", "4000000001"),
            "https://boards.greenhouse.io/Globex/jobs/8000001": ("greenhouse", "globex", "8000001"),
            "https://jobs.ashbyhq.com/initech/9A5D6F84-0000-4000-8000-000000000001": ("ashby", "initech", "9a5d6f84-0000-4000-8000-000000000001"),
            "https://jobs.lever.co/umbrella/7314a1a4-0000-4000-8000-000000000002": ("lever", "umbrella", "7314a1a4-0000-4000-8000-000000000002"),
            "https://hooli.wd1.myworkdayjobs.com/HooliCareers/job/x_1": ("workday", None, None),
            "https://jobs.gem.com/example/abc": ("gem", None, None),
            "https://careers.example.com/jobs/8233482": ("generic", None, None),
        }
        for url, want in cases.items():
            d = detect(url, {})
            self.assertEqual((d["system"], d["token"], d["job_id"]), want, url)

    def test_company_hosted_greenhouse(self):
        d = detect("https://www.example.com/careers?gh_jid=123", {"www.example.com": "example"})
        self.assertEqual((d["system"], d["token"], d["job_id"]), ("greenhouse", "example", "123"))
        self.assertIsNone(detect("https://other.com/c?gh_jid=123", {})["token"])


class Titles(unittest.TestCase):
    def test_compare(self):
        self.assertFalse(title_differs("Head of Sales & Marketing", "head of sales and marketing"))
        self.assertFalse(title_differs("UX Writer, Payments (Senior/Staff)", "UX Writer, Payments"))
        self.assertTrue(title_differs("VP of Design", "Principal Designer"))
        # No substring containment: a raw tab title with the company appended
        # is a different string.
        self.assertTrue(title_differs("Director, Customer Success", "Director, Customer Success | Hooli Careers"))


class GreenhouseEvidence(unittest.TestCase):
    URL = "https://job-boards.greenhouse.io/acme/jobs/4000000001"

    def test_absent_from_full_board_is_gone_even_if_page_renders(self):
        # The req page may still render with an Apply button; the checker never
        # looks at it. Absent from a fully read board means GONE.
        board = BoardRead("acme", {"1": {"title": "A", "location": ""}, "2": {"title": "B", "location": ""}}, header=2, pages=1)
        v = greenhouse_verdicts([row(self.URL)], board)["r1"]
        self.assertEqual((v["verdict"], v["evidence"]), ("GONE", "board"))
        self.assertEqual(v["boardCount"], {"header": 2, "collected": 2})

    def test_short_read_is_cant_tell(self):
        board = BoardRead("acme", {"1": {"title": "A", "location": ""}}, header=17, pages=1)
        self.assertEqual(greenhouse_verdicts([row(self.URL)], board)["r1"]["verdict"], "CANT_TELL")

    def test_present_is_live_and_title_change_is_changed(self):
        board = BoardRead("acme", {"4000000001": {"title": "Head of Research", "location": "US"}}, header=1, pages=1)
        self.assertEqual(greenhouse_verdicts([row(self.URL)], board)["r1"]["verdict"], "LIVE")
        board.jobs["4000000001"]["title"] = "Principal Designer"
        v = greenhouse_verdicts([row(self.URL, title="VP of Design")], board)["r1"]
        self.assertEqual((v["verdict"], v["observedTitle"]), ("CHANGED", "Principal Designer"))


class AshbyEvidence(unittest.TestCase):
    def test_empty_feed_is_gone(self):
        r = row("https://jobs.ashbyhq.com/initech/9a5d6f84-0000-4000-8000-000000000001", title="Head")
        v = ashby_verdicts([r], "initech", {"jobs": []})["r1"]
        self.assertEqual((v["verdict"], v["evidence"]), ("GONE", "feed"))


class PageEvidence(unittest.TestCase):
    def snap(self, **kw):
        base = dict(url="https://x.myworkdayjobs.com/C/job/A_1", status=200, final_url="https://x.myworkdayjobs.com/C/job/A_1",
                    title="Careers", text="", settled=True, headings=[], has_apply=False)
        base.update(kw)
        return PageSnapshot(**base)

    def test_workday_missing_page_is_gone(self):
        s = self.snap(text="Sign In / Search for Jobs / The page you are looking for doesn't exist.")
        self.assertEqual(page_verdict(row(s.url, title="Director"), s)["verdict"], "GONE")

    def test_empty_shell_is_cant_tell(self):
        s = self.snap(text="Loading jobs...", settled=False)
        self.assertEqual(page_verdict(row(s.url, title="Director"), s)["verdict"], "CANT_TELL")

    def test_full_posting_with_apply_is_live_req_page(self):
        s = self.snap(text="Director of Design. " * 100, headings=["Director"], h1=["Director"], has_apply=True)
        v = page_verdict(row(s.url, title="Director"), s)
        self.assertEqual((v["verdict"], v["evidence"]), ("LIVE", "req_page"))

    def test_no_structured_title_skips_title_check(self):
        # Gem pages have no <h1>; the first <h2> is a section like "The Role".
        # A req page's title comes only from JSON-LD or og:title, so with
        # neither, neither the tab title nor a heading is used.
        s = self.snap(url="https://jobs.gem.com/example/abc", final_url="https://jobs.gem.com/example/abc",
                      title="Something Else Entirely", text="x " * 2000, headings=["The Role"], h1=[], has_apply=True)
        v = page_verdict(row(s.url, title="Senior UX Researcher"), s)
        self.assertEqual((v["verdict"], v["observedTitle"]), ("LIVE", ""))

    def test_redirect_to_search_is_gone(self):
        s = self.snap(final_url="https://x.myworkdayjobs.com/C", text="Search for Jobs " * 200, has_apply=True)
        self.assertEqual(page_verdict(row(s.url, title="Director"), s)["verdict"], "GONE")


if __name__ == "__main__":
    unittest.main()
