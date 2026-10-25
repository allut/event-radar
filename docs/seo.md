# SEO and Prerender

What's in here: meta tags and hreflang, JSON-LD structured data, the build-time prerender, its round chaining and R2 chain-state, sitemap and robots, and the in-build and live checks.

## Meta Tags

- **`frontend/src/hooks/useSeoMeta.ts::useSeoMeta` sets every route's `<title>`, `<html lang>` and default `noindex`.** Landing, `/explore`, `/events/:id` and `/faq` pass `indexable: true`. That adds OG tags, a self-referential canonical and hreflang alternates (`en`/`et`/`ru` + `x-default`).
- **`/faq` turns `indexable` on only once its `FaqDoc` has loaded.** Until then it stays `noindex` with no canonical, which the prerender's readiness wait relies on.
- **Every other route goes through the thin `useStaticSeoMeta` wrapper.**
- **The legal pages (`/privacy`, `/terms`, `/ranking`, `/organizer-terms`) stay `noindex`.** They aren't prerendered, in the sitemap or in the robots allowlist. The draft Organizer terms must never become indexable by accident.
- **An unfiltered, default-sort `/explore?page=N` with N of 2 or more is self-canonical.** `useSeoMeta`'s `page` input appends `?page=N` to the canonical, every hreflang href and `og:url`. Page 1 stays the bare URL, so the prerender's canonical checks are unchanged.
- **A filtered, sorted or searched Explore view passes no `page`.** Its canonical stays `/explore` on every page.
- **The canonical follows the URL after a past-end clamp.** Explore holds `indexable` off while a page is empty but `total` is positive, and while a previous page shows as placeholder data. There is no JS `noindex` and no empty state for a past-end page.
- **`buildSeoMeta` is the pure builder behind the hook.** Tests assert on plain tag and link data instead of `react-helmet-async`'s DOM side effects.
- **`frontend/src/components/SeoTags/` is a thin, untested `react-helmet-async` render shell.** The unit tests for `buildSeoMeta` and the structured-data builders cover the data it renders.
- **Every JSON-LD body goes through `frontend/src/lib/jsonLd.ts::serializeJsonLd()`**, which escapes each `<` to `\u003c`. `SeoTags` and the prerender's change-marker re-save both use it. A bare `JSON.stringify` would let event text containing `</script` break out of the tag.

## Structured Data

`frontend/src/lib/structuredData.ts` builds schema.org JSON-LD typed against `schema-dts`.

- **`buildEventJsonLd` never emits `organizer` or `offers.availability`.** No real data backs either. Add them only alongside a data-model change that does.
- **A known `price_min` emits an `AggregateOffer`; otherwise a plain `Offer`.** The check is `price_min !== null`, so a free event's `0` still emits `lowPrice: 0`.
- **`priceCurrency` falls back to `DEFAULT_CURRENCY`.** A free event can lose its currency at ingest, and the validator requires `priceCurrency` once `lowPrice` is present. Dropping it would silently cost the offer its rich-result eligibility.
- **`image` falls back to the same asset as `og:image`.** The two must never pick different fallbacks.
- **`buildWebsiteJsonLd` (Landing) carries only `name`, `url` and `inLanguage`.**
- **`buildExploreItemListJsonLd` emits one `ListItem` per event on the current `/explore` page**, with `position` 1 to n in render order, the same signed in or out (the sign-up strip is not an item). Each `item` is the full `buildEventJsonLd` payload, so there is one field-mapping policy.
- **Each list `item` adds a top-level `url` to the locale-matched detail page.** It is distinct from `offers.url`, which is the external ticket link.
- **The `ItemList` omits `numberOfItems` and `itemListOrder`.** schema.org defines `numberOfItems` as the count for the entire list, which would be wrong on a one-page snapshot, and Google doesn't ask for either.
- **The `ItemList` never includes the Sponsored slot.** `Explore` passes `events` (organic rows) only, so `position` stays contiguous 1 to n and a paid placement never poses as a result. The slot tile is rendered from `sponsored_slot`, outside `events`.
- **Paid links carry `rel="sponsored"`.** The slot card's stretched link is `sponsored` and its ticket link `sponsored noopener noreferrer` (`SPONSORED_LINK_REL`, `SPONSORED_TICKET_REL`). The promoted event's own page, its JSON-LD, the sitemap and the `?page=N` canonicals are unchanged.
- **The prerender never requests a slot.** `Explore` omits `sponsored_slot=true` while `isPrerenderRender()` (`PRERENDER_RUNTIME_FLAG`) is true, so no snapshot freezes a paid tile. `validateSnapshotStructure` is the backstop (see Structural Checks).
- **`/faq` emits no JSON-LD.**

## Build-Time Prerender

`frontend/scripts/prerender.ts` snapshots Landing, `/explore`, `/faq` and every published `/events/:id`, in all three locale variants, so crawlers get real HTML.

- **It runs as the last step of `npm run build`, only when `$CF_PAGES` or `$PRERENDER_LOCAL` is set.** A plain local build skips both the Playwright install and the pass.
- **`main()` returns early on a preview build**, before any rendering, sitemap write, validation or marker commit. `isPreviewBuild()` is `CF_PAGES === '1'` on a branch other than production. Production builds from `release`; see CLAUDE.md's Traps.
- **The target list comes from `GET /public/prerender-events`** (`backend/app/routers/public.py::prerender_events`), the single source of truth for what's published. See [pipeline.md](pipeline.md)'s Read Paths section.
- **It serves `dist/` with `vite preview` and drives it with Playwright's bundled Chromium.** `vite.config.ts`'s `preview.proxy` forwards `/api` to `PRERENDER_API_ORIGIN`, which defaults to the production Render origin.
- **The worker pool is `PRERENDER_CONCURRENCY` (`frontend/src/constants/prerender.ts`).** `NAV_TIMEOUT_MS` and `CONTENT_READY_TIMEOUT_MS` are 3× the local values. A local repro showed the build machine's software-rendered Chromium is simply slower, whatever the concurrency.
- **Each snapshot lands at `dist/<locale-prefix>/.../index.html`.** That's the directory-index shape `frontend/functions/[[path]].ts` resolves through `env.ASSETS.fetch()`, so a prerendered path is served as-is.
- **The build fails (non-zero exit)** if the published-events fetch fails or any target can't render within its timeout.
- **Rounds chain across builds through a git-committed `RoundMarker`.** See Round Chaining below. The cron job and Deploy Hook are in [backend-ops.md](backend-ops.md)'s Prerender Cadence section.

### Targets

- **`buildTargets` keeps home first, then `/explore`, then `/faq`, in each locale.** The live audit reads sitemap freshness off the first `<lastmod>`, so home must stay at index 0.
- **Home, `/explore` and `/faq` carry no `eventId`, so they always render fresh.** `classifyTarget` never copies them forward, and they can't key into the R2 manifest.
- **`/faq` carries a `lastmod` from its three `FaqDoc` modules' `lastUpdated`.** They're imported statically, not through `FAQ_LOADERS`. This content date stays separate from the event-only `updatedAt` change marker.
- **`eventDetailRateGate`, the `GET /events/{id}` budget, is keyed on `target.eventId !== undefined`.** So `/explore` doesn't spend it.

### Readiness

- **`page.goto` waits on `domcontentloaded`, then on the route-specific canonical** (`contentReadySelector`, built from `canonicalUrlFor` in `useSeoMeta.ts`). The canonical only attaches once `indexable` flips true, which for `/events/:id` means the event has loaded.
- **Any-canonical isn't enough.** Mid-round, `dist/index.html` is the Estonian Landing snapshot, and `vite preview` serves it as the fallback for unrendered routes. A bare canonical wait would resolve on Landing's tag.
- **`validateSnapshotStructure`'s `expectedCanonical` option fails a snapshot whose canonical isn't exactly the route's URL.** Waiting on `networkidle` cost ≥500ms per route and caught nothing more.
- **`/explore` waits on `PRERENDER_READY_SELECTOR` instead.** `Explore.tsx` sets `data-prerender-ready="true"` once its query settles, on success or error, never while loading.
- **`data-prerender-error="true"` makes `snapshotTarget` throw.** The failure takes the normal build-failing path instead of shipping a `noindex` page.

### SPA Fallback Shell

- **`npm run build` copies `dist/index.html` to `dist/app-shell.html` before the prerender runs.** The Estonian Landing snapshot later overwrites `dist/index.html`, and the copy exists even if the script dies midway.
- **`frontend/functions/[[path]].ts` serves `app-shell.html` for every route that isn't prerendered.** `/saved`, `/settings` and the rest get the untouched CSR shell, never a mismatched snapshot. Its fetch-first order is in [backend-ops.md](backend-ops.md)'s SPA Fallback section.
- **`/explore?page=N` with N of 2 or more also gets the shell**, in all three locales. The page-1 snapshot would carry a static page-1 canonical and `ItemList`. Page 1, a malformed `page` and any other query string keep the snapshot. Only page 1 is prerendered, and the sitemap has no page entries by design.

### Change Detection and Copy-Forward

- **`classifyTarget` diffs each event route's live production page against the target every round.** It compares the embedded `dateModified` marker (`embedChangeMarker`/`extractChangeMarker`, keyed on `Event.updated_at`).
- **An unchanged route copies its live HTML to `dist/` with no render.** That keeps a catalog of thousands of routes inside the per-round render budget. A mismatch, or no live page yet, renders fresh.
- **The live HTML doubles as a stale fallback for a route the budget never reaches.** It's written after the render pool, once the skipped targets are known.
- **Copied HTML gets its asset references rewritten** by `rewriteSnapshotAssetRefs(html, shellHtml)`. A copied page carries an older build's content-hashed `dist/assets/*` names, which Vite re-mints on every source change. Nothing else re-validates a copied snapshot, so dead references would ship silently.
- **`rewriteSnapshotAssetRefs` swaps only the `<head>` script and link asset nodes**, in order. JSON-LD, the change marker and Helmet's `data-rh` tags stay byte-for-byte. It throws if `shellHtml` has no asset references, since a silent no-op would bring the bug back.
- **`shellHtml` is read once per round from `dist/app-shell.html` (`APP_SHELL_FILENAME`), never `dist/index.html`.** The home snapshot overwrites `index.html` partway through the round.
- **Stale references self-heal.** Every target is reclassified every round, so the next production build rewrites them with no manual backfill.

### Theme-Neutral Snapshots

- **Every snapshot write goes through `finalizeSnapshotHtml`.** It runs `rewriteSnapshotAssetRefs` (copy-forward writes only), then `stripBakedThemeAttr`, unless the copy is already final (see Measured Cost).
- **`stripBakedThemeAttr` removes the build browser's `data-theme` from `<html>`.** `index.html`'s pre-paint script sets it from the build machine's OS theme. Left in, every visitor would see that theme until client JS re-resolved it.
- **The strip is idempotent and leaves `lang` and `data-rh` alone.** With no `data-theme`, the page shows the dark origin palette only until the pre-paint script sets the real value before first paint. That script runs under a CSP hash; see [security.md](security.md)'s Frontend CSP section.

### Measured Cost

- **First real Cloudflare burst (2026-10-03, 5,442 routes, `PRERENDER_RENDER_BUDGET_MINUTES=10`):** three rounds rendered 1,012, 1,012 and 334 routes, each validating clean. Rendering ran at about 100 routes a minute, and the rounds took about 16, 20 and 11 minutes.
- **Resumed rounds spend 5–6 minutes in copy-forward and about 3 validating.** Round 1's copy-forward took 84 s. Each round logs `prerender: peak RSS`, which covers the node process only, not Chromium.
- **Single-round burst (2026-10-10, 5,610 routes, Node 24):** copy-forward of 4,710 routes took 4 min 7 s, rendering 900 took 8 min 16 s, validation about 3 min. Peak RSS was 1,582 MiB.
- **Fused change detection (2026-10-12, 5,685 routes):** classify plus copy-forward of 5,472 routes took 3 min 34 s, about 39 ms a route against 52 ms on 2026-10-10. Finalize was 85 s of that; fetch dominates. Peak RSS was 1,242 MiB.
- **A release that changes asset hashes skips JSDOM for no copy.** That run logged 0/5,472. The fast path pays off on a rebuild of the same commit.
- **Classify and copy-forward share one pool.** Each route's live HTML is written and released as soon as its fetch returns, so fetches overlap JSDOM work and the round never holds every body at once.
- **`finalizeSnapshotHtml` skips JSDOM for a copy that is already final.** `isAlreadyFinalized` string-checks that the `<head>` asset tags equal the shell's JSDOM-serialized tags, in order, and that `<html>` has no `data-theme`. Any mismatch takes the JSDOM path. A JSDOM pass costs 25–40 ms per page; the check costs about 0.01 ms.
- **Eager PUTs on a `done` round stalled its summary (2026-10-12).** About 5.7k chain-state PUTs at roughly 12 a second held `wrote` → `round summary` for 1 min 55 s, then were deleted. Held PUTs fix that; see Chain-State Manifest's Write Path.
- **Each round logs `prerender: chain-state drain took` and `chain-state finalize … took`.** They split the end-of-build time between the PUT drain and the index write or prefix delete.
- **Each round logs a `prerender: change detection took` line.** It splits fetch time (summed across workers) from finalize time and counts the copies that skipped JSDOM.
- **The other cost trims stay in place.** `extractChangeMarker` regex-scans the first JSON-LD script instead of re-parsing the DOM, and the live-API staleness check runs for the default locale only.

## Round Chaining

One build can't always render every route within `PRERENDER_RENDER_BUDGET_MINUTES`. A round that runs out of budget hands the rest to a continuation round, and the rounds of one burst share state through a `RoundMarker` commit (`frontend/src/lib/prerenderChain.ts`).

- **A burst stops at `CHAIN_MAX_ROUNDS` (10) rounds**, and earlier on a round that makes zero progress.
- **The marker carries round state in its commit message.** `prerender.ts::commitRoundMarker` advances `heads/{branch}` through the GitHub Git Data API.
- **That push is the only continuation trigger.** The production branch is git-connected, so the push alone starts the next build. A separate chain Deploy Hook once fired a redundant second build of the same commit.
- **`shouldCommitRoundMarker` pushes only a `continuing` marker.** A pushed `done` marker still starts a build, and that build begins a fresh burst at round 1 instead of stopping.

### Resume Check

- **Every build reads the tip commit's marker before any work** (`resolveRoundStart`). Cloudflare exposes only `CF_PAGES_COMMIT_SHA`, not the message, so the build fetches the message through the authenticated GitHub API.
- **A fresh `continuing` marker resumes the burst at `round + 1`.** Fresh means younger than `CHAIN_STALENESS_TIMEOUT_MINUTES` (30).
- **A stale, missing or `done` marker starts a new burst at round 1.** A stale `continuing` marker means a crashed build, not an active one.
- **Freshness is the only way to tell the intended continuation from a racing build.** An earlier guard skipped both, so the chain never got past round 1.

## Chain-State Manifest (R2)

An optimization layer over the `RoundMarker` chain. It gives resumed rounds per-target identity, so rounds 2+ read a resolved target's HTML from Cloudflare R2 instead of re-fetching production.

- **Why: `RoundMarker` carries only aggregate counters.** Without per-target identity, every resumed round still called `classifyTarget`, a production fetch, for every target. Change-detection traffic stayed at `targets.length` instead of shrinking.
- **Storage is R2 over its S3 API (`@aws-sdk/client-s3`), not a Pages R2 binding.** `prerender.ts` runs as a Node build script, not a Worker.
- **`frontend/src/lib/r2ChainState.ts` is the whole client boundary**: `getR2Object`, `putR2Object` and `deleteR2ObjectsByPrefix`. It knows nothing of the key format or schema, which keeps it testable on its own. It memoizes its `S3Client` on the credential tuple.
- **The bucket, credentials and lifecycle rule are operator setup.** See [backend-ops.md](backend-ops.md)'s R2 Chain-State Bucket section.

### Layout

- **Each burst lives under `prerender-chain-state/{sanitizedBurstId}/` (`CHAIN_STATE_PREFIX`).** `sanitizeBurstIdForR2` swaps `:` and `.` for `-`, because some S3 tooling chokes on the ISO timestamp's colons. `RoundMarker.burstId`, the value rounds compare, stays untouched.
- **`index.json` maps `{locale}:{eventId}` to `{ resolvedAtRound }`.** Each resolved target's post-`finalizeSnapshotHtml` bytes sit at `targets/{locale}-{eventId}.html`. A key in the index means resolved; there's no status enum.
- **The manifest stores content, not just status.** Every deploy replaces the whole site, so a resolved target still needs its bytes in each later round. A status-only manifest would still fetch production for the HTML.

### Read Path

- **Round 1 never reads.** Its `burstId` is new, so no manifest exists yet.
- **Round 2+ reads the index once and splits the targets** (`partitionByChainState`). Both groups run through the same `mapPool` under `CHANGE_DETECTION_CONCURRENCY`, so the cap on production never stacks and `classification` keeps `targets` order.
- **`fetchResolvedTarget` returns the same `ChangeDetectionResult` shape as `classifyTarget`.** Copy-forward, `prioritizeRenderQueue` and the sitemap builder can't tell the two apart.
- **It re-diffs the cached marker against `target.updatedAt` before trusting the bytes.** `fetchPrerenderCandidates()` re-reads `updated_at` every round and a burst spans several, so a mismatch falls back to a fresh `classifyTarget`.

### Write Path

- **A target earns an entry only with finalized HTML in hand**: on copy-forward, or after a successful `snapshotTarget` render. `persistChainStateTarget` writes the index entry only after the content PUT succeeds.
- **The stale-fallback write never earns an entry.** Budget-skipped content still owes a real render; marking it resolved would skip it for the rest of the burst.
- **A target already sourced from the manifest isn't re-PUT.**
- **The index is PUT once**, at the end of `main()` beside `commitRoundMarker`. Concurrent read-modify-write on one shared object would race.
- **Content PUTs start held (`frontend/scripts/prerender.ts::createChainStatePersister()`).** Only a `continuing` round's chain state is read back, and a `done` round deletes the prefix, so a `done` round makes no PUTs. A held target keeps no HTML; its bytes already sit in `dist/`.
- **`frontend/src/lib/prerenderChain.ts::predictRoundContinues()` releases them after change detection** when the render queue exceeds the budget × `PRERENDER_ROUTES_PER_MINUTE` × `PRERENDER_CONTINUE_PREDICTION_MARGIN`. Released PUTs re-read `dist/` and overlap rendering, and later records PUT straight from memory.
- **After rendering, the real marker status decides.** A `continuing` round flushes anything still held; a `done` round drops it. A wrong `done` guess costs only that late flush, so the margin sits below 1. PUTs drain with `Promise.allSettled` before the round summary.

### Cleanup

- **`finalizeChainState` mirrors `shouldCommitRoundMarker`.** A `continuing` round writes the index; a `done` round deletes the burst's whole prefix.
- **`deleteR2ObjectsByPrefix` pages through `ListObjectsV2`**, since a burst exceeds the 1,000-key page. It checks `DeleteObjectsCommand`'s `Errors` array, because S3 reports a per-object failure as HTTP 200.
- **A bucket lifecycle rule backstops a `done` round that crashed before deleting.** It's dashboard config, so `CHAIN_STATE_LIFECYCLE_DAYS` only documents the value.

### Failure Posture

- **R2 is an optimization, never a correctness dependency.** Every failure degrades to a full re-fetch, and none fails the build. Logging stays at `console.log`/`console.error`, with no admin alert.
- **Each failure has a defined fallback.** Unset credentials no-op. A failed or malformed index read means "no manifest yet". A content miss re-runs `classifyTarget` for that target. A failed write costs only this burst's savings.
- **Accepted trade-off: cached HTML can lag a same-burst edit.** The marker re-diff catches any edit that moves `Event.updated_at`. Only changes invisible to the marker slip through, the same blind spot copy-forward has, and the next burst heals them.

## Sitemap and Robots

- **`buildSitemapXml` and `buildRobotsTxt` (`prerender.ts`) write to `dist/` before the snapshot pass, from the same `targets` list.** The sitemap can never list a URL the snapshots don't cover.
- **Each `<url>` gets `<lastmod>` = `target.updatedAt ?? target.lastmod ?? buildTimestamp`.** That's the event's `updated_at`, else the page's content date, else the build time. `en`/`et`/`ru`/`x-default` alternates mirror `useSeoMeta`'s hreflang set.
- **`robots.txt` is an allowlist**: `Disallow: /`, then `Allow:` for `/$`, `/events/`, `/explore` and `/faq` and their `/en` and `/ru` forms, plus a `Sitemap:` line. A new signed-in route stays excluded with no robots edit.
- **`/explore` and `/faq` aren't `$`-anchored.** Filtered `/explore?category=…` URLs stay crawlable. The canonical alone controls indexing: no query-string `Disallow` and no param-conditional `noindex`.

## Local Dry Run

- **`PRERENDER_LOCAL=1 PRERENDER_API_ORIGIN=http://127.0.0.1:8000 npm run build` runs the full pipeline against a local backend.** `PRERENDER_LOCAL` alone runs it against production data.

## In-Build Validation Gate

`prerender.ts::validateTarget` reads each newly rendered snapshot back off disk and checks it with `frontend/src/lib/seoValidation.ts`. Any failure blocks the deploy.

- **Only this round's new renders are validated** (`selectValidationTargets`). Copied-forward routes are byte-identical to snapshots that already passed, so the `validated N snapshot(s)` log counts `newlyRendered`.
- **The gate checks SEO structure, never asset references.** Stale asset hashes are `rewriteSnapshotAssetRefs`'s job.
- **`seoValidation.ts` stays filesystem- and network-free.** It parses an HTML string and compares against a passed-in event, so the live audit reuses `parseSnapshotHtml` and `validateSnapshotStructure` unchanged.

### Structural Checks

- **`validateSnapshotStructure` requires a non-default `<title>` and a canonical on `PRODUCTION_ORIGIN`.** It also needs every `SEO_HREFLANG_CODES` alternate, `<meta name="robots" content="index, follow">`, and exactly one valid JSON-LD script.
- **The JSON-LD check depends on `kind`: `'event'`, `'website'`, `'list'` or `'page'`.** `'page'` (`/faq`) requires zero JSON-LD scripts instead of one.
- **`assertEventJsonLd` checks Google's required Event fields** (`name`, `startDate`, `location`) and its "image or offers" recommendation. It never checks `eventStatus`, `organizer` or `offers.availability`, matching the builder. Price fields are checked only once `lowPrice` is present.
- **`validateSnapshotStructure` fails any snapshot containing the Sponsored slot marker (`SPONSORED_SLOT_ATTR`).** The prerender sets `PRERENDER_RUNTIME_FLAG` so Explore never requests a slot, and the validator catches a regression of that gate.
- **`assertListJsonLd` checks the `ItemList` shape, `position` running exactly `1..n`, and each `item` through `assertEventJsonLd`.** Each `item.url` must be unique, on `PRODUCTION_ORIGIN` and fragment-free, and each `item.image` present.
- **The `≥3 items` check is skipped when the live catalog itself is thinner.** `fetchLiveExploreCount` re-queries `GET /explore` and returns `min(total, BROWSE_PAGE_SIZE)`. The anonymous sign-up strip sits above the grid and takes no event's slot, so the snapshot lists every fetched event.
- **A literal `<` in a JSON-LD body fails the snapshot** (`ParsedSnapshot.jsonLdRaw`). A full `</script` breakout truncates the body and fails the JSON parse instead.

### Staleness Checks

- **`compareEventStaleness` re-fetches `GET /events/{id}` and diffs title, venue and price.** It shares `eventDetailRateGate`'s budget. Title and venue come off the snapshot's JSON-LD.
- **Price is diffed off a DOM marker, not the JSON-LD.** The `AggregateOffer` lacks `has_free_tier` and exists only when `price_min !== null`.
- **`EventDetail.tsx`'s price span is the marker.** It carries `data-testid="event-price"` plus `data-price-min`, `data-price-max`, `data-currency` and `data-has-free-tier`, present exactly when `formatPrice` renders.
- **`/explore` has no staleness diff.** It always renders fresh, so there's no earlier snapshot to compare.

## Live Audit

`frontend/functions/api/seo-audit.ts` checks production every 6 hours, independent of any build. It's the one check that catches a dead Deploy Hook or cron. Its schedule and secrets are in [backend-ops.md](backend-ops.md)'s External Cron Jobs section.

- **`frontend/src/lib/seoAudit.ts::evaluateLiveAudit` is network-free and unit-tested.** It runs the robots, freshness and structure checks below.
- **Robots: `isPathAllowedByRules` flags a blocked `sitemap.xml`, OG fallback image, `/assets/` or `CRAWLABLE_ICON_PATHS` entry.** It follows Google's matching semantics. A stray `Disallow: /` once blocked the sitemap and nothing else in the pipeline noticed.
- **Freshness: a first `<lastmod>` older than `SEO_AUDIT_STALE_THRESHOLD_HOURS` means a dead cadence.** The 8 hours are the 6-hour publish cadence plus a 2-hour buffer.
- **Structure: it validates live Landing (`'website'`), one event page (`'event'`) and `/explore` in all three locales (`'list'`).** The event is the first bare-Estonian URL in the sitemap (`parseSitemapEventUrls`). The event and `/explore` checks are best-effort.
- **The live `/explore` check passes no `liveItemCount`**, so `assertListJsonLd`'s `≥3` check no-ops there.
- **The function itself checks content types.** `/favicon.ico` must be `image/*`, and the event page's `/assets/*` files must be CSS or JavaScript. A missing file falls through `frontend/functions/[[path]].ts` as a 200 HTML app shell, so a wrong type means a missing favicon or a dead asset hash.
- **`parseSnapshotAssetUrls` keeps only references that resolve to `PRODUCTION_ORIGIN`.** An injected `@evil.example/assets/x.css` can't redirect the Worker's fetch.
- **It alerts and never blocks.** A failure files or comments on the open `seo-audit-failure` GitHub issue (`seoAuditIssue.ts::reportAuditFailure`). A pass closes it (`reportAuditRecovery`).
- **Auth is the `x-seo-audit-token` header, constant-time-compared by `seoAuditAuth.ts::isValidAuditToken`.** Without both its Pages Secrets the endpoint returns 500 instead of silently no-oping.

## Prerender Cadence Gate

- **`frontend/functions/api/prerender-cadence.ts` sits between cron-job.org and the rebuild Deploy Hook.** It skips a tick when `frontend/src/lib/prerenderChain.ts::shouldSkipCadenceTick` says a chain round is in flight, so two builds never resume the same marker.
- **Without the gate, a tick during a round would race the real continuation.** Both builds would resume the same fresh marker. The gate removes the race at its source instead of leaving the two pushes to sort it out.
- **It reads the production branch's tip commit through the authenticated GitHub API.** A missing token or a GitHub error fails open and fires the hook, so the collision check can't silently kill the cadence.
- **It has the same shape as `seo-audit.ts`**: a thin handler, `isValidAuditToken` auth with its own header, and the shared `_shared/cloudflare.ts` types. Its secrets are in [backend-ops.md](backend-ops.md)'s External Cron Jobs section.
