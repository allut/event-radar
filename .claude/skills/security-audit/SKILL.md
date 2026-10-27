---
name: security-audit
description: Audit code for OWASP Top 10 vulnerabilities, scoped to changes since the last security audit.
disable-model-invocation: true
---

The deliverable is a **report** in chat: findings ranked by severity, each with a recommended fix. Code changes wait for the user to pick findings from it.

## Steps

1. **Read the ledger, `docs/security-audit.md`, then `docs/security.md`.** Done when you hold the baseline commit, the guards, the accepted risks, the open findings and the controls the code claims.

2. **Fix the scope.** By default it is every non-test source file in `git diff --name-only <baseline>..HEAD`, plus the callers of the functions those files change. Add `render.yaml`, `frontend/public/_headers`, `frontend/functions/` and `.github/workflows/` when they changed. A full sweep happens only when the user asks for one. Done when you hold the file list and its line count.

3. **Run the mechanical checks** and keep their output for the report:
   - `bash backend/scripts/scratch-test.sh --no-db tests/test_route_guards.py tests/routers/test_price_fields.py tests/test_csrf_middleware.py tests/test_security_headers.py`
   - `pip-audit -r backend/requirements.txt` from `backend/`, and `npm audit` from `frontend/`
   - a secrets scan bounded to the scope: `git grep -nE '<key patterns>'` on the tree, and `git log -p --since=<baseline date> -G'<key patterns>'` for history

   Done when every check has a pass or a named failure.

4. **Split the scope into at most three slices by area,** and skip an empty slice:
   - auth and request path: `app/main.py`, `app/rate_limit.py`, `app/auth/`, `app/routers/`, `app/email/`, `frontend/functions/`
   - pipeline and integrations: `ingestion/`, `claims/`, `promotions/`, `integrations/`, `llm/`, `events/`, `publish.py`
   - frontend: `frontend/src/`, `frontend/public/`, `frontend/index.html`

   A scope under about 3k lines needs no agents; audit it yourself.

5. **Give each slice to a read-only agent.** The prompt carries the checklist below plus the ledger's Guards and Accepted sections. Each agent reads every file in its slice in full and returns two things:
   - per finding: location, OWASP category, the concrete attack, severity, and a fix naming an existing helper
   - a per-file coverage list

   Done when every file in scope appears in a coverage list.

6. **Verify every Medium-or-higher finding against the code yourself** before it reaches the report: trace the attacker's input to the sink. Drop what the ledger accepts or a guard enforces.

7. **Report** in tiers: Critical/High, then Medium, then Low and Info. Close with the mechanical-check results and the coverage count. Post a one-line progress note after each step, since a sweep runs long.

8. **Once the user has replied to the report, rewrite the ledger:**
   - Set the baseline to the audited `HEAD`.
   - Remove findings that are gone, and add the new ones.
   - Move anything the user accepts to Accepted by Design, with its reason.

   Then run `bash backend/scripts/scratch-test.sh --no-db tests/test_docs_style.py`. Done when the guard passes.

## Checklist

- **A01 access control:** a query by id without an owner predicate; a hidden row readable through a 200-versus-404 oracle; one auth track's dependency on another track's prefix.
- **A02 cryptography:** a secret in a signed-not-encrypted token payload; a token comparison without `compare_digest`; a cookie missing httpOnly, Secure or the right `SameSite`.
- **A03 injection:** `text()` or f-string SQL; an unescaped `LIKE`; HTML from a user, a scrape or an LLM reaching `dangerouslySetInnerHTML` or an email template without sanitising or `html.escape`.
- **A04 design:** a numeric field with no upper bound; a counter or quota an anonymous caller can drive; a business identity (company, email, domain) taken from the request unverified.
- **A05 configuration:** a response path that skips `SECURITY_HEADERS`; a secret that fails open outside development; a CSP widened without a reason.
- **A07 authentication:** a magic link or token that is reusable, unexpiring or consumed non-atomically; a login path outside the lockout.
- **A08 integrity:** a webhook handled before its signature check; a replay that changes state.
- **A09 logging:** raw email, token or query string in a log line; a security event with no `LOG_EVENT_*` field.
- **A10 SSRF:** a server-side fetch of a stored or user URL that skips `safe_fetchable_url()`, `http_get_stored_url()` or `host_guard_hook`; a user value built into an outbound URL path.
