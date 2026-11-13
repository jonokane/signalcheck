"""Title comparison. No network.

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.detect import detect, norm_title, strip_site_suffix, title_differs  # noqa: E402
from signalcheck.html_page import parse_html  # noqa: E402
from signalcheck.systems import check_page, page_verdict, req_page_title  # noqa: E402
from signalcheck.web import PageSnapshot  # noqa: E402

URL = "https://careers.example.com/jobs/123"
BODY = "Role details and responsibilities. " * 60


def row(title, company="Example", url=URL):
    r = {"id": "r1", "company": company, "title": title, "url": url}
    r["_detect"] = detect(url, {})
    return r


def snap(**kw):
    base = dict(url=URL, status=200, final_url=URL, title="", text=BODY, settled=True, has_apply=True)
    base.update(kw)
    return PageSnapshot(**base)


class Normalise(unittest.TestCase):
    def test_brackets_removed(self):
        self.assertEqual(norm_title("Support Operations Director (100% remote, US only)"), "support operations director")
        self.assertEqual(norm_title("Staff Designer [Contract]"), "staff designer")
        self.assertEqual(norm_title("Designer (Senior (L5))"), "designer")

    def test_case_punctuation_whitespace(self):
        self.assertEqual(norm_title("  Sr.   Data-Analyst, Growth "), "sr data analyst growth")


class Compare(unittest.TestCase):
    def test_parenthetical_extras_are_not_a_change(self):
        self.assertFalse(title_differs("Support Operations Director (100% remote, US only)", "Support Operations Director"))
        self.assertFalse(title_differs("Senior UX Researcher (Remote US)", "Senior UX Researcher"))
        self.assertFalse(title_differs("Product Designer [Remote]", "product designer"))

    def test_no_substring_containment(self):
        self.assertTrue(title_differs("Senior Principal Product Manager", "Principal Product Manager"))
        self.assertTrue(title_differs("Principal Product Manager", "Senior Principal Product Manager"))

    def test_real_changes(self):
        self.assertTrue(title_differs("VP of Design", "Lead Data Analyst"))
        self.assertTrue(title_differs("Staff Product Designer", "Principal Product Manager, Member Experience"))

    def test_empty_side_is_not_a_change(self):
        self.assertFalse(title_differs("Head of Support", ""))
        self.assertFalse(title_differs("", "Head of Support"))


class SiteSuffix(unittest.TestCase):
    def test_company_suffix_removed(self):
        self.assertEqual(strip_site_suffix("Head of Marketing | Globex", "Globex Motors"), "Head of Marketing")
        self.assertEqual(strip_site_suffix("Head of Marketing - Globex Motors", "Globex"), "Head of Marketing")
        self.assertEqual(strip_site_suffix("Product Designer – Careers at Acme", "Other"), "Product Designer")

    def test_role_suffix_kept(self):
        self.assertEqual(strip_site_suffix("Product Designer - Growth", "Acme"), "Product Designer - Growth")

    def test_stacked_suffixes(self):
        self.assertEqual(strip_site_suffix("Designer | Acme | Careers", "Acme"), "Designer")


class ReqPageTitle(unittest.TestCase):
    def test_jsonld_title_first(self):
        s = snap(h1=["job details"], job_posting={"title": "Staff Product Designer"}, og_title="Something | Example")
        self.assertEqual(req_page_title(s, "Example"), "Staff Product Designer")

    def test_og_title_when_no_jsonld(self):
        s = snap(h1=["Why This Role"], og_title="Staff Product Designer | Example")
        self.assertEqual(req_page_title(s, "Example"), "Staff Product Designer")

    def test_html_entities_unescaped(self):
        # Some sites send "&amp;" inside JSON-LD and og:title.
        s = snap(job_posting={"title": "Growth &amp; Acquisitions"})
        self.assertEqual(req_page_title(s), "Growth & Acquisitions")
        s = snap(og_title="Personalization &amp; Discovery | Globex")
        self.assertEqual(req_page_title(s, "Globex"), "Personalization & Discovery")
        v = page_verdict(row("Principal PM, Personalization & Discovery"),
                         snap(job_posting={"title": "Principal PM, Personalization &amp; Discovery"}))
        self.assertEqual(v["verdict"], "LIVE")

    def test_headings_and_tab_title_never_used(self):
        s = snap(title="Job details", h1=["job details"], headings=["Why This Role"])
        self.assertEqual(req_page_title(s, "Example"), "")

    def test_generic_heading_no_longer_changes_a_live_row(self):
        # A generic h1 like "job details" must not become the observed title.
        v = page_verdict(row("Senior UX Design Manager"), snap(h1=["job details"], title="job details"))
        self.assertEqual(v["verdict"], "LIVE")
        self.assertEqual(v["observedTitle"], "")

    def test_structured_title_still_catches_a_real_change(self):
        v = page_verdict(row("VP of Design"), snap(job_posting={"title": "Lead Data Analyst"}))
        self.assertEqual(v["verdict"], "CHANGED")
        self.assertIn("Lead Data Analyst", v["reason"])

    def test_og_title_with_company_suffix_matches(self):
        v = page_verdict(row("Principal PM, AI Personalization (Hybrid)", company="Globex"),
                         snap(og_title="Principal PM, AI Personalization | Globex"))
        self.assertEqual(v["verdict"], "LIVE")


class PlainHtmlOgTitle(unittest.TestCase):
    def test_parser_reads_og_title(self):
        facts, posting = parse_html('<html><head><meta property="og:title" content="  Staff Designer | Acme "></head>'
                                    '<body><h1>Why This Role</h1></body></html>')
        self.assertEqual(facts.og_title, "Staff Designer | Acme")
        self.assertIsNone(posting)

    def test_plain_http_page_uses_og_title_not_h1(self):
        html = ('<html><head><title>job details</title><meta property="og:title" content="Staff Product Designer | Example"></head>'
                f'<body><h1>job details</h1><p>{BODY}</p><a href="/apply">Apply</a></body></html>')
        facts, posting = parse_html(html)
        s = PageSnapshot(url=URL, status=200, final_url=URL, title=facts.title, text=facts.text, settled=True,
                         headings=facts.heads, h1=facts.h1, has_apply=facts.has_apply, job_posting=posting,
                         og_title=facts.og_title, via="plain HTTP")

        class W:
            def get_page(self, url):
                return s

        v = check_page(W(), [row("Staff Product Designer")])["r1"]
        self.assertEqual((v["verdict"], v["observedTitle"]), ("LIVE", "Staff Product Designer"))


if __name__ == "__main__":
    unittest.main()
