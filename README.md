# SignalCheck

Is that job posting really still open?

SignalCheck takes your list of saved job postings and checks each one against the source that actually knows: the company's full job board or feed, not the posting page. It tells you which jobs are still open, which have closed, and which have been retitled, so you don't spend an evening on an application for a job that's already gone.

No AI, no accounts, no sign-ins. It reads public pages the way a person would, slowly, and never clicks Apply.

## Why the posting page isn't enough

A job page that still loads, with an Apply button, does not mean the job is open:

- **Greenhouse** keeps serving closed and unlisted postings in full, Apply button and all. The only reliable answer is whether the job is still listed on the company's board.
- **Workday, Gem, iCIMS** and many careers sites build the page with JavaScript, so a simple fetch sees an empty page.
- **Some sites** show "this position has been filled" to automated requests while the posting is open in a real browser.
- **Large Ashby and Lever feeds** are cut off by tools that only read the first part of a page, so "not found" proves nothing.

SignalCheck handles each case on purpose. When it can't prove an answer, it says "can't tell" and why, rather than guessing.

## What you get

For every job, one of four verdicts:

| Verdict | Meaning |
|---|---|
| `LIVE` | Still open. |
| `GONE` | Closed: absent from a board or feed that was read completely, or the page shows a clear closure (confirmed in a real browser). |
| `CHANGED` | Still open, but the title is different from the one you saved. Only checked when your list includes titles. |
| `CANT_TELL` | Not provable either way, with the reason: a bot check, a board that wouldn't load fully, a page with no posting on it. |

Each verdict comes with an **evidence grade**, so you know how much to trust it:

| Evidence | What was read |
|---|---|
| `board` | The company's full Greenhouse job board, every page |
| `feed` | The company's complete Ashby or Lever job feed |
| `req_page` | Only the posting page itself (Workday, Gem and other sites). Good, but weaker. |
| `none` | Nothing conclusive |

And a plain-English `reason`, for example: *"Read all 3 pages of the rendered Greenhouse board for acme (61 jobs, header 61); req 4000000001 is not listed."*

## Install

You need Python 3.11 or later. Check with `python3 --version`. Macs come with an older Python, so if yours says 3.9 or 3.10, install the current version from [python.org](https://www.python.org/downloads/) (or `brew install python` if you use Homebrew), then open a new Terminal window.

Tested on macOS 15. Linux and Windows should work, since everything SignalCheck uses runs there, but haven't been tried yet.

```sh
python3 -m venv ~/.signalcheck
~/.signalcheck/bin/pip install git+https://github.com/jonokane/signalcheck
~/.signalcheck/bin/playwright install chromium
```

The last line downloads the headless browser SignalCheck uses for JavaScript-built pages (about 150 MB, once). Add `~/.signalcheck/bin` to your PATH, or call `~/.signalcheck/bin/signalcheck` directly.

## Use

**1. Make a list** of the jobs you've saved. Any of these work:

- `jobs.txt`: one URL per line.
- `jobs.csv`: a spreadsheet saved as CSV with a `url` column, and optionally `company` and `title`. Other columns are ignored, so you can export your existing tracker.
- `jobs.json`: a list of `{"url": ..., "company": ..., "title": ...}`.

See [examples/](examples/). Include titles if you want to hear when a job is retitled.

Save the **employer's own posting link** (Greenhouse, Ashby, Lever, Workday or the company's careers site), not a LinkedIn or Indeed link. SignalCheck can't check listing sites. **[Tailoring SignalCheck to your search](docs/tailoring.md)** covers which links work best, using your own tracker as the input, keeping separate daily and weekly lists, and what to do with each verdict.

**2. Run it:**

```sh
signalcheck run jobs.csv
```

It works through the list politely, a few seconds between requests to the same site, so a list of 50 jobs takes several minutes.

**3. Read the results** in `results/`:

| File | What it is |
|---|---|
| `latest.csv` | Every job with its verdict. Open it in any spreadsheet. |
| `YYYY-MM-DD.md` | A readable summary: closed and changed first, then can't-tell, then live |
| `latest.json`, `YYYY-MM-DD.json` | Everything, for other tools |

**Other commands:**

```sh
signalcheck one https://jobs.ashbyhq.com/acme/...   # check a single link, print the result
signalcheck describe jobs.csv                       # save each job's description as text
```

`describe` writes `results/descriptions.json`: the full text of every posting, cleaned up. Handy for tailoring a cover letter after the posting has been taken down.

## Supported job systems

| System | How SignalCheck checks | Evidence |
|---|---|---|
| Greenhouse (`job-boards.greenhouse.io`, `boards.greenhouse.io`) | Loads the company's board in a browser and reads every page | `board` |
| Greenhouse on a company's own site (`?gh_jid=`) | Same, once you map the site to its Greenhouse board name with `--boards` (see below) | `board` |
| Ashby (`jobs.ashbyhq.com`) | Reads the company's complete public job feed | `feed` |
| Lever (`jobs.lever.co`) | Reads the complete feed; if the job is missing, also checks the posting page, because Lever's feed sometimes leaves out live jobs | `feed` |
| Workday, Gem, and any other careers page | Loads the posting page; uses a real browser when the page needs JavaScript or claims to be closed | `req_page` |
| LinkedIn, Indeed, Glassdoor, ZipRecruiter, Wellfound and other listing sites | Not checked and never contacted: they need a sign-in and don't allow automated reading. Save the company's own link instead. | `CANT_TELL` |

Details for each: [docs/how-it-decides.md](docs/how-it-decides.md).

**Company sites that embed Greenhouse.** Links like `https://www.acme.com/careers?gh_jid=123` don't name the Greenhouse board. Find it once (open the company's careers page; the board name appears in `job-boards.greenhouse.io/<name>` links), then add it to a small JSON file and pass it with `--boards`:

```json
{ "www.acme.com": "acme" }
```

```sh
signalcheck run jobs.csv --boards boards.json
```

## Run it every morning

SignalCheck doesn't schedule itself. Use whatever your computer already has:

- **macOS:** [SignalClaw](https://github.com/jonokane/signalclaw)'s `install.sh` sets up a daily LaunchAgent. It can also text you if a run fails, and lets an OpenClaw assistant answer "did the checker run today?". Pass `--results /path/to/results/latest.json`.
- **macOS or Linux, with cron** (`crontab -e`), every day at 7:00:
  ```
  0 7 * * * cd ~/jobs && ~/.signalcheck/bin/signalcheck run jobs.csv >> signalcheck.log 2>&1
  ```
- **Windows:** create a daily task in Task Scheduler that runs `signalcheck run jobs.csv`, starting in your jobs folder.

When a run fails, the last line of output starts with `FAILED:` and gives the reason, and the exit code is non-zero. Schedulers and alert scripts can rely on that.

## Ground rules SignalCheck follows

- **No AI.** Ordinary code: the same pages always give the same answer, and nothing on a page can talk it into a different one.
- **Read-only.** It never signs in, submits a form, clicks Apply, or solves or gets around a CAPTCHA or bot check. A bot check means `CANT_TELL`.
- **Polite.** One request at a time per site, 2 to 5 seconds apart, and at most one retry, a minute later. The browser uses its normal user agent; it doesn't pretend to be anything else.
- **Honest.** `GONE` needs proof: a board or feed read completely, or a clear closure that a real browser confirms.

Job sites change. If a verdict looks wrong, run `signalcheck one <url>`, read the `reason`, and please open an issue with the URL and what you expected.

## Development

```sh
git clone https://github.com/jonokane/signalcheck && cd signalcheck
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests
```

The tests need no network: they use saved samples and a fake web layer.

## License

MIT. See [LICENSE](LICENSE). SignalCheck is not affiliated with Greenhouse, Ashby, Lever, Workday, Gem or any employer.
