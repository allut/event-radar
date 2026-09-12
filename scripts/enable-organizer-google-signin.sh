#!/usr/bin/env bash
#
# A wizard — walks a human, step by step, through a manual procedure that's
# tedious to do by hand and tedious to re-explain to an AI every time. It
# opens each URL, says exactly what to click and copy, captures the values,
# writes them where they belong (.env, GitHub secrets), confirms at every
# stage, and shows how many stages are left.
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library — delightful, consistent UX. Identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later — it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

say()  { printf '  %s\n' "$1"; }
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser — visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser — visit it manually: $url"
}

pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key ($ENV_FILE)")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name — gh not ready; set it later"
}

set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name — gh not ready; set it later"
}

finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES — organizer-track Google sign-in (docs/adr/0002-google-sign-in-oauth-pkce.md)
#
# The code path is already fully implemented and flag-gated off
# (GOOGLE_SIGNIN_ORGANIZER_ENABLED / VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED,
# both default false — app/config.py). backend/.env already has a
# GOOGLE_OAUTH_CLIENT_ID/SECRET pair from earlier testing, so this wizard
# reuses that existing Google Cloud OAuth client rather than creating a new
# one: it just needs the organizer callback path added as a registered
# redirect URI, then the two flags flipped for dev and prod.
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=5

banner "Enable Google sign-in — organizer portal"

# ── Stage 1: add the organizer redirect URI to the existing OAuth client ──
stage "Google Cloud Console — register the organizer redirect URI"
say "Your existing OAuth client (already in backend/.env as GOOGLE_OAUTH_CLIENT_ID)"
say "needs the organizer-track callback URL added to its allow-list. Per ADR 0002"
say "the redirect URI is: \${FRONTEND_URL}/api/organizer/auth/google/callback"
say "(Google's own redirect, not GIS JS — this is a top-level navigation, so no"
say " CSP/CORS change is needed either.)"
open_url "https://console.cloud.google.com/apis/credentials"
step "Find the OAuth 2.0 Client ID whose Client ID matches the value already in"
step "  backend/.env (GOOGLE_OAUTH_CLIENT_ID) and click it to edit."
step "Under 'Authorized redirect URIs', click 'Add URI' and add BOTH of these"
step "  (dev first, prod second — ask for your prod frontend origin below):"
say  "    http://localhost:5173/api/organizer/auth/google/callback"
ask FRONTEND_URL_PROD "Your production frontend origin (e.g. https://whatsonradar.com), no trailing slash:"
say  "    ${FRONTEND_URL_PROD}/api/organizer/auth/google/callback"
step "Click 'Save' at the bottom of the client's edit page."
note "OAuth consent screen scopes: this client already requests 'openid email'"
note "for the consumer track — organizer sign-in reuses the identical scope, so"
note "the consent screen itself needs no change."
confirm "Saved both redirect URIs on the existing client?" || warn "come back and finish this before testing sign-in — the callback will fail closed on a redirect_uri_mismatch otherwise"

# ── Stage 2: local backend env ─────────────────────────────────────────────
stage "Local backend — flip the flag"
say "backend/.env already has GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET."
say "This stage only turns the organizer flag on for local dev."
ENV_FILE="backend/.env"
write_env "GOOGLE_SIGNIN_ORGANIZER_ENABLED" "true"
note "Leaving GOOGLE_SIGNIN_CONSUMER_ENABLED untouched — this wizard is organizer-only."

# ── Stage 3: local frontend env ────────────────────────────────────────────
stage "Local frontend — flip the flag"
say "The frontend flag only avoids rendering a dead button; the backend flag"
say "above is the authoritative gate (endpoint 404s when it's off)."
ENV_FILE="frontend/.env.local"
write_env "VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED" "true"

# ── Stage 4: restart + smoke test locally ──────────────────────────────────
stage "Restart dev servers and test the flow"
say "Vite only reads .env.local at startup, and the backend needs the new"
say "setting too — a plain 'npm run dev' left over from before won't pick"
say "either of these up."
step "Run: bash .devcontainer/dev-server.sh restart"
pause "Run that now, then press Enter to continue"
open_url "http://localhost:5173/organizer/login"
step "Click 'Sign in with Google', pick a Google account, and confirm you land"
step "  back on the organizer dashboard (or get a confirmation-link email if"
step "  the account's address isn't @gmail.com/@googlemail.com or Workspace)."
confirm "Did the local organizer Google sign-in flow work end-to-end?" || warn "check backend logs for LOG_EVENT_GOOGLE_SIGNIN_DEGRADED / redirect_uri_mismatch before going further"

# ── Stage 5: production (Render + Vercel dashboards) ───────────────────────
stage "Production — Render (backend) + Vercel (frontend)"
say "These vars are dashboard-managed (render.yaml marks them sync: false), not"
say "GitHub Actions secrets, so this wizard can't set them via gh — it's a"
say "manual flip in each provider's dashboard."
open_url "https://dashboard.render.com"
step "Open the event-radar-api service → Environment."
step "Confirm GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are already set"
step "  (same values as backend/.env) — set them now if this is a fresh service."
step "Set GOOGLE_SIGNIN_ORGANIZER_ENABLED = true. Save, which triggers a redeploy."
confirm "Set GOOGLE_SIGNIN_ORGANIZER_ENABLED=true on Render?" || SKIPPED+=("Render: GOOGLE_SIGNIN_ORGANIZER_ENABLED=true")
open_url "https://vercel.com/dashboard"
step "Open the frontend project → Settings → Environment Variables."
step "Add VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED = true for the Production environment."
step "Redeploy (Vercel env var changes don't apply retroactively to old builds)."
confirm "Set VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED=true on Vercel and redeployed?" || SKIPPED+=("Vercel: VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED=true + redeploy")
note "Verify in production the same way as stage 4, against ${FRONTEND_URL_PROD}/organizer/login."

finish
