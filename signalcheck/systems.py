"""Per-system checks. Each takes the rows for one group and returns verdicts.

A group is one company's board or feed (so one read settles every row for it),
or a single posting page for Workday, Gem and generic sites.

Verdict functions are kept separate from fetching so the evidence rules can be
tested offline (see tests/).
"""

import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .detect import GREENHOUSE_HOSTS, strip_site_suffix, title_differs
from .web import Blocked, Transient, log


def verdict(row, verdict, evidence, reason, **observed):
    out = {
        "verdict": verdict,
        "evidence": evidence,
        "observedTitle": observed.get("title") or "",
        "observedLocation": observed.get("location") or "",
        "observedBand": observed.get("band") or "",
        "boardCount": observed.get("board_count"),
        "reason": reason,
    }
    if verdict == "LIVE" and title_differs(row.get("title"), out["observedTitle"]):
        out["verdict"] = "CHANGED"
        out["reason"] = f'{reason} Title changed: saved as "{row.get("title")}", now "{out["observedTitle"]}".'
    return out


def req_page_title(snap, company=""):
    """The posting title from a single page, or "" (then the title check is skipped).

    Only structured sources count: JSON-LD JobPosting `title`, else og:title with
    a trailing " | Company" / " - Company" removed. Headings and <title> are
    not used: generic pages put things like "job details" or "Why This Role" there.
    """
    ld = (snap.job_posting or {}).get("title")
    if isinstance(ld, str) and ld.strip():
        return " ".join(html.unescape(ld).split())  # some sites send "&amp;" inside JSON-LD
    if snap.og_title:
        return strip_site_suffix(html.unescape(snap.og_title), company)
    return ""


# ======================= Greenhouse =======================

GH_LINKS_JS = """els => els.map(a => {
  const t = a.querySelector('p.body--medium') || a;
  let title = Array.from(t.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
  if (!title) title = ((t.innerText || '').split('\\n')[0] || '').trim();
  const loc = a.querySelector('p.body__secondary');
  return {href: a.href, title: title.replace(/\\s+/g, ' '), location: loc ? (loc.innerText || '').trim() : ''};
})"""

GH_EMPTY_MARKERS = ("no jobs that fit", "there are no jobs", "no open positions", "no current openings")
MAX_BOARD_PAGES = 60


class BoardError(Exception):
    """The board could not be read to the end: CANT_TELL."""


@dataclass
class BoardRead:
    token: str
    jobs: dict  # job id -> {"title", "location"}
    header: int | None
    pages: int


def parse_header_count(text):
    m = re.search(r"\b(\d[\d,]*)\s+jobs?\b", text or "", re.I)
    return int(m.group(1).replace(",", "")) if m else None


def read_greenhouse_board(web, token):
    """Read every page of the rendered board at job-boards.greenhouse.io/{token}."""
    base = f"https://job-boards.greenhouse.io/{token}"
    jobs, header = {}, None
    for n in range(1, MAX_BOARD_PAGES + 1):
        url = base if n == 1 else f"{base}?page={n}"
        snap = web.load(url, extract=lambda p: p.eval_on_selector_all("a[href*='/jobs/']", GH_LINKS_JS))
        if snap.status and snap.status >= 400:
            raise BoardError(f"the rendered Greenhouse board page {n} returned HTTP {snap.status}")
        final = urlparse(snap.final_url)
        if (final.hostname or "").lower() not in GREENHOUSE_HOSTS or not final.path.lower().rstrip("/").startswith(f"/{token}"):
            raise BoardError(f"the Greenhouse board redirected to {snap.final_url} with no listing")
        if header is None:
            header = parse_header_count(snap.text)

        links, new = 0, 0
        for link in snap.extra or []:
            u = urlparse(link["href"])
            m = re.search(r"/jobs/(\d+)", u.path)
            if not m or (u.hostname or "").lower() not in GREENHOUSE_HOSTS:
                continue
            links += 1
            if m.group(1) not in jobs:
                jobs[m.group(1)] = {"title": link["title"], "location": link["location"]}
                new += 1

        if new:
            continue
        # This page added nothing. That ends the board only if the page clearly
        # rendered: either it repeated jobs we already have, or it shows the
        # board's own "no jobs" message.
        empty_msg = any(m in snap.text.lower() for m in GH_EMPTY_MARKERS)
        if links or empty_msg or (n == 1 and header == 0):
            return BoardRead(token, jobs, header, n)
        if not snap.settled:
            raise Transient(f"Greenhouse board page {n} never finished loading")
        raise BoardError(f"Greenhouse board page {n} rendered neither jobs nor the end-of-list message")
    raise BoardError(f"stopped after {MAX_BOARD_PAGES} board pages without reaching the end")


def greenhouse_verdicts(rows, board):
    """Evidence rules for Greenhouse. Never uses the req page."""
    collected = len(board.jobs)
    count = {"header": board.header, "collected": collected}
    header_txt = f"header {board.header}" if board.header is not None else "no header count"
    out = {}
    for row in rows:
        jid = row["_detect"]["job_id"]
        if jid in board.jobs:
            j = board.jobs[jid]
            out[row["id"]] = verdict(
                row, "LIVE", "board",
                f"Req {jid} is listed on the rendered Greenhouse board for {board.token} "
                f"({board.pages} pages read, {collected} jobs, {header_txt}).",
                title=j["title"], location=j["location"], board_count=count,
            )
        elif board.header is not None and collected < board.header:
            out[row["id"]] = verdict(
                row, "CANT_TELL", "none",
                f"Req {jid} was not found, but the board header says {board.header} jobs and only "
                f"{collected} were collected across {board.pages} pages, so absence is not proven.",
                board_count=count,
            )
        else:
            out[row["id"]] = verdict(
                row, "GONE", "board",
                f"Read all {board.pages} pages of the rendered Greenhouse board for {board.token} "
                f"({collected} jobs, {header_txt}); req {jid} is not listed.",
                board_count=count,
            )
    return out


def check_greenhouse(web, token, rows):
    if not token:
        return {r["id"]: verdict(r, "CANT_TELL", "none", "Unknown Greenhouse token: this company-hosted link needs an entry in the --boards file.") for r in rows}
    try:
        board = read_greenhouse_board(web, token)
    except BoardError as e:
        return {r["id"]: verdict(r, "CANT_TELL", "none", f"Could not read the whole board: {e}.") for r in rows}
    return greenhouse_verdicts(rows, board)


# ======================= Ashby =======================

def ashby_verdicts(rows, org, data):
    jobs = data["jobs"]
    by_id = {str(j.get("id", "")).lower(): j for j in jobs}
    out = {}
    for row in rows:
        jid = row["_detect"]["job_id"]
        j = by_id.get(jid)
        if j is None:
            why = "the feed is a valid empty list" if not jobs else f"the posting is not among its {len(jobs)} jobs"
            out[row["id"]] = verdict(row, "GONE", "feed", f"Parsed the full Ashby feed for {org}; {why}.")
            continue
        comp = j.get("compensation") or {}
        band = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary") or ""
        if j.get("isListed") is False:
            out[row["id"]] = verdict(row, "CANT_TELL", "feed", f"The posting is in the Ashby feed for {org} but marked unlisted.",
                                     title=j.get("title"), location=j.get("location"), band=band)
            continue
        out[row["id"]] = verdict(row, "LIVE", "feed", f"Listed in the fully parsed Ashby feed for {org} ({len(jobs)} jobs).",
                                 title=j.get("title"), location=j.get("location"), band=band)
    return out


def check_ashby(web, org, rows):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
    status, text = web.get_text(url)
    if status != 200:
        return {r["id"]: verdict(r, "CANT_TELL", "none", f"The Ashby feed for {org} returned HTTP {status}.") for r in rows}
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("no jobs list")
    except ValueError as e:
        return {r["id"]: verdict(r, "CANT_TELL", "none", f"The Ashby feed for {org} did not parse as a complete job list ({e}).") for r in rows}
    return ashby_verdicts(rows, org, data)


# ======================= Lever =======================

def lever_band(j):
    sr = j.get("salaryRange") or {}
    if sr.get("min") and sr.get("max"):
        interval = (sr.get("interval") or "").replace("per-", "").replace("-salary", "")
        return f"{sr.get('currency', '')} {sr['min']:,}–{sr['max']:,} {interval}".strip()
    return (j.get("salaryDescriptionPlain") or "").strip()[:200]


def same_posting(a, b):
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname or "").lower() == (pb.hostname or "").lower() and pa.path.rstrip("/").lower() == pb.path.rstrip("/").lower()


def lever_second_look(row, snap, org, n_jobs):
    """The posting is absent from the feed. Decide from the posting page."""
    base = f"Not in the fully parsed Lever feed for {org} ({n_jobs} postings)"
    if snap.status in (404, 410):
        return verdict(row, "GONE", "feed", f"{base}, and the posting page returns HTTP {snap.status}.")
    if not same_posting(snap.url, snap.final_url):
        return verdict(row, "GONE", "feed", f"{base}, and the posting page redirects to {snap.final_url}.")
    shows_title = row.get("title") and row["title"].lower() in snap.text.lower()
    if snap.has_apply or shows_title:
        return verdict(row, "CANT_TELL", "req_page", "Absent from Lever feed but page still renders.",
                       title=req_page_title(snap, row.get("company", "")))
    return verdict(row, "CANT_TELL", "none", f"{base}; the posting page loaded but showed neither a closure notice nor the posting.")


def check_lever(web, org, rows):
    url = f"https://api.lever.co/v0/postings/{org}?mode=json"
    status, text = web.get_text(url)
    if status != 200:
        return {r["id"]: verdict(r, "CANT_TELL", "none", f"The Lever feed for {org} returned HTTP {status}.") for r in rows}
    try:
        jobs = json.loads(text)
        if not isinstance(jobs, list):
            raise ValueError("not a list of postings")
    except ValueError as e:
        return {r["id"]: verdict(r, "CANT_TELL", "none", f"The Lever feed for {org} did not parse completely ({e}).") for r in rows}
    by_id = {str(j.get("id", "")).lower(): j for j in jobs}
    out = {}
    for row in rows:
        j = by_id.get(row["_detect"]["job_id"])
        if j is not None:
            cats = j.get("categories") or {}
            out[row["id"]] = verdict(row, "LIVE", "feed", f"Listed in the fully parsed Lever feed for {org} ({len(jobs)} postings).",
                                     title=j.get("text"), location=cats.get("location"), band=lever_band(j))
        else:
            out[row["id"]] = lever_second_look(row, web.load(row["url"]), org, len(jobs))
    return out


# ======================= Workday, Gem, generic pages =======================

CLOSURE_PHRASES = (
    "no longer available",
    "no longer accepting",
    "no longer open",
    "not found",
    "has expired",
    "doesn't exist",
    "does not exist",
    "has been filled",
    "has been removed",
    "position is closed",
    "job is closed",
    "posting has closed",
)
MIN_POSTING_CHARS = 1000


def closure_phrase(snap):
    """The closure phrase the page shows (in its title or headings, or anywhere
    in a short page), or None."""
    head_text = (snap.title + "\n" + "\n".join(snap.headings)).lower()
    short = len(snap.text) < 3000
    for phrase in CLOSURE_PHRASES:
        if phrase in head_text or (short and phrase in snap.text.lower()):
            return phrase
    return None


def page_verdict(row, snap):
    """Decide from one posting page, read either over plain HTTP or in the browser."""
    src = "Plain HTTP GET" if snap.via == "plain HTTP" else "Browser load"
    status_txt = f"HTTP {snap.status}" if snap.status else "no status"
    if snap.status in (404, 410):
        return verdict(row, "GONE", "req_page", f"{src}: the posting page returned {status_txt}.")

    orig, final = urlparse(snap.url), urlparse(snap.final_url)
    if not same_posting(snap.url, snap.final_url):
        fpath = final.path.rstrip("/").lower()
        opath = orig.path.rstrip("/").lower()
        if fpath == "" or "search" in fpath or (opath.startswith(fpath) and fpath != opath):
            return verdict(row, "GONE", "req_page", f"{src}: the posting page redirected to a search or home page ({snap.final_url}).")

    phrase = closure_phrase(snap)
    if phrase:
        return verdict(row, "GONE", "req_page", f'{src}: the posting page loaded ({status_txt}) and says "{phrase}".')

    posting_signal = "an apply control" if snap.has_apply else ("schema.org JobPosting data" if snap.job_posting else "")
    if posting_signal and len(snap.text) >= MIN_POSTING_CHARS:
        return verdict(row, "LIVE", "req_page",
                       f"{src}: the posting page has a full posting ({len(snap.text):,} characters) with {posting_signal}. "
                       "Single page only: weak evidence.",
                       title=req_page_title(snap, row.get("company", "")))

    settled = "" if snap.settled else ", and the network never settled within 30 seconds"
    return verdict(row, "CANT_TELL", "none",
                   f"{src}: the posting page loaded ({status_txt}) but showed no posting body "
                   f"({len(snap.text):,} characters, {'an' if snap.has_apply else 'no'} apply control{settled}).")


def check_page(web, rows):
    """Generic pages: plain HTTP first; the browser only if the HTML is a JavaScript shell.
    Workday and Gem are JavaScript apps, so they go straight to the browser."""
    (row,) = rows
    if row["_detect"]["system"] == "listing_site":
        site = row["_detect"]["token"]
        return {row["id"]: verdict(
            row, "CANT_TELL", "none",
            f"{site} link: SignalCheck doesn't read job listing sites (they need a sign-in and don't reliably show "
            "whether the employer's job is still open). Not fetched. Use the company's own posting link instead.")}
    if row["_detect"]["system"] == "generic":
        plain = web.get_page(row["url"])
        v = page_verdict(row, plain)
        phrase = closure_phrase(plain) if v["verdict"] == "GONE" else None
        if phrase:
            # Some sites serve a false "has been filled" page to non-browser
            # requests. A closure notice over plain HTTP is only a lead: GONE
            # needs the browser load to agree.
            log(f'  plain HTML says "{phrase}"; confirming in the browser')
            bv = page_verdict(row, web.load(row["url"]))
            if bv["verdict"] != "GONE":
                bv["reason"] += f' (A plain HTTP GET showed "{phrase}", but the browser load did not.)'
            return {row["id"]: bv}
        if v["verdict"] != "CANT_TELL":
            return {row["id"]: v}
        log("  plain HTML has no posting (JavaScript shell); loading in the browser")
    return {row["id"]: page_verdict(row, web.load(row["url"]))}


__all__ = ["Blocked", "Transient", "check_greenhouse", "check_ashby", "check_lever", "check_page"]
