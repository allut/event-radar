"""HTML sanitization for stored event text.

Strict nh3 allowlist plus the pre/post passes that keep line structure and
whitespace sane (block wrappers to <br>, whitespace-run collapsing), and the
plain-text converter used by every non-HTML consumer.
"""

import re
from typing import Any

import nh3
from bs4 import BeautifulSoup, Tag

from app.constants import (
    HTML_BLOCK_BOUNDARY_TAGS,
    HTML_BLOCK_TAGS_TO_BREAK,
    HTML_SANITIZE_ALLOWED_ATTRS,
    HTML_SANITIZE_ALLOWED_TAGS,
    HTML_SANITIZE_MAX_CONSECUTIVE_BR,
    SAFE_URL_SCHEMES,
)

_MULTI_BR_RE = re.compile(r"(?:<br\s*/?>\s*){%d,}" % (HTML_SANITIZE_MAX_CONSECUTIVE_BR + 1))
_EDGE_BR_RE = re.compile(r"^(?:\s*<br\s*/?>\s*)+|(?:\s*<br\s*/?>\s*)+$")


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
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(list(HTML_BLOCK_TAGS_TO_BREAK)):
        tag.insert_after(soup.new_tag("br"))
        tag.unwrap()
    return str(soup)


_WHITESPACE_RUN_RE = re.compile(r"[ \t\n\r\f\v]+")
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
    soup = BeautifulSoup(html, "html.parser")
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
    return re.sub(r"<br\s*/>", "<br>", str(soup))


def _strip_empty_blocks(soup: BeautifulSoup) -> None:
    """Remove block containers with no visible text, in place.

    nh3 keeps empty allowed tags — a source ending its markup with a bare
    ``<p></p>``, ``<p><br></p>``, ``<p>&nbsp;</p>``, or ``<p><span></span></p>``
    (Fienta/Piletilevi/ECH all do this) survives sanitization and renders as a
    visible blank line under the frontend's ``white-space: pre-wrap``. Iterates
    to a fixed point so emptying a ``<li>`` can cascade to its now-empty parent
    ``<ul>``/``<ol>``. ``get_text(strip=True)`` treats U+00A0 (nbsp) as
    whitespace (unlike the ASCII-only whitespace collapse above), so an
    nbsp-only block counts as empty here — intentional, since a lone nbsp
    inside an otherwise-empty container is formatting noise, not content.
    """
    while True:
        removed = False
        for tag in soup.find_all(list(_EMPTY_BLOCK_TAGS)):
            if not tag.get_text(strip=True):
                tag.decompose()
                removed = True
        if not removed:
            break


def sanitize_html(text: str | None) -> str | None:
    """Sanitize HTML with a strict allowlist; plain text passes through unchanged.

    Safe for storing in description/important_info fields. nh3/ammonia forces
    rel="noopener" on links, drops javascript:/event-handler attrs, and HTML-escapes
    any disallowed tags so they render as visible text rather than markup. Block
    wrappers in HTML_BLOCK_TAGS_TO_BREAK are converted to <br> first (see
    _block_tags_to_breaks) so line boundaries are not lost when nh3 strips them.
    """
    if text is None:
        return None
    cleaned = nh3.clean(
        _block_tags_to_breaks(text),
        tags=set(HTML_SANITIZE_ALLOWED_TAGS),
        attributes=HTML_SANITIZE_ALLOWED_ATTRS,
        url_schemes=set(SAFE_URL_SCHEMES),
        link_rel="noopener noreferrer",
    )
    if not cleaned:
        return None
    cleaned = _MULTI_BR_RE.sub("<br>" * HTML_SANITIZE_MAX_CONSECUTIVE_BR, cleaned)
    cleaned = _EDGE_BR_RE.sub("", cleaned)
    if not cleaned:
        return None
    cleaned = _collapse_text_whitespace(cleaned)
    # Re-strip edge <br> runs — removing a trailing/leading empty block above
    # can expose a bare <br> that the earlier _EDGE_BR_RE pass ran before it
    # existed (e.g. "<p>Real content</p><br><p></p>" → removing the empty <p>
    # leaves a dangling trailing <br>).
    cleaned = _EDGE_BR_RE.sub("", cleaned)
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
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True) or None
