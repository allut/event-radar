# Coding Standards

The reviewer's entry point. Implementation follows `CLAUDE.md`; review checks a diff against every source below.

## Where the Standards Live

- **`CLAUDE.md`'s Code Quality Rules and Conventions are the inline rules.** `docs/conventions.md` holds their reasons and edges.
- **Area rules live in the area doc** that `CLAUDE.md`'s Documentation Map names for the files a diff touches.
- **Docs follow `docs/writing-docs.md`.** `backend/tests/test_docs_style.py` enforces its mechanical rules, so review covers the judgement ones.

## Review-Only Rules

These rules need judgement no lint can supply, so they live here rather than in `CLAUDE.md`.

### README Stays Current

- **A diff that adds a user-facing feature, a third-party service or a top-level folder updates `README.md` in the same change.** The feature goes under Features, the service under Tech stack, the folder under Project structure.
- **The README describes each thing by its role,** never by a list of files, jobs or versions a lookup already gives. See `docs/writing-docs.md`'s What to Keep and Cut section.
