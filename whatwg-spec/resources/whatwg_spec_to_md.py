#!/usr/bin/env python3
"""Render a section of a WHATWG-style spec as markdown.

Usage
-----
    whatwg_spec_to_md.py <spec_url_or_file> <anchor> [--out PATH] [--title TITLE]

Example
-------
    whatwg_spec_to_md.py https://url.spec.whatwg.org/ percent-encoded-bytes \\
        --out percent_encoding/SPEC.md --title "Percent-encoded bytes"

What it does
------------
1. Fetches the HTML (URL or local file).
2. Slices the section between the heading `<hN id="<anchor>">` and the next
   heading at the same-or-higher level.
3. Walks the HTML with html.parser.HTMLParser, emitting markdown:
     - headings (rebased so the section's top heading becomes `#`)
     - paragraphs, with `<p class="note|warning|advisement">` as blockquotes
     - `<ol>`/`<ul>` with nested lists (ordered counters tracked per depth)
     - `<table>` as a pipe table (rowspan expanded by repeating the cell)
     - `<code>` → `` `code` ``, `<var>` → *italic*, `<em>`/`<i>`/`<dfn>` → *italic*,
       `<strong>`/`<b>` → **bold**, `<br>` → hard break
     - `<a href="#foo">` rewritten to absolute URLs against the fetched URL;
       external hrefs passed through

Extend by adding tag handlers to `SpecToMarkdown.handle_starttag` /
`handle_endtag` for tags specific to other specs (e.g. `<algorithm>`,
TC39-style `<emu-*>`).

Scope limitations (intentional)
-------------------------------
- Rowspan on tables is rendered by repeating the cell text in each spanned
  row (markdown tables do not support rowspan).
- Multi-paragraph list items are supported one level deep; deeper nesting
  with continuation paragraphs may need manual tidying.
- Does not render `<figure>`, `<aside>`, or `<pre>` blocks specially.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


def fetch(source: str) -> str:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(
            source, headers={"User-Agent": "whatwg-spec-to-md/1.0"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


def slice_section(html_text: str, anchor: str) -> tuple[str, int]:
    """Return (section_html, heading_level). The section runs from the
    opening `<hN id="<anchor>">` heading (inclusive) to just before the next
    heading at level <= N (or end of document)."""
    m = re.search(
        r'<h([2-6])\b[^>]*\bid="' + re.escape(anchor) + r'"[^>]*>',
        html_text,
    )
    if not m:
        raise SystemExit(f"error: anchor '{anchor}' not found in source")
    level = int(m.group(1))
    levels_alt = "|".join(f"h{i}" for i in range(2, level + 1))
    end_re = re.compile(r"<(?:" + levels_alt + r")\b[^>]*>")
    rest = html_text[m.end():]
    nxt = end_re.search(rest)
    end = m.end() + nxt.start() if nxt else len(html_text)
    return html_text[m.start() : end], level


class SpecToMarkdown(HTMLParser):
    DROP_TAGS = {"script", "style", "svg"}

    def __init__(self, spec_base_url: str, section_level: int):
        super().__init__(convert_charrefs=True)
        self.base = spec_base_url.split("#")[0]
        self.section_level = section_level

        self.out: list[str] = []  # completed markdown blocks
        self.buf: list[str] = []  # inline-text buffer for the current block

        # list nesting: each entry {"kind": "ol"|"ul", "counter": int, "first_item": bool}
        self.list_stack: list[dict] = []
        self.drop_depth = 0

        # block-p classification
        self.p_class: list[str | None] = []  # stack, one entry per open <p>

        # heading state
        self.in_heading = 0
        self.heading_level = 0

        # anchor state (can't nest in practice, but keep a stack for safety)
        self.in_a = 0
        self.a_href: list[str] = []
        self.a_text: list[list[str]] = []

        # table state
        self.in_table = 0
        self.table_rows: list[list[dict]] = []
        self.current_row: list[dict] = []
        self.cell_buf: list[str] = []
        self.in_cell = 0
        self.cell_is_header = False
        self.cell_rowspan = 1
        self._row_started = False

    # ---------- implicit table closings (html.parser doesn't emit them) ----------
    def _close_open_cell(self) -> None:
        if self.in_cell:
            self.in_cell -= 1
            text = self._collapse("".join(self.cell_buf))
            self.cell_buf = []
            self.current_row.append(
                {
                    "text": text,
                    "header": self.cell_is_header,
                    "rowspan": self.cell_rowspan,
                }
            )

    def _close_open_row(self) -> None:
        if self._row_started and self.current_row:
            self.table_rows.append(self.current_row)
        self.current_row = []
        self._row_started = False

    # ---------- helpers ----------
    def _emit_text(self, s: str) -> None:
        if self.drop_depth:
            return
        if self.in_a:
            self.a_text[-1].append(s)
        elif self.in_cell:
            self.cell_buf.append(s)
        else:
            self.buf.append(s)

    def _collapse(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _list_indent(self, depth_offset: int = 0) -> str:
        return "   " * (len(self.list_stack) - 1 + depth_offset)

    def _list_marker(self) -> str:
        top = self.list_stack[-1]
        return f"{top['counter']}. " if top["kind"] == "ol" else "- "

    def _finish_block(self) -> None:
        """Flush the current inline buffer as a standalone block
        (paragraph, list item, or note), with blockquote / list prefixing."""
        text = self._collapse("".join(self.buf))
        self.buf = []
        if not text:
            return

        cls = self.p_class[-1] if self.p_class else None

        # Is this paragraph a note/warning/advisement?
        if cls in ("note", "warning", "advisement"):
            body = "\n".join("> " + ln for ln in text.splitlines())
            if self.list_stack and not self.list_stack[-1]["first_item"]:
                indent = self._list_indent() + "   "
                body = "\n".join(indent + ln for ln in body.splitlines())
            self.out.append(body)
            return

        # Inside a list item?
        if self.list_stack:
            top = self.list_stack[-1]
            if top["first_item"]:
                # first block of this <li>: include the marker
                self.out.append(self._list_indent() + self._list_marker() + text)
                top["first_item"] = False
            else:
                # continuation paragraph under the current li: indent
                self.out.append(self._list_indent() + "   " + text)
            return

        # Plain paragraph
        self.out.append(text)

    # ---------- parser events ----------
    def handle_starttag(self, tag, attrs):  # noqa: C901 - dispatch table
        if self.drop_depth or tag in self.DROP_TAGS:
            self.drop_depth += 1
            return
        ad = dict(attrs)

        if tag == "a":
            href = ad.get("href") or ""
            if href.startswith("#"):
                href = self.base + href
            self.in_a += 1
            self.a_href.append(href)
            self.a_text.append([])
            return

        if tag in {"h2", "h3", "h4", "h5", "h6"}:
            self._finish_block()
            self.in_heading += 1
            self.heading_level = max(1, int(tag[1]) - self.section_level + 1)
            return

        if tag == "p":
            self._finish_block()
            cls = ad.get("class", "")
            kind = None
            for k in ("note", "warning", "advisement"):
                if k in cls:
                    kind = k
                    break
            self.p_class.append(kind)
            return

        if tag in {"ol", "ul"}:
            self._finish_block()
            self.list_stack.append(
                {"kind": tag, "counter": 0, "first_item": False}
            )
            return

        if tag == "li":
            self._finish_block()
            if self.list_stack:
                self.list_stack[-1]["counter"] += 1
                self.list_stack[-1]["first_item"] = True
            return

        if tag == "code":
            self._emit_text("`")
            return
        if tag == "var":
            self._emit_text("*")
            return
        if tag in {"em", "i", "dfn"}:
            self._emit_text("*")
            return
        if tag in {"strong", "b"}:
            self._emit_text("**")
            return
        if tag == "br":
            self._emit_text("  \n")
            return

        if tag == "table":
            self._finish_block()
            self.in_table += 1
            self.table_rows = []
            self.current_row = []
            return
        if tag == "tr":
            self._close_open_cell()
            self._close_open_row()
            self.current_row = []
            self._row_started = True
            return
        if tag in {"th", "td"}:
            self._close_open_cell()
            self.in_cell += 1
            self.cell_buf = []
            self.cell_is_header = tag == "th"
            try:
                self.cell_rowspan = int(ad.get("rowspan", "1"))
            except ValueError:
                self.cell_rowspan = 1
            return

        # Default: ignore the tag wrapper, process children.

    def handle_endtag(self, tag):  # noqa: C901 - dispatch table
        if self.drop_depth:
            if tag in self.DROP_TAGS:
                self.drop_depth -= 1
            return

        if tag == "a":
            if not self.in_a:
                return
            self.in_a -= 1
            href = self.a_href.pop()
            text = self._collapse("".join(self.a_text.pop()))
            if not text:
                # Skip empty anchors (e.g. self-link markers in WHATWG specs).
                return
            rendered = f"[{text}]({href})" if href else text
            if self.in_a:
                self.a_text[-1].append(rendered)
            elif self.in_cell:
                self.cell_buf.append(rendered)
            else:
                self.buf.append(rendered)
            return

        if tag in {"h2", "h3", "h4", "h5", "h6"}:
            if self.in_heading:
                self.in_heading -= 1
                text = self._collapse("".join(self.buf))
                self.buf = []
                # Strip WHATWG section numbering like "1.3. "
                text = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", text)
                self.out.append("#" * self.heading_level + " " + text)
            return

        if tag == "p":
            self._finish_block()
            if self.p_class:
                self.p_class.pop()
            return

        if tag in {"ol", "ul"}:
            self._finish_block()
            if self.list_stack:
                self.list_stack.pop()
            return

        if tag == "li":
            self._finish_block()
            return

        if tag == "code":
            self._emit_text("`")
            return
        if tag == "var":
            self._emit_text("*")
            return
        if tag in {"em", "i", "dfn"}:
            self._emit_text("*")
            return
        if tag in {"strong", "b"}:
            self._emit_text("**")
            return

        if tag == "table":
            self._close_open_cell()
            self._close_open_row()
            self._finish_block()
            self._emit_table()
            self.in_table = max(0, self.in_table - 1)
            self._row_started = False
            return
        if tag == "tr":
            self._close_open_cell()
            self._close_open_row()
            return
        if tag in {"th", "td"}:
            self._close_open_cell()
            return

    def handle_data(self, data):
        if self.drop_depth:
            return
        self._emit_text(data)

    # ---------- table rendering ----------
    def _emit_table(self) -> None:
        if not self.table_rows:
            return
        # Expand rowspans by repeating the cell text in each spanned row.
        expanded: list[list[str]] = []
        header_mask: list[list[bool]] = []
        carry: dict[int, tuple[str, bool, int]] = {}  # col -> (text, is_hdr, rem)
        for row in self.table_rows:
            out_row: list[str] = []
            out_hdr: list[bool] = []
            src_i = 0
            col_i = 0
            while src_i < len(row) or carry:
                if col_i in carry:
                    text, is_hdr, rem = carry[col_i]
                    out_row.append(text)
                    out_hdr.append(is_hdr)
                    rem -= 1
                    if rem <= 0:
                        del carry[col_i]
                    else:
                        carry[col_i] = (text, is_hdr, rem)
                elif src_i < len(row):
                    cell = row[src_i]
                    src_i += 1
                    out_row.append(cell["text"])
                    out_hdr.append(cell["header"])
                    if cell["rowspan"] > 1:
                        carry[col_i] = (cell["text"], cell["header"], cell["rowspan"] - 1)
                else:
                    break
                col_i += 1
            expanded.append(out_row)
            header_mask.append(out_hdr)

        # Choose header: first row if all cells are <th>, else synthesize.
        if expanded and header_mask[0] and all(header_mask[0]):
            header = expanded[0]
            body = expanded[1:]
        else:
            width = max(len(r) for r in expanded)
            header = [""] * width
            body = expanded

        def row_md(cells: list[str]) -> str:
            return (
                "| "
                + " | ".join(c.replace("|", r"\|") for c in cells)
                + " |"
            )

        lines = [row_md(header), "|" + "|".join(["---"] * len(header)) + "|"]
        for r in body:
            while len(r) < len(header):
                r.append("")
            lines.append(row_md(r))
        self.out.append("\n".join(lines))


def render(raw_html: str, anchor: str, spec_url: str) -> str:
    section, level = slice_section(raw_html, anchor)
    p = SpecToMarkdown(spec_url, level)
    p.feed(section)
    p.close()
    body = "\n\n".join(b for b in p.out if b.strip())
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("source", help="URL or local path of the spec HTML")
    ap.add_argument("anchor", help='value of the target heading\'s id attribute')
    ap.add_argument("--out", "-o", help="output file (default: stdout)")
    ap.add_argument(
        "--title",
        help="top-level heading override (default: derived from the section heading)",
    )
    ap.add_argument(
        "--no-header",
        action="store_true",
        help="omit the synthesized Title + Source: header",
    )
    ap.add_argument(
        "--base-url",
        help=(
            "base spec URL used to resolve same-page `#foo` anchors "
            "(required when --source is a local file, auto-detected otherwise)"
        ),
    )
    args = ap.parse_args()

    raw = fetch(args.source)
    if args.source.startswith(("http://", "https://")):
        spec_base = args.base_url or args.source
    else:
        spec_base = args.base_url or ""
    body = render(raw, args.anchor, spec_base)

    # Body begins with an `# ...` heading — its text is either our title
    # or what we should use as title if --title isn't given.
    first_line, _, rest = body.partition("\n\n")
    derived_title = re.sub(r"^#+\s*", "", first_line).strip()
    title = args.title or derived_title

    if args.no_header:
        output = body
    else:
        if spec_base.startswith(("http://", "https://")):
            source_line = f"Source: <{spec_base.split('#')[0]}#{args.anchor}>"
        else:
            source_line = f"Source: {args.source}#{args.anchor}"
        output = f"# {title}\n\n{source_line}\n\n{rest}".rstrip() + "\n"

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
