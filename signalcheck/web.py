"""Polite, read-only access to the web: JSON over HTTP and a headless browser.

Politeness: requests run one at a time, and the same host is
never hit again until 2 to 5 seconds after the previous request finished.
Retries are handled by the caller (one retry per URL, after 60+ seconds).

The browser is Playwright's stock Chromium with its normal user agent. It only
navigates to URLs; it never clicks, types, signs in or submits anything.
"""

import random
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from . import __version__
from .html_page import find_job_posting, parse_html
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PAGE_CAP_SECONDS = 30.0

# Phrases that mean a bot check or refusal page. Only looked for on short pages.
BOT_MARKERS = (
    "captcha",
    "verify you are human",
    "are you a robot",
    "just a moment",
    "unusual traffic",
    "access denied",
    "attention required",
    "press & hold",
    "request unsuccessful",
)


class Transient(Exception):
    """A failure worth one retry (network error, timeout, 429, 5xx)."""


class Blocked(Exception):
    """A bot check or refusal. Never retried, never bypassed."""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class HostGate:
    def __init__(self):
        self._last_done = {}

    def before(self, url):
        host = (urlparse(url).hostname or "").lower()
        done = self._last_done.get(host)
        if done is not None:
            wait = done + random.uniform(2.0, 5.0) - time.monotonic()
            if wait > 0:
                time.sleep(wait)

    def after(self, url):
        host = (urlparse(url).hostname or "").lower()
        self._last_done[host] = time.monotonic()


@dataclass
class PageSnapshot:
    url: str
    status: int | None
    final_url: str
    title: str
    text: str
    settled: bool
    extra: object = None
    headings: list = field(default_factory=list)  # h1 and h2 text, for closure notices
    h1: list = field(default_factory=list)  # h1 text only, the posting title if any
    has_apply: bool = False
    job_posting: dict | None = None  # schema.org JobPosting from the HTML, if any
    og_title: str = ""  # <meta property="og:title">, if any
    via: str = "browser"  # "browser" or "plain HTTP"


# Read once per page load: headings and whether any apply control exists.
# Reading only; nothing is clicked.
PAGE_FACTS_JS = """() => {
  const heads = Array.from(document.querySelectorAll('h1,h2')).map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 6);
  const h1 = Array.from(document.querySelectorAll('h1')).map(e => (e.innerText || '').trim()).filter(Boolean);
  const controls = Array.from(document.querySelectorAll('a,button,input[type=submit]'));
  const hasApply = controls.some(e => /\\bapply\\b/i.test((e.innerText || e.value || e.getAttribute('aria-label') || '')));
  const og = document.querySelector('meta[property="og:title"]');
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(e => e.textContent || '');
  return {heads, h1, hasApply, ogTitle: og ? (og.getAttribute('content') || '').trim() : '', ld};
}"""


class Web:
    def __init__(self):
        self.gate = HostGate()
        self.http = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": f"signalcheck/{__version__} (personal job tracker; read-only; +https://github.com/jonokane/signalcheck)"},
        )
        # Plain GETs of generic job pages use httpx's own default user agent.
        self.plain = httpx.Client(timeout=30.0, follow_redirects=True)
        self._pw = None
        self._browser = None
        self._context = None

    # ---------- JSON feeds ----------

    def get_text(self, url):
        """GET a URL. Returns (status, text). Raises Transient or Blocked."""
        self.gate.before(url)
        log(f"  GET {url}")
        try:
            r = self.http.get(url)
        except httpx.TimeoutException:
            raise Transient(f"timed out fetching {url}")
        except httpx.HTTPError as e:
            raise Transient(f"network error fetching {url} ({type(e).__name__})")
        finally:
            self.gate.after(url)
        if r.status_code == 429 or r.status_code >= 500:
            raise Transient(f"{url} returned HTTP {r.status_code}")
        if r.status_code in (401, 403):
            raise Blocked(f"{url} refused the request with HTTP {r.status_code}")
        return r.status_code, r.text

    def get_page(self, url):
        """Plain HTTP GET of a job page, read without running any JavaScript.

        Raises Transient (worth one retry) or Blocked (refusal; never routed around).
        """
        self.gate.before(url)
        log(f"  GET {url} (plain HTTP)")
        try:
            r = self.plain.get(url)
        except httpx.TimeoutException:
            raise Transient(f"timed out fetching {url} over plain HTTP")
        except httpx.HTTPError as e:
            raise Transient(f"network error fetching {url} over plain HTTP ({type(e).__name__})")
        finally:
            self.gate.after(url)
        if r.status_code == 429 or r.status_code >= 500:
            raise Transient(f"{url} returned HTTP {r.status_code}")
        if r.status_code in (401, 403, 406):
            raise Blocked(f"{url} refused a plain HTTP request with HTTP {r.status_code}")
        facts, posting = parse_html(r.text if "html" in r.headers.get("content-type", "html") else "")
        snap = PageSnapshot(
            url=url, status=r.status_code, final_url=str(r.url), title=facts.title, text=facts.text,
            settled=True, headings=facts.heads[:6], h1=facts.h1, has_apply=facts.has_apply,
            job_posting=posting, og_title=facts.og_title, via="plain HTTP",
        )
        _raise_if_bot_check(snap)
        return snap

    # ---------- Browser ----------

    def _new_page(self):
        if self._pw is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._context = self._browser.new_context()
        return self._context.new_page()

    def load(self, url, extract=None):
        """Navigate to url, wait for the network to settle (30 s cap), snapshot it.

        `extract(page)` may read more from the page before it closes.
        Raises Transient on load failure, Blocked on a bot check.
        """
        page = self._new_page()
        self.gate.before(url)
        log(f"  LOAD {url}")
        try:
            start = time.monotonic()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_CAP_SECONDS * 1000)
            except PlaywrightTimeout:
                raise Transient(f"timed out loading {url}")
            except PlaywrightError as e:
                first = str(e).splitlines()[0] if str(e) else type(e).__name__
                raise Transient(f"the browser could not load {url} ({first})")
            settled = False
            left = PAGE_CAP_SECONDS - (time.monotonic() - start)
            if left > 0:
                try:
                    page.wait_for_load_state("networkidle", timeout=left * 1000)
                    settled = True
                except PlaywrightTimeout:
                    pass
            # JavaScript apps (Workday) can go network-quiet before drawing anything.
            # If the page is still nearly empty, wait for text, within the same cap.
            left = PAGE_CAP_SECONDS - (time.monotonic() - start)
            if left > 0 and (resp is None or resp.status < 400):
                try:
                    page.wait_for_function("() => document.body && document.body.innerText.trim().length > 200", timeout=left * 1000)
                except PlaywrightTimeout:
                    settled = False
            status = resp.status if resp else None
            text = page.inner_text("body") if page.query_selector("body") else ""
            facts = page.evaluate(PAGE_FACTS_JS)
            snap = PageSnapshot(
                url=url,
                status=status,
                final_url=page.url,
                title=page.title() or "",
                text=text,
                settled=settled,
                headings=facts["heads"],
                h1=facts["h1"],
                has_apply=bool(facts["hasApply"]),
                job_posting=find_job_posting(facts.get("ld") or []),
                og_title=" ".join((facts.get("ogTitle") or "").split()),
            )
            if extract is not None:
                snap.extra = extract(page)
        finally:
            self.gate.after(url)
            page.close()

        if snap.final_url.startswith("chrome-error://"):
            raise Transient(f"the browser could not load {url} (network error page)")
        if status in (429, 503):
            raise Transient(f"{url} returned HTTP {status}")
        if status in (403, 406):
            raise Blocked(f"{url} refused the browser with HTTP {status} (bot check or block)")
        _raise_if_bot_check(snap)
        return snap

    def close(self):
        try:
            self.http.close()
            self.plain.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def _raise_if_bot_check(snap):
    low = (snap.title + "\n" + snap.text[:3000]).lower()
    if len(snap.text) < 3000 and any(m in low for m in BOT_MARKERS):
        raise Blocked(f"{snap.url} showed a bot check instead of the page")
