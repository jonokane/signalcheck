"""Turn job descriptions (HTML or plain text) into clean plain text.

Standard library only. Keeps paragraph breaks and bullet lines, collapses the
rest of the whitespace, and caps the length.
"""

import html
import re
from html.parser import HTMLParser

CAP = 9000

PARA_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "section", "article", "header", "footer", "pre"}
LINE_TAGS = {"div", "tr", "dt", "dd", "br", "hr"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}

# A bullet glyph (or a lone "-"/"*") at the start of a line, followed by a space.
BULLET = re.compile(r"^(?:[•·●▪◦‣⁃∙*\-–—])\s+")
# Inline images some feeds embed in plain text, e.g. "[data:image/png;base64,iVBOR...]".
DATA_URI = re.compile(r"!\[[^\]\n]*\]\(data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+\)|\[?data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+\]?")
INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


class _ToText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip, self._pre = [], 0, 0
        self._bullet = False  # inside an <li>, waiting for its first text

    def _brk(self, s):
        if not self._bullet:  # keep "- " on the same line as the item's text
            self.out.append(s)

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "li":
            self.out.append("\n")
            self._bullet = True
        elif tag in PARA_TAGS:
            self._brk("\n\n")
            if tag == "pre":
                self._pre += 1
        elif tag in LINE_TAGS:
            self._brk("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr"):
            self._brk("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in PARA_TAGS:
            self._brk("\n\n")
            if tag == "pre":
                self._pre = max(0, self._pre - 1)
        elif tag in LINE_TAGS or tag == "li":
            self._bullet = False
            self.out.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        # In HTML, runs of whitespace inside text are one space; only tags break lines.
        data = data if self._pre else re.sub(r"\s+", " ", data)
        if self._bullet and data.strip():
            data, self._bullet = "- " + data.lstrip(), False
        self.out.append(data)


def looks_like_html(s):
    return bool(re.search(r"</?(p|div|br|li|ul|ol|h[1-6]|span|strong|b|em|a)\b[^>]*>", s or "", re.I))


def html_to_text(s, cap=CAP):
    """HTML (possibly entity-escaped once more, as Greenhouse sends it) to clean text."""
    s = s or ""
    if "&lt;" in s and not looks_like_html(s):
        s = html.unescape(s)
    p = _ToText()
    p.feed(s)
    p.close()
    return clean_text("".join(p.out), cap)


def clean_text(s, cap=CAP):
    """Plain text: one blank line between paragraphs, bullets as "- ", capped."""
    s = DATA_URI.sub("", s or "").translate(INVISIBLE).replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = []
    for raw in s.split("\n"):
        line = " ".join(raw.split())
        if line:
            line = BULLET.sub("- ", line)
            if line == "-":  # an empty bullet
                continue
        if line or (lines and lines[-1]):  # at most one blank line in a row
            lines.append(line)
    # No blank line between two bullets of the same list.
    lines = [ln for i, ln in enumerate(lines)
             if ln or not (0 < i < len(lines) - 1 and lines[i - 1].startswith("- ") and lines[i + 1].startswith("- "))]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cap_text(text, cap)


def cap_text(text, cap=CAP):
    """At most `cap` characters, cut at a line (else word) boundary, ending in "…"."""
    if len(text) <= cap:
        return text
    room = cap - 1
    cut = text.rfind("\n", 0, room)
    if cut < room * 0.8:
        cut = text.rfind(" ", 0, room)
    if cut <= 0:
        cut = room
    return text[:cut].rstrip() + "…"
