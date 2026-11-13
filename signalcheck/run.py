"""Check every job group by group, then write the results files."""

import csv
import io
import json
import time
from datetime import datetime
from pathlib import Path

from .detect import detect
from .inputs import load_jobs
from .systems import check_ashby, check_greenhouse, check_lever, check_page, verdict
from .web import Blocked, Transient, log

RETRY_AFTER_SECONDS = 60
RESULT_KEYS = ("id", "company", "title", "url")
CSV_COLUMNS = ("verdict", "company", "title", "url", "evidence", "observedTitle", "observedLocation",
               "observedBand", "reason", "system", "id", "checkedAt")


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_boards(path=None):
    """Optional {"host": "greenhouse-token"} map for company-hosted Greenhouse links (?gh_jid=)."""
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object of host to Greenhouse token")
    return {str(k).lower(): str(v) for k, v in data.items()}


def group_rows(rows, boards):
    """One group per company board/feed; one group per page otherwise. Input order kept."""
    groups = {}
    for row in rows:
        d = detect(row.get("url", ""), boards)
        row["_detect"] = d
        if d["system"] in ("greenhouse", "ashby", "lever"):
            key = (d["system"], d["token"] or f"?{row['id']}")
        else:
            key = ("page", row["id"])
        groups.setdefault(key, []).append(row)
    return groups


def run_group(web, key, rows):
    system, token = key
    if system == "greenhouse":
        return check_greenhouse(web, None if token.startswith("?") else token, rows)
    if system == "ashby":
        return check_ashby(web, token, rows)
    if system == "lever":
        return check_lever(web, token, rows)
    return check_page(web, rows)


def all_cant_tell(rows, reason):
    return {r["id"]: verdict(r, "CANT_TELL", "none", reason) for r in rows}


def check_rows(rows, boards, web):
    groups = group_rows(rows, boards)
    verdicts, retries = {}, []

    def attempt(key, grows, final):
        label = f"{key[0]}:{key[1]}"
        try:
            return run_group(web, key, grows)
        except Blocked as e:
            log(f"  blocked: {e}")
            return all_cant_tell(grows, f"Bot check or refusal, not bypassed: {e}.")
        except Transient as e:
            if final:
                log(f"  failed again: {e}")
                return all_cant_tell(grows, f"Failed twice (second try after {RETRY_AFTER_SECONDS}+ s): {e}.")
            log(f"  will retry {label} once: {e}")
            retries.append((time.monotonic(), key, grows))
            return {}
        except Exception as e:  # a bug in one group must not sink the whole run
            log(f"  error on {label}: {e!r}")
            return all_cant_tell(grows, f"SignalCheck error ({type(e).__name__}: {e}).")

    for key, grows in groups.items():
        log(f"[{key[0]}] {key[1]} ({len(grows)} job{'s' if len(grows) > 1 else ''})")
        verdicts.update(attempt(key, grows, final=False))

    for failed_at, key, grows in list(retries):
        wait = failed_at + RETRY_AFTER_SECONDS - time.monotonic()
        if wait > 0:
            log(f"waiting {wait:.0f} s before retrying {key[0]}:{key[1]}")
            time.sleep(wait)
        log(f"[retry {key[0]}] {key[1]}")
        verdicts.update(attempt(key, grows, final=True))

    results = []
    for row in rows:
        res = {k: row.get(k, "") for k in RESULT_KEYS}
        res["system"] = row["_detect"]["system"]
        res.update(verdicts[row["id"]])
        res["checkedAt"] = now_iso()
        results.append(res)
    return results


def counts(results):
    c = {"LIVE": 0, "GONE": 0, "CHANGED": 0, "CANT_TELL": 0}
    for r in results:
        c[r["verdict"]] += 1
    return c


def summary_line(day, c, n):
    parts = [f"{n} checked", f"{c['LIVE']} live", f"{c['GONE']} gone"]
    if c["CHANGED"]:
        parts.append(f"{c['CHANGED']} changed")
    parts.append(f"{c['CANT_TELL']} can't tell")
    return f"signalcheck {day}: " + ", ".join(parts)


def label(r):
    return ", ".join(x for x in (f"**{r['company']}**" if r["company"] else "", r["title"]) if x) or r["url"]


def render_md(day, doc):
    c, res = doc["counts"], doc["results"]
    lines = [f"# SignalCheck {day}", "", f"Run at {doc['runAt']} from `{doc['input']}`.", "",
             f"**{len(res)} checked:** {c['LIVE']} live, {c['GONE']} gone, {c['CHANGED']} changed, {c['CANT_TELL']} can't tell.", ""]
    for heading, kinds in (("Gone and changed", ("GONE", "CHANGED")), ("Can't tell", ("CANT_TELL",)), ("Live", ("LIVE",))):
        rows = [r for r in res if r["verdict"] in kinds]
        lines += [f"## {heading}", ""]
        if not rows:
            lines += ["None.", ""]
            continue
        for r in rows:
            lines.append(f"- {label(r)}: {r['verdict']} ({r['evidence']}). {r['reason']} <{r['url']}>")
        lines.append("")
    return "\n".join(lines)


def render_csv(results):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in results:
        w.writerow(r)
    return buf.getvalue()


def write_results(out_dir, doc):
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    day = doc["runAt"][:10]
    body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    files = {
        out / f"{day}.json": body,
        out / "latest.json": body,
        out / f"{day}.md": render_md(day, doc),
        out / "latest.csv": render_csv(doc["results"]),
    }
    for f, text in files.items():
        f.write_text(text)
    return list(files)


def run(input_path, out_dir="results", boards_path=None, web_factory=None):
    jobs, input_label = load_jobs(input_path)
    boards = load_boards(boards_path)
    log(f"Checking {len(jobs)} jobs from {input_label}")
    run_at = now_iso()
    if web_factory is None:
        from .web import Web as web_factory
    web = web_factory()
    try:
        results = check_rows(jobs, boards, web)
    finally:
        web.close()

    doc = {"runAt": run_at, "input": input_label, "counts": counts(results), "results": results}
    files = write_results(out_dir, doc)
    log(summary_line(run_at[:10], doc["counts"], len(results)))
    for f in files:
        log(f"wrote {f}")
    return 0


def one(url, boards_path=None, web_factory=None):
    row = {"id": "one", "company": "", "title": "", "url": url}
    if web_factory is None:
        from .web import Web as web_factory
    web = web_factory()
    try:
        (result,) = check_rows([row], load_boards(boards_path), web)
    finally:
        web.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
