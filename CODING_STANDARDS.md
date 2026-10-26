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

### Backend Judgement Rules

- **A batch job that calls a helper per row, where the helper runs a query or a write, has a per-row SELECT.** The loop hides it, so read the helper. `app/ingestion/refetch.py::_cancel_gone_events()` once cancelled each gone event through the single-event helper; it now calls `cancel_events_and_resolve_reports()`.
- **A request-path list endpoint makes a fixed number of queries per page, never one per row.** A validator or serializer called per row counts.
- **A new serial, rate-limited external loop gets an entry in `docs/conventions.md`'s External Fan-Out exceptions.** Without one, it reads as a missed `asyncio.gather`.

### Frontend Judgement Rules

- **Admin Promotions copy lives in `constants/promotions.ts`.** A label, heading or button text in `routes/AdminPromotionDetail/` or `lib/promotions.ts` is a constant first.
- **A date-only ISO string held in a variable goes through `parseISODateLocal()`.** ESLint catches only a `'YYYY-MM-DD'` literal, so check `new Date(x)` where `x` could be date-only: `new Date('2026-10-25')` parses as UTC midnight and shows the previous day west of UTC.
- **A gross price goes through `grossCents` and `formatMoney` (`lib/organizerPromotions.ts`).** ESLint catches slicing a `formatMoney()` result; a route re-deriving VAT inline is the case left to review.
