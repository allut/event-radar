# Feed-membership lookup for the admin event inspector

**Date:** 2026-08-25
**Ticket:** https://github.com/allut/event-radar/issues/147
**Parent effort:** admin console planning (fog item that graduated into this ticket)

Question under research: should a read-only admin "event inspector" screen be able to show whether a given event appears in *any* user's built Daily 5 today, given that `daily_feeds.event_ids` is a `BigInteger[]` column with no per-event index today?

All claims below are cited to this repo's own code/migrations/docs, or to the official PostgreSQL documentation (docs.postgresql.org, current version). No blog posts or secondary sources were used as authority.

---

## 1. Current shape of `daily_feeds`

**Model** — `backend/app/models/models.py:614-636` (`class DailyFeed`):

```python
class DailyFeed(Base):
    __tablename__ = "daily_feeds"
    __table_args__ = (
        UniqueConstraint("user_id", "feed_date"),
        # cleanup.py's DailyFeed.feed_date < cutoff has no user_id filter — the
        # UniqueConstraint above leads with user_id, so this indexless-for-that-
        # predicate query was unusable by it.
        Index("ix_daily_feeds_feed_date", "feed_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feed_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, default=list
    )
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

Confirmed also in `docs/data-model.md:18`: `daily_feeds — user_id, feed_date, event_ids BigInteger[]`.

**Indexes that exist today**, per the model and migrations (`backend/alembic/versions/0001_init.py:283-309`, `0023_bigo_audit_indexes_2.py`):
- A unique constraint on `(user_id, feed_date)` — the natural PK-ish lookup, leads with `user_id`.
- A plain btree index on `feed_date` alone (`ix_daily_feeds_feed_date`, added in migration `0023`, `backend/alembic/versions/0023_bigo_audit_indexes_2.py:34`, specifically to unblock `cleanup.py`'s `DailyFeed.feed_date < cutoff` retention-sweep query, which has no `user_id` predicate and so couldn't use the composite unique constraint).
- **No index of any kind on `event_ids`.** Grepping every migration file (`grep -rln "daily_feeds\|DailyFeed" backend/alembic/versions/` → only `0001_init.py` and `0023_bigo_audit_indexes_2.py`) and the model's `__table_args__` confirms this — `event_ids` has never had a GIN index, an expression index, or any other index in this schema's history.

**How `event_ids` is written** — `backend/app/ranking/score.py:859-895` (`_persist_daily_feeds`): one bulk `pg_insert(DailyFeed).values(chunk)` upsert per batch of users (`FEED_BUILD_USER_BATCH_SIZE = 500`, `backend/app/constants.py:473`), keyed on `(user_id, feed_date)`. Written once at 06:00 Tallinn time by `build_daily_feeds()` (`backend/app/ranking/score.py:912`), and again ad hoc by an on-demand single-user build path (`backend/app/ranking/score.py:1011`, same upsert helper) that races the scheduled job safely because it's an upsert. **`event_ids` is write-once-per-day-per-user, batch-inserted — never mutated element-by-element.**

**How `event_ids` is read today** — every existing read path queries `daily_feeds` by `(user_id, feed_date)` (the indexed path) and then uses the resulting row's `event_ids` array only to *hydrate* — i.e., `Event.id.in_(feed.event_ids)` to fetch the actual event rows, or `func.cardinality(DailyFeed.event_ids) > 0` to check non-emptiness:
- `backend/app/routers/feed.py:38-74` — `GET /feed`: fetch by `(user_id, feed_date)`, then `Event.id.in_(feed.event_ids)`.
- `backend/app/email/digest.py:290-296` — daily digest send: `DailyFeed.user_id.in_(user_ids), DailyFeed.feed_date == today`.
- `backend/app/ranking/score.py:587-590` — series-cooldown lookback: `DailyFeed.user_id.in_(user_ids), DailyFeed.feed_date >= cooldown_start, DailyFeed.feed_date < today`.

**No existing code path anywhere in the repo queries `daily_feeds` in the "given an event id, which rows/users contain it" direction.** The admin inspector's proposed "is event X in anyone's Daily 5 today" query would be a genuinely new query shape, not a variant of an existing indexed access pattern.

**Retention** — `DAILY_FEEDS_RETENTION_DAYS = 30` (`backend/app/constants.py:1303`), enforced by `cleanup.py:104-110` (`DailyFeed.feed_date < now - 30d` → delete). So the table is bounded to roughly 30 days of history at any time, not an ever-growing table like `events` (which `0023`'s migration message explicitly calls out as "the largest and forever-growing table in the schema" — `backend/alembic/versions/0023_bigo_audit_indexes_2.py:1-4` — `daily_feeds` is notably *not* described that way).

---

## 2. Scale: how many rows, how fast does it grow

**No production row-count or user-count figures exist anywhere in this repo** — no analytics dashboard config, no seed-data row counts, no capacity-planning doc. This section is reasoned from the pipeline design and code constants, not measured. Flagging explicitly per the instructions: **do not treat the numbers below as measured production data.**

- One `daily_feeds` row is created per verified user per calendar day (`build_daily_feeds` iterates `_verified_user_ids()`, `backend/app/ranking/score.py:680-691`, batched at `FEED_BUILD_USER_BATCH_SIZE = 500` per page — a pagination chunk size, not a user-count estimate).
- Each row's `event_ids` array holds up to `DAILY_5_COUNT = 5` element ids (`backend/app/constants.py:678`), occasionally more if the last backfill tier's uncapped sweep pulls in extra events under scarcity (`docs/pipeline.md:13`), but on the order of 5 integers per row, not dozens.
- With 30-day retention, steady-state row count ≈ `verified_user_count × 30` (plus whatever the on-demand single-build path adds, which upserts rather than inserting a second row for the same day).
- What's on Radar is explicitly described in `CLAUDE.md` as: "MVP complete plus a post-MVP self-service organizer portal... soft launch is live." This is a single-city (Tallinn), single-process app on Render's free tier (`CLAUDE.md`'s architecture diagram) — nothing in the repo suggests a user base beyond low hundreds to low thousands at this stage of a soft launch.

**NEEDS DEVELOPER INPUT:** actual verified-user count and actual `daily_feeds` row count (e.g. via `SELECT count(*) FROM daily_feeds` and `SELECT count(*) FROM users WHERE email_verified` against the real Neon database) were not available to this research pass — no DB credentials/data were read. Given 30-day retention and a soft-launch user base, this table is very plausibly small enough (thousands to low tens-of-thousands of rows) that a full-table scan with array unnesting would be fast in absolute terms even with zero index — but this is an inference from design, not a measurement, and should be confirmed against the real row count before deciding.

---

## 3. Does a GIN index on the array support "does this array contain event X"?

Source: PostgreSQL official docs, current version.

**`docs.postgresql.org/current/indexes-types.html`, §11.2.5 (GIN Indexes)**, verbatim:

> "GIN indexes are 'inverted indexes' which are appropriate for data values that contain multiple component values, such as arrays. An inverted index contains a separate entry for each component value, and can efficiently handle queries that test for the presence of specific component values."

The page's own worked example is specifically an array column, and states the built-in array GIN operator class supports indexed queries using: `<@  @>  =  &&`.

**`docs.postgresql.org/current/gin.html`, Table "Built-in GIN Operator Classes"**, the `array_ops` opclass indexable operators, verbatim:

```
&& (anyarray,anyarray)
@> (anyarray,anyarray)
<@ (anyarray,anyarray)
=  (anyarray,anyarray)
```

All four are **array-to-array** operators (both operands are arrays), not scalar-to-array. This matters directly for the query shape the admin inspector would need.

**`docs.postgresql.org/current/arrays.html`, §8.15.5 ("Searching in Arrays")**, verbatim, is the key nuance:

> "To search for a value in an array, each value must be checked... An alternative method is described in Section 9.25. The above query could be replaced by:
> `SELECT * FROM sal_emp WHERE 10000 = ANY (pay_by_quarter);`
> ...
> You can also search an array using the `&&` operator, which checks whether the left operand overlaps with the right operand. For instance:
> `SELECT * FROM sal_emp WHERE pay_by_quarter && ARRAY[10000];`
> This and other array operators are further described in Section 9.19. **It can be accelerated by an appropriate index, as described in Section 11.2.**"

Read literally: the docs present `x = ANY(array_column)` as the plain scalar-search form and `array_column && ARRAY[x]` (overlap) as the form that "can be accelerated by an appropriate index" — the index-acceleration sentence is attached to the `&&` example, not the `= ANY()` example. Combined with the operator table above (only `&&`, `@>`, `<@`, `=` are listed as GIN-indexable, and all are array-vs-array), the practical conclusion is:

- **`5 = ANY(event_ids)`** (the natural way to phrase "does event 5 appear in this row") is *not* the indexable form.
- To get GIN acceleration, the admin-inspector query must be rewritten as **`event_ids @> ARRAY[5]::bigint[]`** (containment: "does the array contain this single-element array") — semantically equivalent to "does 5 appear in event_ids," but expressed as an array-containment predicate so it matches the GIN opclass's supported operators.

**`intarray` extension (`docs.postgresql.org/current/intarray.html`)** — a contrib module offering an alternative, non-default GIN opclass `gin__int_ops` specifically for `int[]`/`int4[]`, adding operator support beyond the built-in class (including `<@`, `@>`, `&&`, `@@`) plus additional functions (`icount`, `sort`, etc.) not relevant here. `event_ids` is declared `ARRAY(BigInteger)` (i.e. `bigint[]`, not `int[]`/`int4[]`) — `intarray`'s `gin__int_ops` targets `int4` elements specifically, so it would not directly apply to a `bigint[]` column without a type change or a different extension; the **built-in `array_ops` GIN class works natively on any array type including `bigint[]`** and is the correct fit here without adding an extension.

**Conclusion on GIN**: a `CREATE INDEX ... USING GIN (event_ids)` on `daily_feeds.event_ids` (built-in `array_ops`, no extension needed) does give an indexed path for "does event X appear in this row," but only if the admin inspector's query is phrased as `event_ids @> ARRAY[:event_id]::bigint[]`, not `:event_id = ANY(event_ids)`.

---

## 4. Alternative: normalize into a join table

A `daily_feed_events(daily_feed_id, event_id)` table with a plain btree index on `event_id` (and probably a composite PK or unique constraint on `(daily_feed_id, event_id)`) would support the same query as a completely standard indexed lookup — `WHERE event_id = :x`, no GIN, no rewritten operator, trivially understandable by anyone reading the query.

**Cost of migrating, given how `event_ids` is actually used today:**

- **Write side** (`_persist_daily_feeds`, `backend/app/ranking/score.py:859-895`) currently does one bulk upsert per batch of users, one row per user containing the whole 5-element array. A join table would multiply row count by ~5× (one row per (user, event) pair instead of one row per user) and turn the write into either (a) a second bulk-insert for the child rows after the parent upsert, or (b) a bulk delete-then-insert of child rows per user per build (since `build_daily_feeds` re-computes from scratch each day and the on-demand path also upserts) — either way it's more moving parts in a job the repo's own conventions require to stay "a fixed number of queries independent of row count" (`docs/conventions.md:21`, batch-jobs rule). Still achievable as bulk operations (`INSERT ... SELECT` / `DELETE ... WHERE daily_feed_id = ANY(...)`), so it wouldn't *violate* the no-N+1 rule, but it is strictly more schema and more moving parts than today's single-array-column upsert.
- **Read side**: `GET /feed` (`backend/app/routers/feed.py:67-78`) explicitly relies on `event_ids`' **array order** to preserve feed ordering ("Preserve the feed ordering from daily_feeds.event_ids", `feed.py:77`). A join table has no inherent row order — you'd need an explicit `position` column on `daily_feed_events` to reconstruct ordering, adding another column and another thing to keep in sync at write time.
- The digest sender (`app/email/digest.py`) and the series-cooldown lookback (`app/ranking/score.py`) both currently fetch by `(user_id, feed_date)` only and never touch individual event membership — they'd be unaffected, but every one of them would need to `JOIN` (or a second query) against the new child table instead of reading `event_ids` directly off the row, i.e. this is not a purely additive change — it touches every existing read site.
- **Migration mechanics**: per `docs/conventions.md:20` ("Migrations — always chain migrations correctly... keep migrations small and reversible"), this would be a new table + a backfill of up to 30 days of existing `event_ids` arrays into it (`INSERT INTO daily_feed_events SELECT id, unnest(event_ids), ... FROM daily_feeds`) + eventually dropping or keeping `event_ids` as a redundant convenience column. Feasible, but a bigger and more invasive change than adding one index.

---

## 5. Fit with this repo's conventions

- **`docs/conventions.md:21`** ("Batch jobs — bulk-load, no N+1"): both options are compatible in principle (GIN index changes nothing about the write path; a join table's writes can stay bulk), but the join table adds real surface area to a job (`build_daily_feeds`) the repo has already gone through a dedicated "Big-O audit" migration pass to keep query-count-bounded (`0023_bigo_audit_indexes_2.py`'s docstring). Adding an index is zero-touch to that job; adding a join table is not.
- **`docs/conventions.md:20`** (migrations small and reversible): a single `CREATE INDEX ... USING GIN` is about as small and reversible as a migration gets — one `create_index`/`drop_index` pair, no data backfill, no behavior change to any existing query. A join table is a bigger, riskier migration (new table, backfill, changes to N read call sites) for a feature this ticket describes as a **read-only admin nice-to-have**, not a load-bearing product path.
- The repo's own prior Big-O audit (`0023_bigo_audit_indexes_2.py`) sets a precedent: it added targeted indexes reactively, specifically where a real query's predicate had no usable index (`ix_daily_feeds_feed_date` for `cleanup.py`'s sweep, `ix_user_event_scores_event_id`, `ix_events_price_min`, etc.) — small, single-purpose indexes justified by a specific query, not speculative schema redesign. Adding a GIN index (or, per the scale caveat below, no index at all) for one new admin query is consistent with that established pattern; standing up a join table is not — nothing else in the codebase currently needs event-membership lookups against `daily_feeds`.

---

## 6. Recommendation

Given:
1. There is no existing evidence (from this repo alone) that `daily_feeds` is large enough today for a full-table scan to be a real problem — 30-day retention (`DAILY_FEEDS_RETENTION_DAYS = 30`) bounds it to `≈ verified_users × 30` rows, and this is a Tallinn-only soft launch on a free-tier single-process backend (**NEEDS DEVELOPER INPUT**: confirm actual row count against the live DB before deciding — this research pass had no DB access).
2. The admin inspector is explicitly read-only and low-traffic (an internal tool screen, not a hot user-facing path) — it does not need to be fast in the way `GET /feed` needs to be fast.
3. `event_ids` is write-once-per-day, bulk-upserted, and read today only by `(user_id, feed_date)` — never by event id — so this would be a brand-new query shape with no existing precedent to match.

**Recommended approach, in order of preference:**

1. **First choice: no index at all — a plain `SELECT feed_date, user_id FROM daily_feeds WHERE event_ids @> ARRAY[:event_id]::bigint[] AND feed_date = CURRENT_DATE` (or unnest-and-join equivalent), unindexed.** For a table this small and a feature this low-traffic, a sequential scan restricted to `feed_date = today` (which *can* use the existing `ix_daily_feeds_feed_date` btree index to narrow the row set first) is very likely fast enough in absolute terms, and costs zero migration risk. This matches the ticket's own framing of the blocker as "no naive query has an indexed path" — the fix may simply be that no index is needed for a read-only admin tool at this scale, provided the query always filters by `feed_date` first (already indexed) and only then array-scans within that day's rows.
2. **If row-count reality (once confirmed) or observed query latency says otherwise: add a single GIN index** — `CREATE INDEX ix_daily_feeds_event_ids ON daily_feeds USING GIN (event_ids);` — and phrase the query as `event_ids @> ARRAY[:event_id]::bigint[]`, not `:event_id = ANY(event_ids)` (per §3 above, the latter does not use the GIN opclass's supported operators). This is a small, reversible, single-purpose migration consistent with the precedent set by `0023_bigo_audit_indexes_2.py`, and needs no application-code changes beyond the admin router itself.
3. **Do not build a join table for this.** The cost (new table, ordering column, backfill, touching every existing `daily_feeds` read site) is disproportionate to a read-only admin convenience feature, and nothing else in the codebase would benefit from the normalization — it would be schema churn in service of one low-traffic query that a GIN index (or no index) already answers.

**NEEDS DEVELOPER INPUT, consolidated:**
1. Actual `daily_feeds` row count / verified-user count from the live database — determines whether option 1 (no index) is already fast enough, or whether option 2 (GIN index) is worth adding preemptively. This research pass had no database access and explicitly avoided fabricating a precise figure.
2. Whether the admin inspector needs "today only" or "any historical day" membership — if historical (within the 30-day retention window), the `feed_date` pre-filter in option 1 won't narrow the scan nearly as much, which would tip the balance toward adding the GIN index sooner.
