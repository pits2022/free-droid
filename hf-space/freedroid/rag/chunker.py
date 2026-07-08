"""Parse the Yotengrit knowledge markdown into retrievable chunks.

One chunk per `###` heading: the heading is the chunk title, the lines until the next
heading (`###` or `##`) are the body. Non-knowledge sections (the intro, the "how to
fill" instructions, the trailing note) carry no `###`, so they never become chunks.
An empty (unanswered) heading is skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_H2 = re.compile(r"^##\s+(.*?)\s*$")
_H3 = re.compile(r"^###\s+(.*?)\s*$")
_HR = re.compile(r"^-{3,}\s*$")  # horizontal rule: section boundary, never chunk body
_PLACEHOLDER = re.compile(r"^\s*>?\s*_\.\.\._\s*$")


@dataclass(frozen=True)
class Chunk:
    id: str        # stable, order-based id (the corpus is regenerated wholesale)
    section: str   # the enclosing `##` section title
    title: str     # the `###` heading (the question)
    text: str      # the answer body


def parse_chunks(md_text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = ""
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if title is not None:
            text = "\n".join(body).strip()
            if text:  # skip an unanswered heading
                chunks.append(Chunk(id=f"yot-{len(chunks):03d}",
                                    section=section, title=title, text=text))
        title, body = None, []

    for line in md_text.splitlines():
        if m3 := _H3.match(line):
            flush()
            title = m3.group(1)
        elif m2 := _H2.match(line):
            flush()
            section = m2.group(1)
        elif _HR.match(line):
            # `---` separates sections (and precedes the trailing editor note); end the
            # current chunk here so neither the rule nor post-rule meta-text leaks in.
            flush()
        elif title is not None and not _PLACEHOLDER.match(line):
            body.append(line)
    flush()
    return chunks
