# How SignalCheck decides

SignalCheck groups your jobs by company and job system, so one read of a company's board or feed settles every job you saved there. Then, per system:

## Greenhouse: evidence `board`

The only proof is the company's rendered job board at `https://job-boards.greenhouse.io/<company>`. SignalCheck loads it in a headless browser, collects every job link, and pages through `?page=2`, `?page=3` and so on until a page adds nothing new. If the board shows a total ("61 jobs"), that is compared with what was collected.

- Listed on the board: `LIVE`.
- Not listed, and the whole board was read: `GONE`.
- Not listed, but fewer jobs were collected than the board's total: `CANT_TELL` (absence not proven).
- Board won't load: `CANT_TELL`.

SignalCheck never opens a Greenhouse posting page as evidence, because Greenhouse keeps serving closed and unlisted postings in full. Greenhouse's public jobs API isn't used to decide either: it is wrong in both directions.

## Ashby: evidence `feed`

Reads `https://api.ashbyhq.com/posting-api/job-board/<company>` and parses it completely. A complete parse means the whole list was seen.

- In the feed: `LIVE`, with title, location and pay range when the feed has them.
- Not in the feed, or the feed is an empty list: `GONE`.
- In the feed but marked unlisted: `CANT_TELL`.
- Feed error or incomplete parse: `CANT_TELL`.

## Lever: evidence `feed`, with a second look

Reads `https://api.lever.co/v0/postings/<company>?mode=json` and parses it completely.

- In the feed: `LIVE`.
- Not in the feed: Lever's feed sometimes leaves out live postings, so SignalCheck also loads the posting page in a browser.
  - The page is gone (HTTP 404) or redirects away: `GONE`.
  - The page still shows the posting: `CANT_TELL`, "absent from Lever feed but page still renders".

## Workday, Gem and other careers pages: evidence `req_page`

Only the posting page is available, so this is weaker evidence.

1. For most sites, SignalCheck first fetches the page plainly (no browser). Many careers pages are built on the server and answer immediately. Workday and Gem always need a browser, so they skip this step.
2. If the plain page doesn't show a posting (often an empty JavaScript shell), it loads the page in a headless browser and waits for it to settle (up to 30 seconds).
3. If the plain page says the job is closed, it **also** loads the page in the browser, because some sites show "this position has been filled" to automated requests while the job is open. It's `GONE` only if the browser agrees.

Then:

- HTTP 404 or 410, or a redirect to a search or home page: `GONE`.
- The page or its headings say the job is closed ("no longer available", "has been filled", "has expired", "not found" and similar): `GONE`.
- A full posting (at least about 1,000 characters) with an Apply button or structured job data: `LIVE`.
- Anything else, such as a loading shell, an empty list or a "please enable JavaScript" notice: `CANT_TELL`.

## Job listing sites: `CANT_TELL`, never contacted

Links to LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster, SimplyHired, Dice, Wellfound and Built In (including their country sites, like `uk.indeed.com` or `glassdoor.co.uk`) are recognized from the address alone and never fetched. Those sites need a sign-in, don't allow automated reading, and don't reliably show whether the employer's job is still open. The reason asks for the company's own posting link.

## Title changes: `CHANGED`

If your list includes a title, SignalCheck compares it with the title the source reports: the board or feed entry, or, for posting pages, the page's structured job data or its `og:title` tag (never a page heading, which is often something like "Job details").

Titles are compared after removing anything in (parentheses) or [brackets], lowercasing, treating "&" as "and", and ignoring punctuation. So "Director of Product Design (Remote, US)" matches "Director of Product Design", but "Senior Principal Product Manager" does not match "Principal Product Manager".

A changed title on a live job gives `CHANGED`, with the new title in `observedTitle`.

## Retries and blocks

- A timeout, network error, HTTP 429 or 5xx: one retry for that company, at least 60 seconds later. If it fails again: `CANT_TELL`.
- HTTP 401 or 403, or a bot check or CAPTCHA page: `CANT_TELL` right away. Never bypassed.
- A bug while checking one company gives `CANT_TELL` for that company only. The rest of the run continues.
