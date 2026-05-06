---
name: whatwg-spec
description: Fetch a WHATWG-style web spec (URL, HTML, Fetch, DOM, Streams, Encoding, etc.) and render one section as markdown so it can be consulted directly. Trigger when you need to consult the authoritative text of a web standard — e.g. "what does the URL spec say about percent-encoding", "check the Fetch spec for redirect handling", "look up the HTML spec section on …", or when another skill needs spec text in markdown form.
---

# whatwg-spec

Render a single section of a WHATWG (or WHATWG-style: W3C, TC39) HTML spec as
markdown. Designed for on-demand reference: pick the section by its heading
anchor, get markdown back, read it in-context.

## Why a section, not the whole spec

WHATWG specs are large single-page HTML documents (the URL spec is ~1 MB; the
HTML spec is tens of MB rendered). Slurping the whole thing wastes context and
buries the part that matters. This skill fetches the document once but emits
**only the section you ask for**, with sub-headings rebased so the section's
top heading becomes `#`.

## Usage

```sh
python3 ~/.claude/skills/whatwg-spec/resources/whatwg_spec_to_md.py \
    <spec_url_or_local_html> <anchor> [--out PATH] [--title TITLE] [--no-header] [--base-url URL]
```

- `spec_url_or_local_html` — full URL of the spec (e.g. `https://url.spec.whatwg.org/`) or a local HTML file.
- `anchor` — value of the section heading's `id` attribute (the part after `#` in the spec's permalink).
- `--out` — write to a file instead of stdout.
- `--title` — override the synthesised top heading.
- `--no-header` — omit the "Title + Source:" preamble.
- `--base-url` — required when the source is a local file and you want `#foo` anchors resolved to absolute URLs.

The output starts with a generated `# Title` and `Source: <url#anchor>` line so
the markdown remains traceable to its origin spec, then the section body.

## Finding the right anchor

The anchor is the `id` of the heading you care about. Three reliable ways to
find it:

1. **Spec table of contents.** WHATWG specs render a ToC at the top; clicking
   any entry navigates to `…#anchor` — that fragment is the anchor.
2. **§ permalinks.** Every section heading in WHATWG specs has a `§` permalink
   next to it that points at `…#anchor`.
3. **Grep the fetched HTML.** `curl -s <url> | grep -oE 'id="[a-z0-9-]+"' | sort -u`
   lists every heading id.

If you guess wrong, the script exits with `error: anchor 'X' not found in source`.

## Examples

```sh
# URL spec — percent-encoded bytes
python3 ~/.claude/skills/whatwg-spec/resources/whatwg_spec_to_md.py \
    https://url.spec.whatwg.org/ percent-encoded-bytes

# Fetch spec — HTTP-redirect fetch, into a file
python3 ~/.claude/skills/whatwg-spec/resources/whatwg_spec_to_md.py \
    https://fetch.spec.whatwg.org/ http-redirect-fetch \
    --out /tmp/fetch-redirect.md

# Local HTML mirror, with explicit base URL for `#foo` link rewriting
python3 ~/.claude/skills/whatwg-spec/resources/whatwg_spec_to_md.py \
    ./url.html percent-encoded-bytes \
    --base-url https://url.spec.whatwg.org/
```

## What the renderer handles

Headings (rebased), paragraphs (with `note`/`warning`/`advisement` paragraphs
as blockquotes), nested ordered/unordered lists, pipe tables (rowspans
expanded by repeating the cell), `<code>` / `<var>` / `<em>` / `<strong>` /
`<br>`, and anchor rewriting (`#foo` → absolute URL against the spec base).
WHATWG section numbering like `1.3.` is stripped from headings.

Out of scope: `<figure>`, `<aside>`, `<pre>` blocks (rendered as plain text);
deeply nested list-item continuation paragraphs may need manual tidying.

## Extending

For non-WHATWG specs with custom tags (TC39 `<emu-*>`, W3C `<algorithm>`,
etc.), add handlers to `SpecToMarkdown.handle_starttag` / `handle_endtag` in
[whatwg_spec_to_md.py](resources/whatwg_spec_to_md.py). The slicing logic only
assumes `<hN id="…">` headings and is reusable as-is.
