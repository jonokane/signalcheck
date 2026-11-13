"""Work out which job system a URL belongs to, and compare titles."""

import re
from urllib.parse import parse_qs, urlparse

GREENHOUSE_HOSTS = {"job-boards.greenhouse.io", "boards.greenhouse.io"}

# Sites that list other companies' jobs. They need a sign-in, forbid automated
# reading, and don't reliably show whether the employer's job is still open, so
# SignalCheck never fetches them. Matched on the host and every parent domain.
LISTING_SITES = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "monster.com": "Monster",
    "simplyhired.com": "SimplyHired",
    "dice.com": "Dice",
    "wellfound.com": "Wellfound",
    "builtin.com": "Built In",
}


def listing_site(host):
    """The listing site's name if host is (a subdomain of) one, else None.
    Country domains count too: uk.indeed.com, glassdoor.co.uk, linkedin.cn."""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        name = ".".join(parts[i:])
        if name in LISTING_SITES:
            return LISTING_SITES[name]
        rest = parts[i + 1:]
        country = rest and len(rest) <= 2 and all(len(x) <= 3 for x in rest) and rest[-1] != "com"
        if country:  # glassdoor.co.uk, indeed.de, linkedin.cn (not linkedin.com.evil.io)
            for site, label in LISTING_SITES.items():
                if site.split(".")[0] == parts[i]:
                    return label
    return None


def detect(url, boards):
    """Return {"system", "token", "job_id"} for a posting URL.

    `boards` maps a company host to its Greenhouse token, for company-hosted
    links that carry ?gh_jid=. A missing mapping gives token None.
    """
    u = urlparse((url or "").strip())
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    query = parse_qs(u.query)

    site = listing_site(host)
    if site:
        return {"system": "listing_site", "token": site, "job_id": None}
    if host in GREENHOUSE_HOSTS and len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
        return {"system": "greenhouse", "token": parts[0].lower(), "job_id": parts[2]}
    if "gh_jid" in query and query["gh_jid"][0].isdigit():
        token = boards.get(host) or boards.get(host.removeprefix("www."))
        return {"system": "greenhouse", "token": token, "job_id": query["gh_jid"][0]}
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return {"system": "ashby", "token": parts[0], "job_id": parts[1].lower()}
    if host == "jobs.lever.co" and len(parts) >= 2:
        return {"system": "lever", "token": parts[0], "job_id": parts[1].lower()}
    if host.endswith(".myworkdayjobs.com"):
        return {"system": "workday", "token": None, "job_id": None}
    if host == "jobs.gem.com" and len(parts) >= 2:
        return {"system": "gem", "token": None, "job_id": None}
    return {"system": "generic", "token": None, "job_id": None}


BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def norm_title(s):
    """Anything in (parentheses) or [square brackets] removed, lowercase,
    '&' -> 'and', punctuation stripped, whitespace collapsed.

    Tracker titles carry extras like "(100% remote, US only)"; those are not
    part of the job title.
    """
    s = s or ""
    prev = None
    while prev != s:  # nested brackets, innermost first
        prev, s = s, BRACKETED.sub(" ", s)
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]|_", " ", s)
    return " ".join(s.split())


def title_differs(saved, observed):
    """True when the observed title differs from the saved one after norm_title.

    Exact comparison only. No substring containment: "Senior Principal Product
    Manager" vs "Principal Product Manager" is a real change.
    """
    a, b = norm_title(saved), norm_title(observed)
    return bool(a and b and a != b)


SUFFIX = re.compile(r"\s+[|\-–—]\s+([^|\-–—]+)$")
SITE_WORDS = ("career", "jobs", "hiring", "job board")


def strip_site_suffix(title, company=""):
    """Drop a trailing " | Company" or " - Company" from an og:title.

    Only drops the last segment when it names the company or is plainly a site
    name ("Careers", "Jobs"), so "Product Designer - Growth" keeps "Growth".
    """
    title = " ".join((title or "").split())
    co = norm_title(company)
    while True:
        m = SUFFIX.search(title)
        if not m:
            return title
        last = norm_title(m.group(1))
        names_company = bool(co and last and (co in last or last in co))
        if not (names_company or any(w in last for w in SITE_WORDS)):
            return title
        title = title[: m.start()].rstrip()
