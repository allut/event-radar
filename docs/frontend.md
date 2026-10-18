# Frontend

What's in here: folder conventions, routing and locale prefixes, the admin console, paged lists, the FAQ page, the API client, auth hints, tests, i18n, brand assets and email.

## Frontend Structure

Routes (pages) live in `frontend/src/routes/`, shared components in `frontend/src/components/` and hooks in `frontend/src/hooks/`. The folders and `App.tsx`'s `ROUTE_DEFS` are the inventory; this section holds the rules.

### Folders and Barrels

- **Each component and route gets its own folder:** `Name.tsx`, `Name.module.css` and a one-line `index.ts` barrel (`export { default } from './Name'`). The barrel keeps imports short: `./components/EventCard`, not `./components/EventCard/EventCard`.
- **A folder skips its stylesheet when it renders no styled DOM of its own.** That covers thin wrappers (`Privacy/` and `Terms/` over `LegalPage`), shells (`SeoTags/`, `AdminApp/`), delegators (`AdminThemeToggle/` over `SelectMenu`) and `ChevronIcons/`, which its consumers style.
- **The top-bar family composes from `components/shared/Bar.module.css` instead.** `TopBar/`, `OrganizerTopBar/` and the sub-components they assemble carry no stylesheet. `DialMark/` and `MobileMenu/` keep their own.
- **A route-private subcomponent is a bare `Name.tsx` beside its parent, with no folder or barrel.** Nothing outside the parent imports it, so a barrel would shorten nothing. `Explore/UpsellCard.tsx` and `RichTextEditor/icons.tsx` are examples. Promote one to a folder only when a second parent imports it.

### Helper Homes

- **`localizedPath()` and `stripLocalePrefix()` live in `frontend/src/lib/urlLocale.ts`, re-exported through `utils.ts`.** They're the one deliberate exception to "shared helpers live in `utils.ts`". The module's own comment says why.
- **`StaticPage/`'s component has no importer, but its stylesheet is live.** `Contact.module.css` composes `.page`, `.main`, `.title` and `.body` from it. It stays as the scaffold for future static pages.
- **`components/shared/` is the shared CSS layer.** See [design-system.md](design-system.md) §7 for the composing rules.
- **`GoogleSignInButton/` is a plain `<a href>` to the backend's OAuth `start` endpoint, with no client-side OAuth.** Its plate colors are Google-mandated, held as `--google-btn-*` tokens in `index.css`. The mark itself is covered by design-system.md's Google Sign-In Mark section.
- **The `VITE_GOOGLE_SIGNIN_*` build flags are a frontend convenience gate only.** The backend `start` endpoint 404s on its own when its flag is off. [backend-ops.md](backend-ops.md)'s Cloudflare Pages Frontend section says where the flags are set.

### Routing

- **`App.tsx`'s `Home` picks `Landing` or `Feed` from `useAuth()`, a live subscription.** A one-shot `isAuthenticated()` read would leave a stale Feed on screen after signing out on `/`.
- **Organizer routes sit behind `OrganizerProtected`.** It mirrors `Protected` but reads `useOrganizerAuth()` and redirects to `/organizer/login`. The auth tracks never share a guard; see [security.md](security.md)'s Track Separation section.
- **Trigger-button popovers build on `hooks/useDropdown.ts`.** It owns open and close, outside-click, Escape, focus and the mobile flip. `FacetMenu`, `SelectMenu`, `DatePicker` and `EventOverflowMenu` all use it.
- **Each card list resolves `useEventCardNav()` once and passes the result as `EventCard`'s `nav` prop.** That way no card subscribes to the router or the auth store itself.

### Top Bar Behaviour

- **The account identity loads when the menu or drawer opens, never on mount.** That's `GET /auth/me`, or `GET /organizer/profile` on the organizer bar.
- **The bar condenses on every route through `useBarScrolled()`:** past 24px, and back under 4px. It starts unscrolled, so prerendered HTML shows the unscrolled bar.
- **`Footer` labels follow the URL's locale through `usePathLocale()`, never the saved preference.** Its FAQ link always goes to the public `/faq`, organizer pages included.
- **Sponsored slot (`components/SponsoredSlot/`, `constants/sponsored.ts`):** `EventCard`'s optional `sponsored` prop (`{ advertiser, explanation }`) renders the caption, the "Why?" panel, the slot marker, `rel="sponsored"` on the stretched link and `rel="sponsored noopener noreferrer"` on the ticket link. The `explanation` is `filters`, `none` (Explore, from the API) or `daily5`. The strings (`sponsored_*`) and the marker attribute are in `shared/`.
- **The "Why?" link stays a plain `/ranking#ads` link.** Explore and Daily 5 both render the card through `EventCard`.
- **Daily 5 (`routes/Feed/`) renders the `sponsored_slot` after the `<ol>`,** in its own `<section>` with a hairline `--rule`, a small `sponsored_daily5_caption` line and no numeral. The `RankingLink` follows it. The card is passed `explanation: 'daily5'` by the API.
- **A sponsored card's links carry `?ref=ad`, and its dislike sends `ref: 'ad'`.** `EventDetail` passes a known `ref` on its first request only, then strips it from the URL, so a reload or share can't count again.
- **Explore opts in with `sponsored_slot=true` unless `isPrerenderRender()`.** It reads the `PRERENDER_RUNTIME_FLAG` window flag that `scripts/prerender.ts` sets with `addInitScript`. Page 1 inserts the payload card at `tile` (the 4th card, after the sign-up strip). Only organic `events` feed the `ItemList` and the range label, so positions skip the slot. The pager reads `page1_has_slot` through `slotRows`.
- **`/ranking` is a `LegalPage` doc, and `RankingLink` is its entry point.** Explore's results header, the Daily 5 list and the `Footer` link to it in every state. A `LegalSection.id` becomes the anchor, scrolled to once the lazy doc loads.

### Admin Console

- **`routes/AdminApp/` dispatches admin screens on `pathname`, outside `ROUTE_DEFS` and the locale-prefix loop.** It's reached by typed URL or bookmark only.
- **It loads behind one `React.lazy` chunk,** so a signed-out visit to a public route never downloads it.
- **The admin console is English-only and skips the shared/i18n workflow.** Its strings are literals, such as `utils.ts::relativeTimeFromNow()`.
- **`<Pager>` is the exception: admin renders it from shared/i18n with `LOCALE_EN`.** One component serves every list, so its strings live in the catalogue rather than in a second English copy.
- **Resolving queues page through `hooks/useAdminQueuePage.ts` and `AdminQueueSplitView`.** Each row-removing action tags its row in place and refetches the current page once, so rows pulled up from the next page append at the bottom and paging on never skips a row.
- **An action passes `tagRow` the `actionSpot(item)` it captured when triggered:** the page offset and the row's slot. One that resolves after the admin changed page only refetches, and leaves the new page's note draft alone. On the same page it always tags, at the captured slot if a refetch already dropped the row.
- **A 409 or 404 on an action means another admin got there first.** `onError` calls `resyncAfterFailedAction`, which refetches the page and `/admin/counts` so the stale row drops out; the error toast still shows.
- **A queue page holds while it has tagged rows**, so clearing a last page leaves the no-items label, not a clamp. A page change selects and focuses the first row, marks it `aria-current="true"`, resets the list scroll and clears the tags. The pager sits in the split view's `listFooter`, outside the scroll area.
- **A silent clamp onto another page resets the queue without moving focus.** It selects the first row, clears the tags and resets the note.
- **Admin Reports sends `report=<id>` to the server only while the URL has no `page`.** The server-placed offset syncs through `usePagedQuery`'s silent replace, silently. Page links drop `report` (`dropOnPageChange`); a located row on page 1 keeps it. A gone row shows a gold "already resolved" callout linking to the event, except right after this screen resolved it.
- **The locate runs once per link.** A row located on page 1 leaves no `page` in the URL, so later refetches ask for the plain page and keep the first not-found flag. Re-locating would jump pages once the row moved.
- **"Already located" is this mount's record or the locate query's cached data.** The cache covers a remount; the record covers a long mount whose inactive locate entry was garbage-collected.
- **Admin Reports invalidates the whole `[adminReports]` prefix** (`invalidateKey`) on an action or a 409/404. The plain pages go stale even in locate mode; only the mounted query refetches.
- **Admin Claims keeps its tab in the URL as `?status=approved`** (pending omitted), written through `setListParams` so a switch is one push to page 1. The queue is keyed by tab, so the selection, note draft and tags never leak across tabs.
- **Admin Claims keeps the toast in the unkeyed parent** and passes `showToast` down, so an action that fails after a tab switch still reports. An action invalidates the whole claims prefix (`invalidateKey`), refetching whichever tab is mounted.
- **Promotions (#600) live in two places, both English literals from `constants/promotions.ts`.** `/admin/promotions` shows the 14-day `PromotionCapStrip` and a `PromotionsTable` list filtered by `?state=` (all, live, scheduled, finished). Granting happens on the event's detail page, in its Promotions tab (`PromotionsPanel`).
- **`PromotionGrantForm` validates dates against the server, never locally.** `GET /admin/events/{id}/promotions/validate` returns the window, overlap and cap errors and the price, so the form carries no copy of those rules. It pre-checks only the field rules it can (registry code of 8 digits, `ER-M-` invoice prefix, a note for complimentary). The strip highlights the picked window.
- **A row's pill is computed in `lib/promotions.ts::promotionPill()`** from the computed state and the stored status (awaiting payment, ended early, void), with the not-showing reason under it. A cap-day count comes from the API, so the strip needs no constant for the cap.
- **The Promotion detail (#601, #606) is `/admin/promotions/:id`, reached from a row's Manage link.** `AdminApp` dispatches it by path prefix. One `GET /admin/promotions/{id}` feeds the header, record, snapshots and audit; the per-day table has its own `daily-stats` query.
- **Detail action buttons follow the API's `actions` flags and never recompute a rule.** Each opens an inline panel, never a modal. A command's refusal shows inside its panel, and any command error refetches the detail.
- **A command's response is the refreshed detail, written straight into the query cache.** The list, cap strip, grant context and per-day table are invalidated. Edit sends only the changed fields, and a live edit sends just `end_date`.
- **The per-day table lists complete days only and always shows the note that served is not seen.** Totals are summed client-side from the rows; gate labels come from `PROMOTION_GATE_REASON_LABELS`.
- **`AdminShell/` is the nav-rail chrome every signed-in admin screen renders inside.** `AdminLogin` renders outside it. The console replaces curl calls to `/admin/*`; see [backend-ops.md](backend-ops.md)'s Admin Endpoints section.

## Paged Lists

Every list pages with a numbered pager and a `?page` URL param. There is no Load more button and no `useInfiniteQuery`. Backend rules are in [backend-ops.md](backend-ops.md)'s Pagination section.

### Composing a List

- **A list composes three pieces: `hooks/usePageParam.ts`, `hooks/usePagedQuery.ts` and `components/Pager/`.** Change paging behaviour there, never per route.
- **`usePageParam` owns `?page` and `setListParams`.** It reads and normalizes `?page` (page 1 omits it, a malformed value replaces to page 1). `setListParams` is the one writer for filter, sort, search and tab params: it drops `page` and default-valued params in a single push.
- **`setListParams` skips a write where only `page` would change**, such as re-picking the active tab, sort or preset. It returns false then.
- **`usePagedQuery` owns the fetch.** Give it `queryKey`, `pageSize`, `fetchPage` and a `select` that maps the response to `{ items, total, offset }`. It keeps the previous page while the next loads, clamps a past-end page, syncs a server-placed offset and calls `onPageSettled`.
- **`select` may also return `slotRows` (0 or 1) for a list whose page 1 carries a row beside the counted items.** `lastPage` becomes `ceil((total + slotRows) / pageSize)`, and the hook returns `firstRowOffset`, where this page's counted rows begin (later pages start `slotRows` earlier).
- **`pagerProps.offset` and the announcement use `firstRowOffset`,** so the range label covers counted rows only. Explore uses it for the Sponsored slot.
- **`<Pager {...pagerProps} />` renders the links and the live-region announcement**, with `pagerProps` returned by `usePagedQuery`. The caller adds `locale`, `liveNoun` (`events` or `items`), a `className` for placement and, if needed, `dropOnPageChange`. Its strings come from shared/i18n.
- **The request carries `limit` and `offset` only.** `PAGE_PARAM` in `constants/api.ts` names them, and `?page` is never sent to the backend. Each list's page size is a constant in `frontend/src/constants/`.
- **Pass `enabled` to hold the fetch** until a prerequisite such as a claim id or tab is known.

### Behaviour

- **`usePagedQuery` caps the last page at the backend's `PAGINATION_MAX_OFFSET`** (shared/app-config.json). Past it the label reads "... of N+" over the reachable count, and a deeper link replaces to the deepest reachable page without fetching.
- **Only a pager-link push or a back/forward POP counts as a page change.** `usePagedQuery` reads `useNavigationType()`, and every `<Pager>` link pushes with router state `PAGER_NAV_STATE`. Any other push that lands on a different page, from a `setListParams` filter change to a nav link or preset chip, stays silent. Every `replace` (normalizing, clamping, server-placed offset) skips `onPageSettled` and the announcement.
- **A pending page change belongs to its history entry.** A filter push before its data lands stays silent, even on a later Back. When a counted change lands on an emptied page, the clamp's target settles instead, so focus never drops to `<body>`.
- **A clamp's target settles only on fresh data.** The clamp marks the list stale, and a cached copy older than the emptied response never settles or announces.
- **Consumer and organizer lists settle a page change with `hooks/usePageSettledFocus.ts`.** Pass its `onPageSettled` to `usePagedQuery`: it instant-scrolls to the results heading and focuses it with `preventScroll`. The heading composes `PageSettle.module.css`'s `.settleTarget`, and the results container sets `aria-busy={isPlaceholderData}`.
- **A list whose `h1` sits above its filters gets a visually hidden results `h2`.** Explore puts a focusable "Events" `h2` (`srOnly` plus `.settleTarget`) directly above the grid, so focus after a page change lands below the filters and the next Tab reaches the first new card.
- **Admin queues wrap `usePagedQuery` in `hooks/useAdminQueuePage.ts`.** See the Admin Console section below.

## Locale-Prefixed Routing

- **Every `ROUTE_DEFS` entry registers twice.** Once at its bare `ROUTES.*` path, which is Estonian, and once under a `/:locale` prefix through `localePrefixedPattern`. `/en/...` and `/ru/...` reach the same element.
- **The four public SEO routes are `noRedirect: true`:** Home, `Explore`, `EventDetail` and `Faq`. Their bare path always renders Estonian, whatever the stored preference, so crawlers and the prerender see stable content.
- **Every other route is wrapped in `BareLocaleGate`.** It redirects a bare visit to the prefixed URL only when the stored preference is explicitly non-Estonian. A first-time visitor stays on the bare path.
- **The gate reads `getStoredLocale()`, not `getLocale()`.** `getLocale()` falls back to English, which would send a first-time visitor to `/en`.
- **An unrecognized `:locale` segment, such as `/xx/...`, renders Estonian without redirecting.**
- **`usePathLocale()` reads the locale from the pathname,** so it also works outside `<Routes>`. The `Footer`, `useLocaleMutation` and the switcher-less pages (login, verify, unsubscribe, `NotFound`) use it, so a page and its footer always share a language.
- **Internal links go through `useLocalePath()`, and programmatic navigation through `useLocaleNavigate()`.** Both prefix the target against the current URL.
- **`useLocaleMutation` switches locale by navigating to the equivalent prefixed path.** It also persists to `localStorage` and `PATCH /users/me`. It takes the locale from the URL segment, else the stored preference, or Estonian for `publicRoute: true` callers.

## FAQ Page

- **`Faq/` doesn't reuse `LegalPage`.** It copies `LegalPage`'s `TopBar` wiring and per-locale loader, but renders its own layout: a section jump-nav, one closed `<details>` per question and a contact CTA.
- **Each locale is a lazy `FaqDoc` chunk in `frontend/src/content/faq/`, loaded through `FAQ_LOADERS`.** English is canonical. A locale whose chunk is missing or fails falls back to it.
- **Answers are always in the DOM,** inside closed `<details>`, so the prerender captures them.
- **`structure.test.ts` pins Estonian and Russian to English's structure,** down to inline runs and list items, so a link dropped from one translation fails CI.
- **`configValues.test.ts` fails when a quoted config value changes without matching copy.** It covers link expiry, session length, persona cap and claim expiry, in every locale.
- **`FaqInline` adds a `{ text, to }` internal-route form, rendered as a router `Link` through `localePath()`.** `LegalInline`'s `href` stays for `mailto:` and `https:` only, because `safeUrl()` rejects a relative path.

### Deep Links

- **`createRoot` replaces the prerendered DOM, so the browser's hash jump fires before the answers exist.** An effect keyed on the loaded doc and `useLocation().hash` opens the matching `<details>` imperatively, then calls `scrollIntoView`. A hash that matches no section or item id is ignored.
- **React never renders `open`,** so the summary still toggles the item.
- **The scroll is `smooth`, or `auto` under reduced motion.** `scroll-margin-top` keeps the target clear of the sticky `TopBar`.
- **In-app `#` clicks are native jumps that land before the effect runs.** So `Faq.module.css` sets `scroll-behavior: smooth` on `html:has(.page)` while the page is mounted. `index.css`'s reduced-motion block forces it back to `auto`.

## API Client

- **`frontend/src/api/client.ts` exports `api` for the consumer track, plus `organizerApi` and `adminApi`.** The wrappers pass `{ organizer: true }` or `{ admin: true }` on every call, so callers never have to remember the flag. `adminStream()` reads the NDJSON job triggers.
- **Every request sends `credentials: 'include'`.** The session is an httpOnly cookie the JavaScript never sees, so there's no token to attach. See [security.md](security.md)'s Sessions section.
- **A 401 means "session expired" everywhere except `POST /admin/auth/login`.** There it means wrong credentials and must reach the login form as an `ApiError`, which `NO_SESSION_REDIRECT_ON_401` arranges.
- **`handleSessionExpiry401()` clears the matching track's signed-in hint and redirects to that track's login page.**
- **`FormData` bodies, such as the image upload, skip JSON stringification and the explicit `Content-Type`.** The browser sets the multipart boundary itself.
- **Server state goes through React Query** (`@tanstack/react-query`).

## Auth Hints

- **Each track has its own signed-in hint store:** `frontend/src/lib/auth.ts`, `organizerAuth.ts` and `adminAuth.ts`. They never share a storage key, matching the separate backend salts. The locale preference lives only in `auth.ts`.
- **The hint is a `'1'` marker that answers "should the UI render as signed in".** The backend decides authorization on every call, and a stale hint costs one 401 and a redirect.
- **Components read auth through `useAuth()`, `useOrganizerAuth()` or `useAdminAuth()`.** Those hooks subscribe to the store. Calling `isAuthenticated()` directly in render misses sign-in and sign-out changes.

## Tests

- **Tests sit beside their subject as `Name.test.tsx` or `Name.test.ts`.** Shared helpers live in `frontend/src/test/`. The stack is Vitest, Testing Library and jsdom.
- **`frontend/functions/` stays free of test files.** Cloudflare's file-based routing would claim a `.test.ts` there as a route. Pages Functions tests live in `frontend/tests/functions/`, mirroring that tree.
- **`npm run lint` covers `src`, `scripts`, `functions` and `tests`.**

## i18n

`shared/` is the single source of truth for every translated string and cross-stack value.

| File | Holds |
|---|---|
| `shared/i18n/{en,et,ru}.json` | `"ui"` frontend strings and `"email"` backend email strings |
| `shared/personas.json` | persona names and vibes per locale |
| `shared/app-config.json` | cross-stack scalars and taxonomies |
| `shared/calendar.json` | localized day and month names |

1. Edit the JSON in `shared/`.
2. Run `python scripts/generate_shared.py`.
3. Commit the JSON and the regenerated `_generated/` files together.

- **`_generated/` belongs to the script.** `backend/tests/test_generated_sync.py` runs the generator into a temp dir and fails on any byte of drift.
- **The frontend reads strings through `frontend/src/i18n.ts`** (`t`, `ti`, `tn`, `personaName`, `personaVibe`) over `_generated/i18nData.ts`. `constants.ts` takes `LOCALES`, `PERSONAS`, TTLs and weight thresholds from `_generated/sharedConstants.ts`.
- **A count-dependent string uses `tn()` and one key per plural category**, `{key}_one`/`_other`, plus `_few`/`_many` in `ru.json`. `Intl.PluralRules` picks the category, so each locale needs every category its rule returns.
- **The backend reads strings through `backend/app/i18n.py`** (`t`, `ti`, `day_name`, `month_name`) over `_generated/i18n_data.py`. `app/constants.py` takes cross-stack scalars and frozensets from `_generated/shared_constants.py`.
- **Legal and FAQ copy isn't in `shared/`.** Each is a per-locale TypeScript module under `frontend/src/content/legal/` or `content/faq/`.

## Brand Assets

- **`frontend/scripts/generate-icons.ts` is hand-run, not part of `npm run build`:** `npx tsx scripts/generate-icons.ts`. It owns `public/favicon.svg` and rasterizes the favicons, app icons, email mark and `og-fallback.png` through Playwright.
- **Commit the regenerated binaries with the script change.** The geometry rules are in [design-system.md](design-system.md)'s The Dial section.
- **The email mark is embedded as an inline CID attachment, not linked.** Apple Mail's privacy proxy failed to fetch it from the Pages host. The script writes it to `backend/app/email/assets/` as well as `public/`, since Render deploys `backend/` alone. `backend/app/email/brand.py::brand_mark_html()` renders the `cid:` `<img>` into every `*_HEADER` template, and `brand_mark_attachments()` adds the payload in `send_resend_email()` and the digest send.
- **`public/email-mark.png` (`EMAIL_BRAND_MARK_PATH`) stays only for already-sent mail,** which links it by URL.

## Email

`backend/app/email/` renders every email. Palette and dark mode are in [design-system.md](design-system.md)'s Email Theming section.

- **Each email type splits three ways:** presentation in `styles.py`, markup in `templates.py`, and assembly plus delivery in its own module. A new email type follows the split.
- **Markup is plain `str.format()` constants, with no templating engine.** Jinja2 would add a dependency for what string constants already do. A future rendering feature, such as a report export, uses the same split.
- **`styles.py::get_email_styles()` returns the one `EmailStyles` bundle.** Theme-neutral geometry stays as module-level `S_*` constants.
- **`templates.py` holds the shared `EMAIL_DOCUMENT` shell,** with header, content and footer slots. A new email type adds its own header, body and footer templates and reuses the shell.

### Email Links

- **Every user-facing link in an email carries the recipient's locale prefix.** Build it with `app/email/links.py::localized_path()` or `frontend_url()`, the backend twin of `localizedPath()`. A bare `f"{settings.FRONTEND_URL}..."` link would land on Estonian, because the switcher-less pages read the language from the URL alone.
- **Two links stay unprefixed:** the admin-only report notification and the digest's `List-Unsubscribe` header, which points at the backend.

### Digest

- **`digest.py` formats, assembles and sends the digest,** filling `EMAIL_DOCUMENT` with `DIGEST_HEADER` and `DIGEST_FOOTER`. Subjects, labels and day and month names come from `app/i18n.py`.
- **Each event block shows its escaped `image_url`, or a plain color band when there's none.** The header carries an "open feed" button (`feed_url`).
- **The digest is HTML only, with no plain-text part.**
- **It sends from a scheduled batch job, so it goes through the retrying `http_post()`.**

### Magic Link

- **`magic_link.py` builds both an HTML and a plain-text part** (`build_magic_link_html`, `build_magic_link_text`). Unlike the digest, it's a transactional send where deliverability matters.
- **`app/auth/email.py::send_magic_link` sends it through the single-attempt `send_resend_email()`.** A retrying backoff would stall the user's request. `docs/conventions.md` lists every bypass of `http_post()` and its reason.

### Contact Mail

- **`contact.py::send_contact_message` delivers a contact-form message to `settings.CONTACT_TO_ADDRESS`,** with `reply_to` set to the sender.
- **It's internal mail, so it skips `EMAIL_DOCUMENT`.** It fills the plain `CONTACT_HTML_BODY` and `CONTACT_TEXT_BODY` constants, escaped in `contact.py`.
- **It logs instead of sending when `RESEND_API_KEY` is unset.**
- **`app/routers/contact.py::submit_contact` swallows send errors,** so no email failure reaches the caller. The route is `POST /contact`, behind a honeypot and `RATE_LIMIT_CONTACT`.
