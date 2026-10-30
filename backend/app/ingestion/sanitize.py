"""HTML sanitization for stored event text.

Strict nh3 allowlist plus the pre/post passes that keep line structure and
whitespace sane (block wrappers to <br>, whitespace-run collapsing, Cloudflare
email-protection decoding), and the plain-text converter used by every
non-HTML consumer.
"""

import re
from typing import Any

import nh3
from bs4 import BeautifulSoup, Tag

from app._generated.shared_constants import (
    HTML_SANITIZE_ALLOWED_ATTRS,
    HTML_SANITIZE_ALLOWED_TAGS,
    SAFE_URL_SCHEMES,
)
from app.constants.core import HTML_PARSER
from app.constants.ingestion import HTML_CF_EMAIL_MARKERS
from app.constants.security import (
    HTML_BLOCK_BOUNDARY_TAGS,
    HTML_BLOCK_TAGS_TO_BREAK,
    HTML_BR_TAG_RE,
    HTML_MULTI_BR_TEMPLATE_RE,
    HTML_SANITIZE_MAX_CONSECUTIVE_BR,
    HTML_SELF_CLOSING_BR_RE,
    HTML_WHITESPACE_RUN_RE,
)
from app.ingestion.selectors import CFEMAIL_HREF_MARKER

_MULTI_BR_RE = re.compile(HTML_MULTI_BR_TEMPLATE_RE % (HTML_SANITIZE_MAX_CONSECUTIVE_BR + 1))
_BR_TAG_RE = re.compile(HTML_BR_TAG_RE)
# ASCII-only: bare .strip() would also eat an intentional U+00A0 (see below).
_ASCII_WS = " \t\n\r\f\v"
_SELF_CLOSING_BR_PATTERN = re.compile(HTML_SELF_CLOSING_BR_RE)


def decode_cfemail(hex_str: str) -> str | None:
    """Decode a Cloudflare email-protection hex payload to a plain address.

    Cloudflare XOR-obfuscates the address against naive scrapers: the first
    byte is the XOR key, applied to every remaining byte. Returns None on
    malformed input (odd length, non-hex, empty) rather than raising, since
    the input is arbitrary source-page content.
    """
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    key = raw[0]
    return "".join(chr(b ^ key) for b in raw[1:])


def deobfuscate_cf_emails(html: str) -> str:
    """Replace Cloudflare "email protection" markup with the decoded address.

    Cloudflare hides real addresses behind client-side-JS-decoded markup; our
    scraper never runs that JS, so without this pass only the visible
    "[email protected]" placeholder text survives sanitization. Handles both
    forms Cloudflare emits: a <span data-cfemail="hex"> node, and an anchor
    whose href fragment carries the hex (`/cdn-cgi/l/email-protection#hex`) —
    the latter covers both the `__cf_email__`-classed anchor and a bare one.
    Replaces each matched node with the decoded address as a plain-text node
    (never a link — see sanitize_html's docstring for why).
    """
    if not any(marker in html for marker in HTML_CF_EMAIL_MARKERS):
        return html
    soup = BeautifulSoup(html, HTML_PARSER)
    changed = False
    for span in soup.find_all(attrs={"data-cfemail": True}):
        decoded = decode_cfemail(str(span["data-cfemail"]))
        if decoded is not None:
            span.replace_with(decoded)
            changed = True
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if CFEMAIL_HREF_MARKER not in href:
            continue
        decoded = decode_cfemail(href.rsplit("#", 1)[-1])
        if decoded is not None:
            anchor.replace_with(decoded)
            changed = True
    return str(soup) if changed else html


def _block_tags_to_breaks(html: str) -> str:
    """Convert bare block-wrapper tags (e.g. <div>) to <br> so line structure survives.

    nh3 strips disallowed tags without inserting any separator, so a source that
    encodes each line as a <div> (Piletilevi) collapses into run-on text. Replacing
    each such wrapper with a trailing <br> before sanitizing preserves the breaks
    using an already-allowlisted tag, keeping the stored HTML clean (no <div> noise).
    """
    lowered = html.lower()
    if not any(f"<{tag}" in lowered for tag in HTML_BLOCK_TAGS_TO_BREAK):
        return html
    soup = BeautifulSoup(html, HTML_PARSER)
    for tag in soup.find_all(list(HTML_BLOCK_TAGS_TO_BREAK)):
        tag.insert_after(soup.new_tag("br"))
        tag.unwrap()
    return str(soup)


_WHITESPACE_RUN_RE = re.compile(HTML_WHITESPACE_RUN_RE)
# Block containers eligible for empty-block removal — HTML_BLOCK_BOUNDARY_TAGS
# minus "br" (a void element, never a "container" that can be emptied).
_EMPTY_BLOCK_TAGS = HTML_BLOCK_BOUNDARY_TAGS - frozenset({"br"})


def _at_block_edge(node: Any, inline_tags: frozenset[str], leading: bool) -> bool:
    """Whether node sits at a true block boundary on the given side.

    Walks up through any chain of inline-tag ancestors (a, b, em, ...) so a
    wrapper sitting at the very start/end of a block — e.g. the <b> in
    "<p><b> Hello</b> after</p>" — still counts as a boundary, while a real
    adjacent text/inline sibling (a genuine word separator) does not.
    """
    element: Any = node
    while True:
        sibling = element.previous_sibling if leading else element.next_sibling
        if sibling is not None:
            return isinstance(sibling, Tag) and sibling.name in HTML_BLOCK_BOUNDARY_TAGS
        parent = element.parent
        if not isinstance(parent, Tag) or parent.name not in inline_tags:
            return True
        element = parent


def _strip_edge_brs(html: str) -> str:
    """Strip leading/trailing <br> runs (and the whitespace around them).

    Linear: each pass either consumes one whole tag or stops. Never use a
    regex with nested ``\\s*`` quantifiers around a repeated group here — see
    HTML_BR_TAG_RE."""
    html = html.strip(_ASCII_WS)
    while True:
        m = _BR_TAG_RE.match(html)
        if m is None:
            break
        html = html[m.end():].lstrip(_ASCII_WS)
    while html.endswith(">"):
        idx = html.rfind("<br")
        if idx == -1 or _BR_TAG_RE.fullmatch(html, idx) is None:
            break
        html = html[:idx].rstrip(_ASCII_WS)
    return html


def _collapse_text_whitespace(html: str) -> str:
    """Collapse whitespace runs within text nodes, leaving tags/attributes untouched.

    Source markup (e.g. KUMU's indented anchor tags) leaves newlines/indentation
    inside text nodes; nh3 sanitizes tags but never touches text content, so that
    raw whitespace survives into storage and renders literally under the
    frontend's white-space: pre-wrap. Collapsing here (post-sanitize, text-only)
    fixes it at the source for every HTML-sourced description. Matches ASCII
    whitespace only, not U+00A0 (non-breaking space, which BeautifulSoup decodes
    &nbsp; entities into) — nbsp is intentional spacing from the source content,
    not formatting noise, and Python's \\s would otherwise silently collapse it.
    """
    inline_tags = HTML_SANITIZE_ALLOWED_TAGS - HTML_BLOCK_BOUNDARY_TAGS
    soup = BeautifulSoup(html, HTML_PARSER)
    for node in soup.find_all(string=True):
        collapsed = _WHITESPACE_RUN_RE.sub(" ", node)
        # A single space touching a block boundary (line start/end, or the
        # edge of the whole fragment) is a leftover formatting artifact, not
        # a word-boundary separator — strip it so lines don't visibly start
        # or end with a stray space under the frontend's white-space:
        # pre-wrap. Inline tags (a, b, em, ...) are not boundaries: a real
        # separator like "text <a>link</a> more" — or a space living just
        # inside one, e.g. "before<b> after</b>" — must survive. When the
        # node has no sibling on a side, the search walks up through any
        # chain of inline ancestors (e.g. "<p><b> Hello</b> after</p>") to
        # find the true edge, since an inline wrapper sitting at the very
        # start/end of a block is still a block boundary.
        if _at_block_edge(node, inline_tags, leading=True):
            collapsed = collapsed.lstrip(" ")
        if _at_block_edge(node, inline_tags, leading=False):
            collapsed = collapsed.rstrip(" ")
        node.replace_with(collapsed)
    _strip_empty_blocks(soup)
    # BeautifulSoup serializes void elements as "<br/>"; normalize back to the
    # bare "<br>" form the rest of sanitize_html and its callers expect.
    return _SELF_CLOSING_BR_PATTERN.sub("<br>", str(soup))


def _strip_empty_blocks(soup: BeautifulSoup) -> None:
    """Remove block containers with no visible text, in place.

    nh3 keeps empty allowed tags — a source ending its markup with a bare
    ``<p></p>``, ``<p><br></p>``, ``<p>&nbsp;</p>``, or ``<p><span></span></p>``
    (Fienta/Piletilevi/ECH all do this) survives sanitization and renders as a
    visible blank line under the frontend's ``white-space: pre-wrap``.
    ``find_all`` returns tags in document order (a parent before its
    children), so iterating it in reverse visits every child before its
    parent; a single such bottom-up pass reaches the same fixed point a
    repeated forward-scanning loop would, since an ancestor is only checked
    for emptiness after its now-decomposed children have already been
    removed — emptying a ``<li>`` still cascades to its now-empty parent
    ``<ul>``/``<ol>`` in this one pass. ``get_text(strip=True)`` treats
    U+00A0 (nbsp) as whitespace (unlike the ASCII-only whitespace collapse
    above), so an nbsp-only block counts as empty here — intentional, since a
    lone nbsp inside an otherwise-empty container is formatting noise, not
    content.
    """
    for tag in reversed(soup.find_all(list(_EMPTY_BLOCK_TAGS))):
        if not tag.get_text(strip=True):
            tag.decompose()


def sanitize_html(
    text: str | None,
    tags: frozenset[str] | None = None,
    attrs: dict[str, set[str]] | None = None,
) -> str | None:
    """Sanitize HTML with a strict allowlist; plain text passes through unchanged.

    Safe for storing in description/important_info fields. Cloudflare
    email-protection markup is decoded first (see deobfuscate_cf_emails), before
    nh3 strips the attributes that carry the encoded address. nh3/ammonia forces
    rel="noopener" on links, drops javascript:/event-handler attrs, and HTML-escapes
    any disallowed tags so they render as visible text rather than markup. Block
    wrappers in HTML_BLOCK_TAGS_TO_BREAK are converted to <br> first (see
    _block_tags_to_breaks) so line boundaries are not lost when nh3 strips them.

    `tags`/`attrs` default to the shared ingestion allowlist
    (HTML_SANITIZE_ALLOWED_TAGS/ATTRS) — every ingestion call site is
    unaffected. The organizer-submission boundary passes its own narrower
    allowlist (ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS/ATTRS) instead.
    """
    if text is None:
        return None
    text = deobfuscate_cf_emails(text)
    resolved_attrs = attrs if attrs is not None else HTML_SANITIZE_ALLOWED_ATTRS
    cleaned = nh3.clean(
        _block_tags_to_breaks(text),
        tags=set(tags) if tags is not None else set(HTML_SANITIZE_ALLOWED_TAGS),
        attributes=resolved_attrs,
        url_schemes=set(SAFE_URL_SCHEMES),
        link_rel="noopener noreferrer",
        # nh3/ammonia always keeps a handful of "generic" attributes (e.g.
        # title, lang) regardless of the attributes map above — this filter
        # enforces resolved_attrs as the true ceiling so a narrower boundary
        # allowlist (e.g. the organizer one, which omits title) is honored.
        # "rel" is exempted: it isn't organizer-controlled input, it's the
        # link_rel="noopener noreferrer" value nh3 itself injects below —
        # filtering it out here would silently defeat that protection.
        attribute_filter=lambda tag, attr, value: (
            value if attr == "rel" or attr in resolved_attrs.get(tag, set()) else None
        ),
    )
    if not cleaned:
        return None
    cleaned = _MULTI_BR_RE.sub("<br>" * HTML_SANITIZE_MAX_CONSECUTIVE_BR, cleaned)
    cleaned = _strip_edge_brs(cleaned)
    if not cleaned:
        return None
    cleaned = _collapse_text_whitespace(cleaned)
    # Re-strip edge <br> runs — removing a trailing/leading empty block above
    # can expose a bare <br> that the earlier _strip_edge_brs pass ran before it
    # existed (e.g. "<p>Real content</p><br><p></p>" → removing the empty <p>
    # leaves a dangling trailing <br>).
    cleaned = _strip_edge_brs(cleaned)
    if not cleaned:
        return None
    # Strip ASCII whitespace only — bare .strip() also treats U+00A0 (nbsp) as
    # whitespace and would delete an intentional leading/trailing &nbsp;.
    return cleaned.strip(" \t\n\r\f\v") or None


def html_to_text(text: str | None) -> str | None:
    """Strip HTML tags from a sanitized description, returning plain text.

    Used by plain-text consumers (LLM prompts, explicit-keyword filter, dedup
    quality rank) so they never receive raw HTML tags or entities.
    """
    if not text:
        return text
    if "<" not in text and "&" not in text:
        # No tag or entity to strip: the parse would only strip the ends.
        return text.strip() or None
    return BeautifulSoup(text, HTML_PARSER).get_text(separator=" ", strip=True) or None
