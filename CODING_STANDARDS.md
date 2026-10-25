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

### Frontend Judgement Rules

- **A date-only ISO string goes through `parseISODateLocal()`,** never `new Date()`. `new Date('2026-10-25')` parses as UTC midnight and shows the previous day west of UTC.
- **Admin Promotions copy lives in `constants/promotions.ts`.** A label, heading or button text in `routes/AdminPromotionDetail/` or `lib/promotions.ts` is a constant first.
- **Money and VAT math goes through the `lib/organizerPromotions.ts` helpers** (`formatMoney`, `grossCents`). A route never re-derives a gross price or slices the currency symbol off a formatted string.
