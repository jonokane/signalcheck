"""Generic job pages: plain HTTP first, browser when needed. No network.

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.detect import detect  # noqa: E402
from signalcheck.html_page import parse_html  # noqa: E402
from signalcheck.systems import check_page  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402

URL = "https://careers.example.com/jobs/8233482"

SERVER_RENDERED = """<!doctype html><html><head><title>Senior Product Designer, Consumer App | Example Careers</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Senior Product Designer, Consumer App"}</script>
<script>window.analytics = "apply now";</script></head>
<body><h1>Senior Product Designer, Consumer App</h1><p>%s</p><a href="/apply">Apply Now</a></body></html>""" % ("We build things. " * 120)

JS_SHELL = """<!doctype html><html><head><title>Careers</title><script src="/app.js"></script></head>
<body><div id="root"></div><noscript>You need to enable JavaScript to run this app.</noscript></body></html>"""


def snap_from_html(html, status=200):
    facts, posting = parse_html(html)
    return PageSnapshot(url=URL, status=status, final_url=URL, title=facts.title, text=facts.text, settled=True,
                        headings=facts.heads, h1=facts.h1, has_apply=facts.has_apply, job_posting=posting, via="plain HTTP")


def row(title="Senior Product Designer, Consumer App"):
    r = {"id": "r1", "company": "Example", "title": title, "url": URL}
    r["_detect"] = detect(URL, {})
    return r


class FakeWeb:
    """Records calls; returns canned snapshots."""

    def __init__(self, plain, browser=None):
        self.plain, self.browser, self.calls = plain, browser, []

    def get_page(self, url):
        self.calls.append("get_page")
        return self.plain

    def load(self, url, extract=None):
        self.calls.append("load")
        return self.browser


class HtmlParsing(unittest.TestCase):
    def test_server_rendered_page_facts(self):
        facts, posting = parse_html(SERVER_RENDERED)
        self.assertEqual(facts.h1, ["Senior Product Designer, Consumer App"])
        self.assertTrue(facts.has_apply)
        self.assertEqual(posting["title"], "Senior Product Designer, Consumer App")
        self.assertNotIn("analytics", facts.text)  # script text is not page text

    def test_shell_has_no_posting(self):
        facts, posting = parse_html(JS_SHELL)
        self.assertFalse(facts.has_apply)
        self.assertIsNone(posting)
        self.assertNotIn("enable JavaScript", facts.text)  # noscript is not page text


class PlainHttpFirst(unittest.TestCase):
    def test_server_rendered_posting_decides_without_browser(self):
        web = FakeWeb(plain=snap_from_html(SERVER_RENDERED))
        v = check_page(web, [row()])["r1"]
        self.assertEqual((v["verdict"], v["evidence"]), ("LIVE", "req_page"))
        self.assertTrue(v["reason"].startswith("Plain HTTP GET"))
        self.assertEqual(web.calls, ["get_page"])  # browser never started

    def test_jobposting_data_counts_even_without_apply_link(self):
        html = SERVER_RENDERED.replace('<a href="/apply">Apply Now</a>', "")
        v = check_page(FakeWeb(plain=snap_from_html(html)), [row()])["r1"]
        self.assertEqual(v["verdict"], "LIVE")

    def test_server_rendered_closure_is_confirmed_in_browser(self):
        # A plain-HTTP closure notice is re-checked in the browser before GONE.
        closed = snap_from_html("<html><title>Careers</title><body><h1>This job is no longer available</h1></body></html>")
        web = FakeWeb(plain=closed, browser=closed)
        self.assertEqual(check_page(web, [row()])["r1"]["verdict"], "GONE")
        self.assertEqual(web.calls, ["get_page", "load"])

    def test_js_shell_falls_back_to_browser(self):
        rendered = PageSnapshot(url=URL, status=200, final_url=URL, title="Careers", text="Role details. " * 200,
                                settled=True, headings=["Senior Product Designer, Consumer App"],
                                h1=["Senior Product Designer, Consumer App"], has_apply=True)
        web = FakeWeb(plain=snap_from_html(JS_SHELL), browser=rendered)
        v = check_page(web, [row()])["r1"]
        self.assertEqual(web.calls, ["get_page", "load"])
        self.assertEqual(v["verdict"], "LIVE")
        self.assertTrue(v["reason"].startswith("Browser load"))

    def test_workday_skips_plain_http(self):
        url = "https://x.wd1.myworkdayjobs.com/C/job/A_1"
        r = {"id": "r1", "company": "X", "title": "Director", "url": url, "_detect": detect(url, {})}
        shell = PageSnapshot(url=url, status=200, final_url=url, title="", text="The page you are looking for doesn't exist.", settled=True)
        web = FakeWeb(plain=None, browser=shell)
        self.assertEqual(check_page(web, [r])["r1"]["verdict"], "GONE")
        self.assertEqual(web.calls, ["load"])


if __name__ == "__main__":
    unittest.main()
