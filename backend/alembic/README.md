# Alembic Migration Environment

This directory contains the Alembic migration environment for the Event Radar backend.

## Configuration

- **Script location**: `backend/alembic/` (set in `backend/alembic.ini`)
- **Database URL**: read from `app.config.settings.DATABASE_URL` inside `env.py` — the `sqlalchemy.url` key in `alembic.ini` is intentionally left blank.
- **Target database**: Neon Postgres (eu-central-1), async driver (`asyncpg`).
- **Metadata**: `app.db.Base.metadata`; all models are registered by the import of `app.models` in `env.py`, whose `__init__.py` imports every module in `app/models/`.

## Common Commands

Run all commands from the `backend/` directory.

```bash
# Apply all pending migrations
alembic upgrade head

# Apply the next N revisions
alembic upgrade +1

# Roll back the last revision
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade <revision_id>

# Show current revision
alembic current

# Show revision history
alembic history --verbose

# Auto-generate a new migration from model changes
alembic revision --autogenerate -m "short description"

# Create an empty migration script
alembic revision -m "short description"
```

## Creating a New Migration

1. Make your SQLAlchemy model changes in the domain's module under `app/models/`.
2. Auto-generate a candidate script:
   ```bash
   alembic revision --autogenerate -m "add_foo_column"
   ```
3. **Review the generated script carefully.** Autogenerate cannot detect every change (e.g. server-side defaults, `citext` columns, custom types, GIN/GiST indexes). Adjust as needed before committing.
4. Apply it:
   ```bash
   alembic upgrade head
   ```

## File Naming Convention

Migration scripts are named `NNNN_description.py` (zero-padded four-digit sequence number), e.g. `0001_init.py`. Keep descriptions short and lowercase with underscores.

## Offline vs Online Mode

`env.py` supports both Alembic run modes:

- **Online** (default): creates an async engine, connects to the real database, and runs migrations.
- **Offline** (`alembic upgrade head --sql`): emits raw SQL to stdout without connecting — useful for generating migration scripts to apply manually.

## Adding a New Model

Put the model in its domain's module under `app/models/`. For a new module, add it to the import in `app/models/__init__.py`, which `env.py` imports, so its tables are registered with `Base.metadata` before autogenerate runs; otherwise Alembic and the mapper registry never see it. A cross-module `Mapped[...]` gets its class from an `if TYPE_CHECKING:` import, because model modules never import each other at runtime.

## Notes

- All datetimes must be timezone-aware (`zoneinfo`, `Europe/Tallinn`). Use `sa.DateTime(timezone=True)` in every migration.
- The `citext` extension is created in `0001_init.py`. New migrations that need case-insensitive columns can rely on it already being present.
- `downgrade()` must be implemented for every migration to support rollback in production.
