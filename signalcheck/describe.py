"""Save each job's description as plain text, before the posting disappears.

    signalcheck describe FILE [--out DIR]

Same rules as the checker: no AI, read-only, polite, bot checks never
bypassed. The text is only text: nothing here decides whether a job is open.
A Greenhouse description can exist for a req the checker calls GONE (the jobs
API is wrong in both directions), and the reverse.

Writes DIR/descriptions.json.
"""

import html
import json
import time
from datetime import date
from pathlib import Path

from .detect import detect
from .html_page import find_job_posting
from .inputs import load_jobs
from .run import load_boards, now_iso
from .systems import page_verdict
from .text import clean_text, html_to_text, looks_like_html
from .web import Blocked, Transient, log

RETRY_AFTER_SECONDS = 60
MIN_CHARS = 200  # shorter than this is not a job description
MIN_RENDERED_CHARS = 1000  # main text needed when the page shows no apply control (it may sit in an iframe)

SOURCE = {"ashby": "Ashby feed", "lever": "Lever feed", "greenhouse": "Greenhouse",
          "workday": "Workday", "gem": "Gem", "generic": "company page"}


def source_of(d):
    # A company-hosted Greenhouse link without a known token is read as a company page.
    return SOURCE["generic" if d["system"] == "greenhouse" and not d["token"] else d["system"]]


class Skip(Exception):
    """No description for this row; the message is the reason."""


# ======================= Extraction (pure; tested offline) =======================

def usable(text, what):
    if len(text) < MIN_CHARS:
        raise Skip(f"{what} gave only {len(text)} characters of text")
    return text


def ashby_text(job):
    return clean_text(job.get("descriptionPlain") or "")


def lever_text(posting):
    """descriptionPlain, then each list's title and items, then additionalPlain."""
    parts = [clean_text(posting.get("descriptionPlain") or "")]
    for lst in posting.get("lists") or []:
        title = clean_text(lst.get("text") or "")
        items = html_to_text(lst.get("content") or "")
        parts.append("\n".join(p for p in (title, items) if p))
    parts.append(clean_text(posting.get("additionalPlain") or ""))
    return clean_text("\n\n".join(p for p in parts if p))


def greenhouse_text(job):
    """`content` from boards-api: HTML that is entity-escaped once more."""
    return html_to_text(job.get("content") or "")


def jsonld_text(posting):
    d = (posting or {}).get("description") or ""
    if not isinstance(d, str):
        return ""
    if looks_like_html(d) or "&lt;" in d:
        return html_to_text(d)
    return clean_text(html.unescape(d))  # plain text can still carry entities (Workday: "&amp;")


def page_text(row, snap):
    """Text from one posting page (plain HTTP or browser). Raises Skip if gone or empty.

    Returns (text, needs_browser): needs_browser is True when plain HTML had no
    JSON-LD description, so the main text must come from the rendered page.
    """
    v = page_verdict(row, snap)
    if v["verdict"] == "GONE":
        raise Skip(f"page is gone: {v['reason']}")
    ld = jsonld_text(snap.job_posting)
    if len(ld) >= MIN_CHARS:
        return ld, False
    if snap.via == "plain HTTP":
        return "", True
    main = clean_text((snap.extra or {}).get("main") or "")
    # The checker wants an apply control as proof of life; for text we only need the
    # posting itself, and some pages keep the apply form in an iframe.
    if v["verdict"] == "CANT_TELL" and len(main) < MIN_RENDERED_CHARS:
        raise Skip(f"no posting body: {v['reason']}")
    return usable(main, "the rendered page"), False


# ======================= Fetching =======================

# Runs in the page after it has loaded. Reads the JSON-LD, then removes page
# chrome (nav, header, footer, cookie banners) from this local copy of the DOM
# and reads the main posting text. Nothing is clicked, typed or submitted.
MAIN_TEXT_JS = r"""() => {
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.textContent || '');
  const chrome = 'nav, header, footer, aside, [role=navigation], [role=banner], [role=contentinfo], [role=dialog], [aria-modal=true],'
    + ' [id*=cookie i], [class*=cookie i], [id*=consent i], [class*=consent i], [id*=onetrust i], [class*=onetrust i], [id*=gdpr i], [class*=gdpr i],'
    + ' form, button, select, textarea, label, iframe, svg, [role=button], [role=tab], [role=tablist]';
  const keep = e => e === document.body || e === document.documentElement;
  document.querySelectorAll(chrome).forEach(e => { if (!keep(e)) e.remove(); });
  // Icons are aria-hidden; a whole page can be too while a cookie modal is open, so only short ones go.
  document.querySelectorAll('[aria-hidden=true]').forEach(e => { if (!keep(e) && (e.innerText || '').trim().length < 80) e.remove(); });
  // Navigation and share links (the posting's own links stay).
  const navText = /^(apply( now| for this job)?|(view|see|back to)( all)?( open)? (jobs|roles|positions|openings)|share( this job)?|linkedin|facebook|x|twitter|email|link|copy link)$/i;
  const shareHref = /linkedin\.com\/(share|sharing)|facebook\.com\/sharer|(twitter|x)\.com\/intent/i;
  document.querySelectorAll('a').forEach(a => { if (navText.test((a.innerText || '').trim()) || shareHref.test(a.href || '')) a.remove(); });
  const pick = ['[data-automation-id=jobPostingDescription]', 'main', '[role=main]', 'article'];
  let main = '';
  for (const sel of pick) {
    const el = document.querySelector(sel);
    if (el && (el.innerText || '').trim().length > 200) { main = el.innerText; break; }
  }
  if (!main && document.body) main = document.body.innerText;
  return {ld, main};
}"""


def browser_snapshot(web, url):
    snap = web.load(url, extract=lambda p: p.evaluate(MAIN_TEXT_JS))
    snap.job_posting = find_job_posting((snap.extra or {}).get("ld") or [])
    return snap


def describe_page(web, row):
    if row["_detect"]["system"] in ("generic", "greenhouse"):  # greenhouse here = company-hosted, no token
        text, needs_browser = page_text(row, web.get_page(row["url"]))
        if not needs_browser:
            return text
        log("  no JSON-LD description in the plain HTML; reading the rendered page")
    text, _ = page_text(row, browser_snapshot(web, row["url"]))
    return text


def describe_ashby(web, org, rows):
    status, body = web.get_text(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
    if status != 200:
        raise Skip(f"the Ashby feed for {org} returned HTTP {status}")
    try:
        jobs = {str(j.get("id", "")).lower(): j for j in json.loads(body)["jobs"]}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise Skip(f"the Ashby feed for {org} did not parse ({type(e).__name__})")
    out = {}
    for row in rows:
        j = jobs.get(row["_detect"]["job_id"])
        out[row["id"]] = Skip(f"not in the Ashby feed for {org} (gone)") if j is None else _try(usable, ashby_text(j), "the Ashby feed")
    return out


def describe_lever(web, org, rows):
    status, body = web.get_text(f"https://api.lever.co/v0/postings/{org}?mode=json")
    if status != 200:
        raise Skip(f"the Lever feed for {org} returned HTTP {status}")
    try:
        jobs = {str(j.get("id", "")).lower(): j for j in json.loads(body)}
    except (ValueError, TypeError, AttributeError) as e:
        raise Skip(f"the Lever feed for {org} did not parse ({type(e).__name__})")
    out = {}
    for row in rows:
        jid = row["_detect"]["job_id"]
        j = jobs.get(jid)
        if j is None:
            # Lever's list sometimes omits live postings; ask for this one directly.
            status, body = web.get_text(f"https://api.lever.co/v0/postings/{org}/{jid}?mode=json")
            if status != 200:
                out[row["id"]] = Skip(f"not in the Lever feed for {org}, and its posting API returns HTTP {status} (gone)")
                continue
            try:
                j = json.loads(body)
            except ValueError:
                out[row["id"]] = Skip("the Lever posting API response did not parse")
                continue
        out[row["id"]] = _try(usable, lever_text(j), "the Lever feed")
    return out


def describe_greenhouse(web, token, row):
    jid = row["_detect"]["job_id"]
    status, body = web.get_text(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}")
    if status != 200:
        raise Skip(f"Greenhouse's job API returned HTTP {status} for {token} req {jid} (no description; not a liveness verdict)")
    try:
        job = json.loads(body)
    except ValueError:
        raise Skip("Greenhouse's job API response did not parse")
    return usable(greenhouse_text(job), "Greenhouse's job API")


def _try(fn, *args):
    try:
        return fn(*args)
    except Skip as e:
        return e


# ======================= Run =======================

def group_rows(rows, boards):
    """Ashby and Lever: one feed read per company. Everything else: one row per group."""
    groups = {}
    for row in rows:
        d = row["_detect"] = detect(row.get("url", ""), boards)
        if d["system"] in ("ashby", "lever"):
            key = (d["system"], d["token"])
        elif d["system"] == "greenhouse" and d["token"]:
            key = ("greenhouse", d["token"], row["id"])
        else:
            key = ("page", row["id"])
        groups.setdefault(key, []).append(row)
    return groups


def run_group(web, key, rows):
    """Returns {row id: text or Skip}."""
    if key[0] == "ashby":
        return describe_ashby(web, key[1], rows)
    if key[0] == "lever":
        return describe_lever(web, key[1], rows)
    (row,) = rows
    if key[0] == "greenhouse":
        return {row["id"]: describe_greenhouse(web, key[1], row)}
    return {row["id"]: describe_page(web, row)}


def collect(rows, boards, web):
    groups = group_rows(rows, boards)
    got, retries = {}, []

    def attempt(key, grows, final):
        try:
            return run_group(web, key, grows)
        except Skip as e:
            return {r["id"]: e for r in grows}
        except Blocked as e:
            log(f"  blocked: {e}")
            return {r["id"]: Skip(f"blocked (bot check or refusal, not bypassed): {e}") for r in grows}
        except Transient as e:
            if final:
                return {r["id"]: Skip(f"failed twice (second try after {RETRY_AFTER_SECONDS}+ s): {e}") for r in grows}
            log(f"  will retry once: {e}")
            retries.append((time.monotonic(), key, grows))
            return {}
        except Exception as e:  # a bug on one page must not sink the run
            log(f"  error: {e!r}")
            return {r["id"]: Skip(f"describe error ({type(e).__name__}: {e})") for r in grows}

    for key, grows in groups.items():
        log(f"[{key[0]}] {key[1]} ({len(grows)} row{'s' if len(grows) > 1 else ''})")
        got.update(attempt(key, grows, final=False))
    for failed_at, key, grows in retries:
        wait = failed_at + RETRY_AFTER_SECONDS - time.monotonic()
        if wait > 0:
            log(f"waiting {wait:.0f} s before retrying {key[1]}")
            time.sleep(wait)
        log(f"[retry {key[0]}] {key[1]}")
        got.update(attempt(key, grows, final=True))
    return got


def build_doc(rows, got, generated_at, day):
    items, skipped = {}, []
    for row in rows:
        res = got.get(row["id"], Skip("not attempted"))
        if isinstance(res, Skip):
            skipped.append({"id": row["id"], "reason": str(res)})
        else:
            items[row["id"]] = {"url": row["url"], "company": row.get("company", ""), "title": row.get("title", ""),
                                "text": res, "source": source_of(row["_detect"]),
                                "fetchedAt": day}
    return {"generatedAt": generated_at, "items": items, "skipped": skipped}


def describe(input_path, out_dir="results", boards_path=None, web_factory=None):
    rows, label = load_jobs(input_path)
    boards = load_boards(boards_path)
    log(f"Describing {len(rows)} jobs from {label}")
    generated_at = now_iso()
    if web_factory is None:
        from .web import Web as web_factory
    web = web_factory()
    try:
        got = collect(rows, boards, web)
    finally:
        web.close()

    doc = build_doc(rows, got, generated_at, date.today().isoformat())
    out = Path(out_dir).expanduser() / "descriptions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    log(f"descriptions {generated_at[:10]}: {len(doc['items'])} captured, {len(doc['skipped'])} skipped")
    log(f"wrote {out}")
    return 0
