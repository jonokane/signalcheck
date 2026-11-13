"""Read a job page's raw HTML without running it (standard library only).

Used for generic company career pages: if the server already sent the posting
in the HTML, there is no need to start a browser.
"""

import json
import re
from html.parser import HTMLParser

APPLY = re.compile(r"\bapply\b", re.I)
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _Facts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.h1, self.heads, self.ld, self.has_apply = "", [], [], [], False
        self.og_title = ""
        self._text, self._skip, self._in_title = [], 0, False
        self._head = None  # (tag, [text]) while inside h1/h2
        self._ctrl = None  # [text] while inside a/button
        self._ld = None  # [text] while inside a JSON-LD script

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in SKIP_TAGS:
            if tag == "script" and a.get("type", "").lower() == "application/ld+json":
                self._ld = []
            self._skip += 1
            return
        if tag == "meta" and a.get("property", "").lower() == "og:title" and not self.og_title:
            self.og_title = " ".join(a.get("content", "").split())
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2"):
            self._head = (tag, [])
        elif tag in ("a", "button"):
            self._ctrl = []
            if APPLY.search(a.get("aria-label", "")):
                self.has_apply = True
        elif tag == "input" and a.get("type", "").lower() == "submit" and APPLY.search(a.get("value", "")):
            self.has_apply = True

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            if tag == "script" and self._ld is not None:
                self.ld.append("".join(self._ld))
                self._ld = None
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2") and self._head and self._head[0] == tag:
            t = " ".join(" ".join(self._head[1]).split())
            if t:
                self.heads.append(t)
                if tag == "h1":
                    self.h1.append(t)
            self._head = None
        elif tag in ("a", "button") and self._ctrl is not None:
            if APPLY.search(" ".join(self._ctrl)):
                self.has_apply = True
            self._ctrl = None

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self._text.append(data)
        if self._head:
            self._head[1].append(data)
        if self._ctrl is not None:
            self._ctrl.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self._text).split())


def find_job_posting(blobs):
    """First schema.org JobPosting object in the page's JSON-LD, or None."""
    for blob in blobs:
        try:
            stack = [json.loads(blob)]
        except ValueError:
            continue
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                t = x.get("@type")
                if "JobPosting" in (t if isinstance(t, list) else [t]):
                    return x
                if isinstance(x.get("@graph"), list):
                    stack.extend(x["@graph"])
    return None


def parse_html(html):
    """Return (facts, job_posting) for an HTML document."""
    f = _Facts()
    f.feed(html or "")
    f.close()
    f.title = " ".join(f.title.split())
    return f, find_job_posting(f.ld)
