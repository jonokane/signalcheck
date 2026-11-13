"""A closure notice over plain HTTP must be confirmed in the browser. No network.

Some sites serve "This position has been filled" to non-browser requests
while the posting is open in a real browser.

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.detect import detect  # noqa: E402
from signalcheck.systems import check_page  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402

URL = "https://careers.example.com/global/en/job/R_100001/Digital-Experience-Lead"
BODY = "Role details and responsibilities. " * 60


def row():
    r = {"id": "r1", "company": "Example", "title": "Digital Experience Lead", "url": URL}
    r["_detect"] = detect(URL, {})
    return r


def filled(via):
    return PageSnapshot(url=URL, status=200, final_url=URL, title="Example Careers",
                        text="Sorry, this position has been filled.", settled=True,
                        headings=["This position has been filled"], has_apply=False, via=via)


def open_posting():
    return PageSnapshot(url=URL, status=200, final_url=URL, title="Digital Experience Lead",
                        text=BODY, settled=True, headings=["Digital Experience Lead"],
                        has_apply=True, via="browser")


class FakeWeb:
    def __init__(self, plain, browser=None):
        self.plain, self.browser, self.loads = plain, browser, 0

    def get_page(self, url):
        return self.plain

    def load(self, url):
        self.loads += 1
        return self.browser


class PlainClosureNeedsBrowser(unittest.TestCase):
    def test_false_filled_page_is_live(self):
        web = FakeWeb(filled("plain HTTP"), open_posting())
        v = check_page(web, [row()])["r1"]
        self.assertEqual(web.loads, 1)
        self.assertEqual((v["verdict"], v["evidence"]), ("LIVE", "req_page"))
        self.assertIn("has been filled", v["reason"])

    def test_gone_only_when_browser_agrees(self):
        web = FakeWeb(filled("plain HTTP"), filled("browser"))
        v = check_page(web, [row()])["r1"]
        self.assertEqual(web.loads, 1)
        self.assertEqual(v["verdict"], "GONE")
        self.assertTrue(v["reason"].startswith("Browser load"))

    def test_plain_404_is_not_rechecked(self):
        web = FakeWeb(PageSnapshot(url=URL, status=404, final_url=URL, title="", text="", settled=True, via="plain HTTP"))
        v = check_page(web, [row()])["r1"]
        self.assertEqual((web.loads, v["verdict"]), (0, "GONE"))


if __name__ == "__main__":
    unittest.main()
