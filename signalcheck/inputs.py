"""Read the list of saved jobs to check.

Three formats, picked by file extension:

- .txt   one URL per line. Blank lines and lines starting with # are skipped.
- .csv   a header row with a `url` (or `link`) column. Optional columns:
         `company`, `title`, `id`. Other columns are ignored.
- .json  a list of objects with at least `url` (or {"jobs": [...]}).
         Optional keys: `company`, `title`, `id`.

`title` is optional, but when it is given SignalCheck also reports when the
posting's title has changed (verdict CHANGED).

A job without an `id` gets one made from its URL, so the same job keeps the
same id from run to run. A URL listed twice is checked once.
"""

import csv
import hashlib
import json
from pathlib import Path


class InputError(ValueError):
    pass


def job_id(url):
    return "u" + hashlib.sha1(url.encode()).hexdigest()[:10]


def _clean(raw, where):
    url = str(raw.get("url") or raw.get("link") or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        raise InputError(f"{where}: not a web address: {url[:80]}")
    return {
        "id": str(raw.get("id") or "").strip() or job_id(url),
        "company": str(raw.get("company") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "url": url,
    }


def _from_txt(text):
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            yield n, {"url": line}


def _from_csv(text):
    reader = csv.DictReader(text.splitlines())
    fields = {(f or "").strip().lower(): f for f in reader.fieldnames or []}
    if "url" not in fields and "link" not in fields:
        raise InputError("the CSV needs a header row with a 'url' column")
    for n, rec in enumerate(reader, 2):
        yield n, {k: rec.get(orig) for k, orig in fields.items()}


def _from_json(text):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InputError(f"not valid JSON ({e})") from None
    if isinstance(data, dict):
        data = data.get("jobs")
    if not isinstance(data, list):
        raise InputError("the JSON must be a list of jobs, or an object with a 'jobs' list")
    for n, rec in enumerate(data, 1):
        if not isinstance(rec, dict):
            raise InputError(f"item {n} is not an object with a 'url'")
        yield n, {str(k).lower(): v for k, v in rec.items()}


def load_jobs(path):
    """Return (jobs, label). Raises InputError with a plain reason."""
    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    ext = p.suffix.lower()
    readers = {".txt": _from_txt, ".csv": _from_csv, ".json": _from_json}
    if ext not in readers:
        raise InputError(f"use a .txt, .csv or .json file (got '{ext or 'no extension'}')")

    jobs, seen_urls, seen_ids = [], set(), set()
    unit = "line" if ext != ".json" else "item"
    for n, raw in readers[ext](text):
        job = _clean(raw, f"{p.name} {unit} {n}")
        if not job or job["url"] in seen_urls:
            continue
        if job["id"] in seen_ids:
            raise InputError(f"{p.name} {unit} {n}: id '{job['id']}' is used twice")
        seen_urls.add(job["url"])
        seen_ids.add(job["id"])
        jobs.append(job)
    if not jobs:
        raise InputError(f"no job URLs found in {path}")
    return jobs, str(path)
