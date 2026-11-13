"""Job listing sites (LinkedIn, Indeed...) are recognized and never fetched. No network.

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.detect import detect  # noqa: E402
from signalcheck.systems import check_page  # noqa: E402


class NoFetchWeb:
    def get_page(self, url):
        raise AssertionError(f"fetched {url}")

    def load(self, url, extract=None):
        raise AssertionError(f"loaded {url}")


class ListingSites(unittest.TestCase):
    def test_recognized_including_country_domains(self):
        cases = {
            "https://www.linkedin.com/jobs/view/4012345678/": "LinkedIn",
            "https://uk.indeed.com/viewjob?jk=abc": "Indeed",
            "https://www.indeed.de/viewjob?jk=abc": "Indeed",
            "https://au.indeed.com.au/viewjob?jk=abc": "Indeed",
            "https://www.glassdoor.co.uk/job-listing/x.htm": "Glassdoor",
            "https://www.ziprecruiter.com/c/Acme/Job/x": "ZipRecruiter",
            "https://wellfound.com/jobs/123": "Wellfound",
        }
        for url, site in cases.items():
            d = detect(url, {})
            self.assertEqual((d["system"], d["token"]), ("listing_site", site), url)

    def test_lookalikes_are_ordinary_pages(self):
        for url in ("https://notlinkedin.com/jobs/1", "https://builtin.example.com/x",
                    "https://jobs.monster.energy/x", "https://linkedin.com.evil.io/x"):
            self.assertEqual(detect(url, {})["system"], "generic", url)

    def test_cant_tell_without_any_request(self):
        url = "https://www.linkedin.com/jobs/view/4012345678/"
        r = {"id": "r1", "company": "Acme", "title": "Designer", "url": url, "_detect": detect(url, {})}
        v = check_page(NoFetchWeb(), [r])["r1"]
        self.assertEqual((v["verdict"], v["evidence"]), ("CANT_TELL", "none"))
        self.assertIn("company's own posting link", v["reason"])


if __name__ == "__main__":
    unittest.main()
