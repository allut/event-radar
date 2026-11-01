# Runtime config stores overrides only, over repo defaults

Status: accepted

Runtime config is one keyed table of overrides (`key`, JSON `value`,
`updated_at`). A registry in `app/runtime_config/`, one module per area,
declares each runtime value's key, type, validator and repo default together,
so every repo default lives in that one package. A row exists only once an
admin has changed a value; no row means the repo default applies, and resetting
deletes the row. Decided in
[how values are stored, validated and fall back to repo defaults](https://github.com/allut/event-radar/issues/680).

## Considered options

- **A full copy of every value, seeded from the repo.** Rejected. A developer's
  later change to a default would never reach production, because the seeded
  copy always wins.
- **One typed table per area** (Operator details, prompts, selectors, weights).
  Rejected. Each new area would need a migration and its own read and write
  path, and the admin screen would have to know every table.

## Consequences

- **The registry is the schema.** Adding a runtime value means adding a
  registry entry, with no migration. Constants that are not runtime values
  (hosts, URLs, date formats, safety bounds, token caps) stay in their
  current homes.
- **An override can go stale.** Each override records a hash of the repo
  default it was written against. When the default changes, the override still
  applies, a warning is logged, and the admin console flags it for the admin
  to reconcile.
- **An override can turn invalid after a code change**, such as a prompt
  override lacking a placeholder the code now fills in. It is validated on
  save and again on read; on read failure the repo default applies (for a
  private runtime value, the placeholder) and an error is logged.
- **Reads come from a module-level cache of parsed values**, loaded at startup,
  reloaded after each write and on a short schedule. The scheduled reload
  covers the deploy overlap, when two instances briefly run. Long jobs read at
  the point of use, so a change applies from their next item.
