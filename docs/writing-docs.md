# Writing Docs

What's in here: the house style for `CLAUDE.md`, `README.md` and `docs/*.md`, the README carve-outs, how code points into docs, and the guard that enforces it.

## Scope

- **Governs `CLAUDE.md`, `README.md` and the top-level `docs/*.md`.** Docs are agent-first and still readable by humans: agents open them before editing code, so exact pointers matter more than polish.
- **`docs/adr/*`, `CONTEXT.md` and `docs/agents/*` keep their own formats.** The domain-modeling skill owns the ADR and glossary shapes.

## Shape

- **Bold-lead bullets are the default.** Each bullet opens with a bold one-line rule or fact. One or two sentences of *why* or *gotcha* follow. One fact per bullet.
- **Each topic gets a named `##`/`###` heading.** A bullet that mixes two topics splits under two headings.
- **Tables hold lookup data only:** uniform key→value facts like enum values, env var→purpose, field→authority or schedule→job. Cells hold short phrases. A reason or a warning goes in a bullet.
- **A numbered list is for a real sequence**, such as a flow or an order of passes.
- **Short prose orients.** A heading may open with a lead-in paragraph before its bullets.

## Length

- **Cap every bullet and paragraph at 60 words.** A longer topic becomes sibling bullets or its own subheading. The count is whitespace tokens, inline code included. Nested bullets count on their own.
- **Aim for sentences of about 20 words, 30 at most.** One idea per sentence.
- **`CLAUDE.md` and `README.md` each stay within 1,500 words.** A line that would cross the limit means moving something into an area doc, or raising the limit on purpose in the guard.

## Banner

- **Open every `docs/*.md` with `What's in here: …` on the line after the H1.** One line, 30 words or fewer, topics only.
- **The "read before touching" file list lives only in `CLAUDE.md`'s Documentation Map.** A doc body names its topics; the map row names its triggers.

## Citing code

- **Write `path::symbol`**, for example `app/publish.py::publish_pending()`. Use a bare `path` when the whole file is the point, and a bare `symbol` once its path has appeared in the same section.
- **Leave line numbers out of cites.** They drift on every edit, and the guard rejects a `path:line` cite.

## What to keep and cut

- **Keep what reading the code won't tell you:** the why, the gotchas, the trade-offs, and silent-failure warnings with the steps to verify.
- **Cut what one file or command reveals:** component, route, prop and nav-item lists, file counts and folder inventories.
- **Cut issue numbers and audit IDs, keep the lesson.** Keep an ID only when it justifies a rule that would otherwise look arbitrary, as one parenthetical.
- **Each fact has one home.** Another doc links to it with a one-clause gist: `See [organizer-portal.md](organizer-portal.md)'s Event Claiming section`.

## Wording

- **Use domain terms exactly as `CONTEXT.md` defines them.**
- **Phrase rules as the positive target.** Keep "Never …" for a real guardrail, and pair it with what to do instead.

## Pointers from code

- **Write a code→doc pointer as the doc path plus a quoted heading:** `docs/backend-ops.md "Data Retention"`. The guard checks the quoted text is a heading or its leading words. Free prose like "the retention section" goes unchecked.
- **Keep each pointer on one line.** The guard reads line by line, so a pointer wrapped between path and heading goes unchecked.
- **`design-system.md` keeps its `## N.` numbering frozen** so `docs/design-system.md §N` pointers stay valid. Other docs cite by heading name, with no new numbering.
- **Renaming or removing a heading means updating its pointers in the same commit.** The guard fails on any quoted heading or `§N` that no longer resolves.

## README carve-outs

- **No banner.** The pitch blockquote stands in for `What's in here:`.
- **GitHub admonitions (`> [!NOTE]` etc.) are allowed for real guardrails.** Each counts as one paragraph under the 60-word cap.
- **Every other rule applies**, `path::symbol` cites and tables for lookup data included.

## The guard

- **`backend/tests/test_docs_style.py` enforces the mechanical rules in CI:** the 60-word cap (skipping fences, headings, HTML comments and table rows), the banner, no `path:line` cites, the 1,500-word limits, and code→doc pointer resolution.
- **The rest is judgement:** sentence length, what to cut, one home per fact, and positive phrasing.
- **`NOT_YET_REWRITTEN` is a ratchet.** A doc on it is exempt from the style checks, never from pointer resolution. A rewrite removes its doc from the list in the same commit, so the list only shrinks.
