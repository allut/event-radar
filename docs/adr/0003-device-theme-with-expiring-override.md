# Theme follows the device, and a manual choice expires

Status: accepted

The resolved theme was a durable, account-level *preference*: a tri-state
`system`/`light`/`dark` value in `localStorage`, mirrored into
`users.theme_preference` / `organizers.theme_preference` and synced across a
signed-in user's devices, with emails rendered from the stored column. We
collapsed that to a device-local model: the *device theme* decides, a viewer
may override it to light or dark on one browser, and that **theme override
expires the next time that browser's device theme changes** — on a live
`matchMedia` flip or on a load-time mismatch against the device theme the
override was chosen under. The account columns are dropped, the picker loses
its "System" entry (device-following is now the default state, not a choice),
and every email renders from one bundle that carries its own
`prefers-color-scheme` override so the client decides.

The trade this makes: cross-device persistence and a durable user choice, in
exchange for deleting a whole synced-preference pathway (two columns, two
PATCH fields, a post-verify sync policy on both auth tracks, and a three-way
email style branch) for a setting whose correct value is already sitting on
the device.

## Considered options

- **Keep the override permanent** (today's behaviour minus "System") —
  rejected, though it is arguably the better product. It makes "the site
  follows your device" false for anyone who has ever touched the toggle, which
  is the property we were asked to guarantee.
- **Store the override as an inversion** ("always the opposite of my device")
  — rejected. It survives device flips, but nobody wants "opposite"; they want
  light or dark, and the two only coincide until the device flips.
- **Expire only on a live `matchMedia` flip** — rejected. An override set at
  noon would still force light on a dark phone opened at midnight.
- **Keep the account columns, stop reading them** — rejected. A column nobody
  reads is a column someone re-wires; the deletion is the point.
- **Render emails from a stored per-recipient theme** — rejected, because a
  stored theme cannot track a device that changes after the mail is sent,
  which is the behaviour asked for.

## Consequences

- **A manual choice has a half-life of hours on most phones.** Scheduled auto
  dark mode flips at sunset and sunrise, and each flip expires the override.
  Deliberate, and the single most likely source of a "the site keeps changing
  my theme" report.
- **There is no UI affordance to return to device-following.** With "System"
  gone, a viewer who overrides waits for the next device flip (or clears site
  data). Accepted as the cost of a two-option control.
- **The override is per browser profile, not per device.** Chrome and Safari
  on the same phone hold separate overrides; private windows and cleared site
  data start over at the device theme. "Works on all platforms" means the
  device theme is always honoured, not that a choice travels.
- **Email theming is best-effort and client-dependent.** Apple Mail and
  Outlook.com honour `prefers-color-scheme`; Gmail (web, Android, iOS) does
  not, and applies its own inversion heuristics to the light base instead. The
  bundle keeps a light base precisely so a non-supporting or
  `<style>`-stripping client lands on a designed render rather than an
  inverted one.
- **The columns are dropped one release after the code that reads them.**
  `render.yaml`'s `preDeployCommand: alembic upgrade head` runs while the old
  process still serves traffic, so a same-deploy drop would throw
  `UndefinedColumn` on every `select(User)` for the deploy window.
- **The pre-paint script gains the expiry check** and stays hash-pinned in
  `frontend/public/_headers`; it only reads, while `lib/theme.ts` performs the
  cleanup write at boot, keeping the hashed body small.
- **The word "preference" leaves the theme vocabulary** — `CONTEXT.md` now
  defines *device theme*, *resolved theme* and *theme override*, and
  `shared/app-config.json`'s key is renamed `theme_preferences` → `themes`,
  with no backend emission at all.
