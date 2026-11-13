"""Offline tests for `describe`: text cleaning and per-system extraction.
Saved fixtures in tests/fixtures/, no network.

    python -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck import describe as D  # noqa: E402
from signalcheck.detect import detect  # noqa: E402
from signalcheck.html_page import parse_html  # noqa: E402
from signalcheck.text import cap_text, clean_text, html_to_text  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return (FIX / name).read_text()


def row(url, rid="r1", title="Product Designer"):
    return {"id": rid, "company": "Example", "title": title, "url": url, "_detect": detect(url, {})}


class FakeWeb:
    """get_text answers from a {url: (status, body)} map; anything else is a test failure."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get_text(self, url):
        self.asked.append(url)
        return self.answers[url]


def plain_snap(html, url="https://example.com/jobs/1", status=200, final_url=None):
    facts, posting = parse_html(html)
    return PageSnapshot(url=url, status=status, final_url=final_url or url, title=facts.title, text=facts.text,
                        settled=True, headings=facts.heads, h1=facts.h1, has_apply=facts.has_apply,
                        job_posting=posting, via="plain HTTP")


class TextCleaning(unittest.TestCase):
    def test_paragraphs_and_bullets_kept(self):
        t = html_to_text("<p>Intro  text\n here.</p><ul><li><p>One</p></li><li>Two &amp; <b>three</b></li></ul><h3>Next</h3><p>A<br>B</p>")
        self.assertEqual(t, "Intro text here.\n\n- One\n- Two & three\n\nNext\n\nA\nB")

    def test_double_escaped_html(self):
        self.assertEqual(html_to_text("&lt;p&gt;Fish &amp;amp; chips&lt;/p&gt;&lt;ul&gt;&lt;li&gt;x&lt;/li&gt;&lt;/ul&gt;"), "Fish & chips\n\n- x")

    def test_scripts_and_styles_dropped(self):
        self.assertEqual(html_to_text("<style>p{}</style><p>Hi</p><script>evil()</script>"), "Hi")

    def test_plain_text_whitespace_and_bullet_glyphs(self):
        self.assertEqual(clean_text("  A   b \r\n\n\n\n• one\n\n·  two\n– three\n \nend​ "),
                         "A b\n\n- one\n- two\n- three\n\nend")

    def test_embedded_base64_image_removed(self):
        self.assertEqual(clean_text("[data:image/png;base64,iVBORw0KGgoAAAA+/=]\n\nAbout Plug\n![](data:image/jpeg;base64,AAAA)"), "About Plug")

    def test_hyphenated_words_are_not_bullets(self):
        self.assertEqual(clean_text("-30% churn\nfull-time"), "-30% churn\nfull-time")

    def test_cap(self):
        long = ("word " * 3000).strip()
        out = clean_text(long)
        self.assertLessEqual(len(out), 9000)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out[:-1].endswith(" "))

    def test_cap_prefers_line_boundary(self):
        text = "a" * 8500 + "\n" + "b" * 1000
        self.assertEqual(cap_text(text), "a" * 8500 + "…")

    def test_short_text_untouched_by_cap(self):
        self.assertEqual(cap_text("short"), "short")


class Ashby(unittest.TestCase):
    ORG = "toolco"
    FEED = f"https://api.ashbyhq.com/posting-api/job-board/{ORG}?includeCompensation=true"

    def run_rows(self, *ids):
        rows = [row(f"https://jobs.ashbyhq.com/{self.ORG}/{i}", rid=f"r{n}") for n, i in enumerate(ids)]
        return D.describe_ashby(FakeWeb({self.FEED: (200, fixture("ashby_feed.json"))}), self.ORG, rows)

    def test_description_plain_cleaned(self):
        # Pad to clear the 200-character floor without changing the shape under test.
        job = json.loads(fixture("ashby_feed.json"))["jobs"][0]
        self.assertEqual(D.ashby_text(job), "About us\n\nWe build tools.\n\nWhat you'll do\n\n- Lead design\n- Ship it weekly")

    def test_absent_is_skipped_as_gone(self):
        out = self.run_rows("ffffffff-0000-0000-0000-000000000000")
        self.assertIsInstance(out["r0"], D.Skip)
        self.assertIn("not in the Ashby feed", str(out["r0"]))

    def test_too_short_is_skipped(self):
        out = self.run_rows("00000000-0000-0000-0000-000000000001")
        self.assertIn("only 10 characters", str(out["r0"]))

    def test_bad_feed_skips_group(self):
        with self.assertRaises(D.Skip):
            D.describe_ashby(FakeWeb({self.FEED: (200, "<html>oops")}), self.ORG, [row(f"https://jobs.ashbyhq.com/{self.ORG}/x")])


class Lever(unittest.TestCase):
    ORG = "planwell"
    FEED = f"https://api.lever.co/v0/postings/{ORG}?mode=json"
    JID = "aaaaaaaa-1111-2222-3333-444444444444"

    def test_order_description_lists_additional(self):
        text = D.lever_text(json.loads(fixture("lever_feed.json"))[0])
        self.assertEqual(text, (
            "Planwell is hiring a principal designer to shape how teams plan their week.\n\n"
            "What you'll do\n- Own the planning flow\n- Partner with research & engineering\n\n"
            "About you\n- 10+ years of product design\n\n"
            "Planwell is an equal opportunity employer."))

    def test_found_in_feed(self):
        web = FakeWeb({self.FEED: (200, fixture("lever_feed.json"))})
        out = D.describe_lever(web, self.ORG, [row(f"https://jobs.lever.co/{self.ORG}/{self.JID}")])
        self.assertTrue(out["r1"].startswith("Planwell is hiring"))
        self.assertEqual(web.asked, [self.FEED])

    def test_absent_asks_posting_api_then_skips_on_404(self):
        missing = "bbbbbbbb-0000-0000-0000-000000000000"
        one = f"https://api.lever.co/v0/postings/{self.ORG}/{missing}?mode=json"
        web = FakeWeb({self.FEED: (200, fixture("lever_feed.json")), one: (404, '{"ok":false}')})
        out = D.describe_lever(web, self.ORG, [row(f"https://jobs.lever.co/{self.ORG}/{missing}")])
        self.assertIn("HTTP 404", str(out["r1"]))
        self.assertEqual(web.asked, [self.FEED, one])

    def test_absent_but_posting_api_has_it(self):
        missing = "bbbbbbbb-0000-0000-0000-000000000000"
        one = f"https://api.lever.co/v0/postings/{self.ORG}/{missing}?mode=json"
        posting = json.dumps(json.loads(fixture("lever_feed.json"))[0])
        web = FakeWeb({self.FEED: (200, "[]"), one: (200, posting)})
        out = D.describe_lever(web, self.ORG, [row(f"https://jobs.lever.co/{self.ORG}/{missing}")])
        self.assertTrue(out["r1"].startswith("Planwell is hiring"))


class Greenhouse(unittest.TestCase):
    URL = "https://job-boards.greenhouse.io/examplefreight/jobs/7000000001"
    API = "https://boards-api.greenhouse.io/v1/boards/examplefreight/jobs/7000000001"

    def test_content_unescaped_and_stripped(self):
        self.assertEqual(D.greenhouse_text(json.loads(fixture("greenhouse_job.json"))), (
            "Example Freight builds delivery software.\n\nResponsibilities\n\n"
            "- Define the dispatch roadmap\n- Run studies with drivers & customers\n\n"
            "Pay range\n$150,000 - $190,000 USD"))

    def test_api_404_is_skipped_without_a_liveness_claim(self):
        with self.assertRaises(D.Skip) as cm:
            D.describe_greenhouse(FakeWeb({self.API: (404, "")}), "examplefreight", row(self.URL))
        self.assertIn("not a liveness verdict", str(cm.exception))

    def test_fetch(self):
        web = FakeWeb({self.API: (200, fixture("greenhouse_job.json"))})
        # The fixture is short, so lower the floor for this test only.
        old, D.MIN_CHARS = D.MIN_CHARS, 50
        try:
            self.assertTrue(D.describe_greenhouse(web, "examplefreight", row(self.URL)).startswith("Example Freight builds"))
        finally:
            D.MIN_CHARS = old


class Pages(unittest.TestCase):
    def test_jsonld_description_preferred(self):
        text, needs_browser = D.page_text(row("https://example.com/jobs/1"), plain_snap(fixture("company_page.html")))
        self.assertFalse(needs_browser)
        self.assertTrue(text.startswith("Example Co makes tools for audio engineers.\n\n- Design the mixer UI\n- Prototype in code\n\nWe are"))
        self.assertNotIn("Cookie", text)

    def test_shell_without_jsonld_goes_to_browser(self):
        text, needs_browser = D.page_text(row("https://example.com/jobs/1"), plain_snap(fixture("shell_page.html")))
        self.assertEqual((text, needs_browser), ("", True))

    def test_gone_page_is_skipped(self):
        with self.assertRaises(D.Skip) as cm:
            D.page_text(row("https://example.com/jobs/1"), plain_snap("<h1>Not found</h1>", status=404))
        self.assertIn("page is gone", str(cm.exception))

    def browser_snap(self, main, has_apply=True, ld=None):
        return PageSnapshot(url="https://x.wd1.myworkdayjobs.com/c/job/1", status=200, final_url="https://x.wd1.myworkdayjobs.com/c/job/1",
                            title="Product Designer", text="Product Designer\n" + main, settled=True, h1=["Product Designer"],
                            has_apply=has_apply, job_posting=ld, extra={"main": main}, via="browser")

    def test_rendered_main_text_used_without_jsonld(self):
        main = "About the role\n\n\n• Lead design   for payroll\n" + "We design calm software. " * 50
        text, _ = D.page_text(row("https://x.wd1.myworkdayjobs.com/c/job/1"), self.browser_snap(main))
        self.assertTrue(text.startswith("About the role\n\n- Lead design for payroll\nWe design"))

    def test_rendered_shell_is_skipped(self):
        with self.assertRaises(D.Skip) as cm:
            D.page_text(row("https://x.wd1.myworkdayjobs.com/c/job/1"), self.browser_snap("Loading...", has_apply=False))
        self.assertIn("no posting body", str(cm.exception))

    def test_jsonld_plain_text_entities_decoded(self):
        ld = {"@type": "JobPosting", "description": "Growth &amp; Acquisitions. " * 10}
        snap = self.browser_snap("x", ld=ld)
        text, _ = D.page_text(row("https://x.wd1.myworkdayjobs.com/c/job/1"), snap)
        self.assertTrue(text.startswith("Growth & Acquisitions."))

    def test_apply_form_in_iframe_still_captured(self):
        # A full posting, apply form inside a Greenhouse iframe, so no apply control on the page.
        main = "Senior Design Manager\n\n" + "This team owns AI monitoring. " * 40
        text, _ = D.page_text(row("https://careers.example.com/detail/1/?gh_jid=1", title="Senior Design Manager"),
                              self.browser_snap(main, has_apply=False))
        self.assertTrue(text.startswith("Senior Design Manager\n\nThis team"))

    def test_rendered_jsonld_beats_main_text(self):
        ld = {"@type": "JobPosting", "description": "<p>" + "From JSON-LD. " * 20 + "</p>"}
        text, _ = D.page_text(row("https://x.wd1.myworkdayjobs.com/c/job/1"), self.browser_snap("nav junk " * 200, ld=ld))
        self.assertTrue(text.startswith("From JSON-LD."))


class Output(unittest.TestCase):
    def test_doc_shape_and_sources(self):
        rows = [row("https://jobs.ashbyhq.com/o/1", rid="a"),
                row("https://careers.example.com/x?gh_jid=5", rid="gh-hosted"),
                row("https://jobs.gem.com/o/abc", rid="gem")]
        got = {"a": "text a", "gh-hosted": "text b", "gem": D.Skip("blocked")}
        doc = D.build_doc(rows, got, "2026-11-11T20:00:00-08:00", "2026-11-11")
        self.assertEqual(set(doc), {"generatedAt", "items", "skipped"})
        self.assertEqual(doc["items"]["a"], {"url": "https://jobs.ashbyhq.com/o/1", "company": "Example", "title": "Product Designer",
                                             "text": "text a", "source": "Ashby feed", "fetchedAt": "2026-11-11"})
        self.assertEqual(doc["items"]["gh-hosted"]["source"], "company page")
        self.assertEqual(doc["skipped"], [{"id": "gem", "reason": "blocked"}])


if __name__ == "__main__":
    unittest.main()
