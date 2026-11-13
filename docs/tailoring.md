# Tailoring SignalCheck to your search

SignalCheck doesn't search for jobs. You find them, wherever you look, and SignalCheck tells you which ones are still open. So you tailor it through the list you give it: which jobs go in, which links you save, what you include alongside them, and how often you check.

This guide covers each of those.

## 1. Save the right link

The link you save decides how good the answer is.

**Use the employer's own posting link.** Found the job on LinkedIn or Indeed? Click through to Apply until you reach the company's site, and save that address. It usually looks like one of these:

| You'll see | System | How sure SignalCheck can be |
|---|---|---|
| `job-boards.greenhouse.io/acme/jobs/4000000001` | Greenhouse | Strongest: checks the company's whole board |
| `jobs.ashbyhq.com/acme/...` | Ashby | Strong: reads the complete job feed |
| `jobs.lever.co/acme/...` | Lever | Strong: reads the complete job feed |
| `acme.wd1.myworkdayjobs.com/...` | Workday | Good: reads the posting page |
| `acme.com/careers/...?gh_jid=123` | Greenhouse on the company's site | Strongest, once you add the company to `boards.json` (step 5) |
| `careers.acme.com/jobs/...` | The company's own careers site | Good: reads the posting page |

**Don't save LinkedIn, Indeed, Glassdoor, ZipRecruiter, Wellfound or similar links.** Those sites need a sign-in, don't allow automated reading, and often keep a listing up after the employer has closed the job. SignalCheck recognizes them, doesn't contact them, and marks them `CANT_TELL` with a reminder to use the company's link.

**Save the posting, not the search.** A link to a search results page ("Design jobs in Austin") isn't one job, so there's nothing to check. Open the job itself and save that.

**Tidy links are fine, but not required.** Tracking bits like `?source=linkedin&utm_campaign=...` don't hurt. If the same job is in your list twice with different tracking bits, it's checked twice.

## 2. Use your own tracker as the input

If you already keep a spreadsheet of jobs, you don't need a separate list. Export it as CSV (Google Sheets: File > Download > CSV; Excel: Save As > CSV; Notion and Airtable: Export > CSV) and run SignalCheck on the export.

SignalCheck needs one column, `url` (or `link`). It also uses:

- `company`: makes the results readable.
- `title`: the exact title you saved. With it, SignalCheck also tells you when a job is retitled (`CHANGED`).
- `id`: your own row id, if your tracker has one, so you can match results back to rows. Without it, SignalCheck makes a stable id from the URL.

Every other column is ignored, so keep whatever helps you: salary, status, notes, priority, referral. Column order and capitalization don't matter.

```csv
company,title,url,status,salary,notes
Acme,Staff Product Designer,https://job-boards.greenhouse.io/acme/jobs/4000000001,applying,190-220k,referral from Sam
Initech,Design Lead (Remote US),https://jobs.ashbyhq.com/initech/...,watching,,
```

**Titles: copy them as posted.** Notes in (parentheses) or [brackets] are ignored when comparing, so "Design Lead (Remote US)" still matches "Design Lead". But don't shorten or reword the title itself: "Sr. Designer" and "Senior Product Designer" count as different titles.

## 3. Check only what you'd act on

A shorter list runs faster and is easier to read. Some ways to keep it focused:

- **Leave out jobs you're done with.** Applied, rejected, or decided against? Take them out of the list you check, or keep them in a separate file.
- **Keep two lists** if you track a lot of jobs:
  - `active.csv`: jobs you plan to apply to soon. Check daily.
  - `watching.csv`: jobs you're keeping an eye on. Check weekly.

  Give each its own results folder so they don't overwrite each other:
  ```sh
  signalcheck run active.csv --out results/active
  signalcheck run watching.csv --out results/watching
  ```
- **Filter your tracker before exporting.** In a spreadsheet, filter to the rows you care about (say, status is "applying"), then export just those.

## 4. Choose how often to check

- **Every morning** for jobs you're actively applying to. Postings often close without notice, and a morning check means you know before you spend an evening on an application. See [Run it every morning](../README.md#run-it-every-morning).
- **Right before you submit**, check that one job: `signalcheck one <url>`. It takes a few seconds.
- **Weekly** for jobs you're only watching.

SignalCheck is deliberately slow, a few seconds between requests to the same site, so a list of 50 jobs takes several minutes. That's normal, and it keeps job sites from treating you as a bot.

## 5. Add companies that embed Greenhouse on their own site

Some companies show Greenhouse jobs on their own domain, with links like `https://www.acme.com/careers?gh_jid=4000000001`. The link doesn't say which Greenhouse board to check, so tell SignalCheck once:

1. Open the company's careers page and find a link containing `job-boards.greenhouse.io/<name>` or `boards.greenhouse.io/<name>`. You may need to hover over a job or view the page source. That `<name>` is the board.
2. Add the site and the board name to a `boards.json` file:
   ```json
   {
     "www.acme.com": "acme",
     "careers.globex.com": "globex"
   }
   ```
3. Pass it on every run: `signalcheck run jobs.csv --boards boards.json`.

Until a company is in the file, its `?gh_jid=` links come back `CANT_TELL` with "Unknown Greenhouse token".

## 6. Read the results and act on them

Open `results/latest.csv` in a spreadsheet and sort by `verdict`.

| Verdict | What to do |
|---|---|
| `GONE` | Take it off your list. If you were mid-application, check the company's careers page for a reposted version: closed jobs are sometimes reopened under a new link. |
| `CHANGED` | Open the posting and reread it. A new title can mean a different level, scope or team. Update the title in your list once you've seen it, so next time only real changes show up. |
| `CANT_TELL` | Read the `reason` column. Usually: a listing site link (save the company's link instead), a bot check (open it yourself in a browser), or a company site that needs `boards.json`. |
| `LIVE` | Still open. The `evidence` column says how sure: `board` and `feed` are the strongest, `req_page` is good. |

The dated summary (`results/YYYY-MM-DD.md`) lists `GONE` and `CHANGED` jobs first, which makes for a quick morning read.

## 7. Save descriptions before they disappear

When a posting closes, its description usually disappears with it, along with what you'd want to quote in a cover letter or prepare for an interview. Save the text while it's up:

```sh
signalcheck describe active.csv
```

This writes `results/descriptions.json` with the cleaned-up text of every posting. Run it when you add new jobs to your list.

## Privacy

Your list and results stay on your computer. SignalCheck only contacts the job sites in your list (and the company boards and feeds behind them), and sends nothing about you: no sign-in, no cookies from your browser, no tracking.
