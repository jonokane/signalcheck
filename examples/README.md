# Examples

Sample job lists in each format SignalCheck reads. The companies and URLs are made up, so running these as they are tells you nothing useful: replace them with your own saved jobs.

- `jobs.txt`: one URL per line.
- `jobs.csv`: a `url` column, plus optional `company` and `title`. Extra columns (like `notes`) are ignored.
- `jobs.json`: a list of objects. An `id` is optional; without one, SignalCheck makes a stable id from the URL.
- `boards.json`: for company sites that embed Greenhouse (`?gh_jid=` links), maps the site to its Greenhouse board name. Use with `--boards`.
