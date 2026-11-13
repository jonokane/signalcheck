"""Command line.

    signalcheck run FILE [--out DIR] [--boards PATH]
    signalcheck one URL [--boards PATH]
    signalcheck describe FILE [--out DIR] [--boards PATH]
"""

import argparse
import sys

from . import __version__
from .inputs import InputError


def build_parser():
    ap = argparse.ArgumentParser(prog="signalcheck", description="Is each saved job posting really still open?")
    ap.add_argument("--version", action="version", version=f"signalcheck {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="check every job in FILE and write the results")
    r.add_argument("file", help="your jobs: .txt (one URL per line), .csv (url column) or .json")
    r.add_argument("--out", default="results", help="folder for results (default: ./results)")
    r.add_argument("--boards", help="optional JSON map of company host to Greenhouse token")

    o = sub.add_parser("one", help="check one URL and print the result")
    o.add_argument("url")
    o.add_argument("--boards", help="optional JSON map of company host to Greenhouse token")

    d = sub.add_parser("describe", help="save each job's description as text (descriptions.json)")
    d.add_argument("file", help="same formats as run")
    d.add_argument("--out", default="results", help="folder for descriptions.json (default: ./results)")
    d.add_argument("--boards", help="optional JSON map of company host to Greenhouse token")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "run":
        from .run import run
        return run(a.file, a.out, a.boards)
    if a.cmd == "describe":
        from .describe import describe
        return describe(a.file, a.out, a.boards)
    from .run import one
    return one(a.url, a.boards)


def entry(argv=None):
    """Console entry point. Any failure ends with one 'FAILED: ...' line, which
    schedulers (and SignalClaw's run-with-status.sh) quote in their alert."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        print("FAILED: interrupted", file=sys.stderr)
        return 130
    except InputError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FAILED: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr, flush=True)
        return 1
