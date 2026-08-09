#!/usr/bin/env bash
# Mirrors the host's Claude Code config into the container. One-way
# (host -> container) and non-fatal: a missing mount or no network must never
# fail container start. Idempotent -- runs on create and on every start.
set -uo pipefail

HOST_CLAUDE="/mnt/host-claude"
HOST_ANVIL="/mnt/host-anvil"
HOST_CCSL="/mnt/host-ccstatusline"
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

if [ ! -d "$HOST_CLAUDE" ]; then
  echo "    no host ~/.claude mount at $HOST_CLAUDE -- skipping"
  exit 0
fi

# 1. Flat config files. settings.json is copied verbatim, rtk hook included --
#    the Dockerfile installs rtk so the hook resolves here.
for f in settings.json CLAUDE.md RTK.md; do
  [ -f "$HOST_CLAUDE/$f" ] && install -m 644 "$HOST_CLAUDE/$f" "$DEST/$f"
done

# 1b. Container-only plugin declarations. The copy above is verbatim, so anything
# enabled only in the container is wiped on every start -- and step 4 re-derives
# its install list from this same file. Merging the repo's overlay back on top
# keeps these plugins working without putting them in the host's ~/.claude.
OVERLAY="$(dirname "${BASH_SOURCE[0]}")/claude-plugins.json"
if [ -f "$OVERLAY" ]; then
  python3 - "$DEST/settings.json" "$OVERLAY" <<'PY' \
    || echo "    WARN: could not merge claude-plugins.json"
import json, pathlib, sys
dst, ov = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
try:
    s = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
    o = json.loads(ov.read_text(encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"malformed json: {e}", file=sys.stderr)
    sys.exit(1)
for key in ("extraKnownMarketplaces", "enabledPlugins"):
    if o.get(key):
        s.setdefault(key, {}).update(o[key])
dst.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
PY
fi

# 2. Personal slash commands. anvil.md / anvil-setup.md come across with
#    C:/Users/... paths baked in; step 5 regenerates those two in place.
if [ -d "$HOST_CLAUDE/commands" ]; then
  mkdir -p "$DEST/commands"
  cp -f "$HOST_CLAUDE"/commands/*.md "$DEST/commands/" 2>/dev/null || true
fi

# 3. Status line layout. ~/.cache/ccstatusline is deliberately NOT copied --
#    it is machine-local token accounting and a git cache.
if [ -f "$HOST_CCSL/settings.json" ]; then
  mkdir -p "$HOME/.config/ccstatusline"
  install -m 644 "$HOST_CCSL/settings.json" "$HOME/.config/ccstatusline/settings.json"
fi

# 4. Plugins. installed_plugins.json / known_marketplaces.json cannot be copied:
#    every installPath in them is a C:\ Windows path. Re-derive the declarations
#    from settings.json and let the CLI install them natively into the volume.
#    Scoped to this step alone (not a script-wide exit) so a missing/broken
#    claude CLI does not also skip step 5's unrelated anvil config seeding.
if command -v claude >/dev/null; then
  installed="$(claude plugin list 2>/dev/null || true)"

  while read -r kind arg; do
    case "$kind" in
      marketplace)
        claude plugin marketplace add "$arg" >/dev/null 2>&1 || true ;;
      plugin)
        case "$installed" in *"$arg"*) continue ;; esac
        echo "    installing $arg"
        claude plugin install "$arg" --scope user >/dev/null 2>&1 \
          || echo "    WARN: could not install $arg" ;;
    esac
  done < <(python3 - "$DEST/settings.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
try:
    s = json.loads(p.read_text(encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"malformed {p}: {e}", file=sys.stderr)
    sys.exit(0)
# The official marketplace is auto-added only on a first *interactive* launch.
print("marketplace anthropics/claude-plugins-official")
for m in (s.get("extraKnownMarketplaces") or {}).values():
    src = m.get("source") or {}
    if src.get("source") == "github" and src.get("repo"):
        print(f"marketplace {src['repo']}")
for name, enabled in (s.get("enabledPlugins") or {}).items():
    if enabled:
        print(f"plugin {name}")
PY
  )
fi

# 5. anvil. Seed config.json once from the host, minus the secrets: the host
#    stores api_key as a "dpapi:<base64>" blob that Windows DPAPI can only
#    decrypt on that user+machine. Reviewer enable flags, models, endpoints,
#    roster and caveman level all survive. Supply the keys via
#    .devcontainer/anvil.env (ANVIL_GEMINI_API_KEY / ANVIL_OPENAI_API_KEY),
#    which anvil resolves ahead of config.json, or run /anvil-setup once.
mkdir -p "$HOME/.claude-anvil"
if [ ! -f "$HOME/.claude-anvil/config.json" ] && [ -f "$HOST_ANVIL/config.json" ]; then
  # Default-deny: blank every non-empty api_key regardless of its format.
  # A host-side value can never be a usable secret in the container (DPAPI
  # blobs decrypt only on the host machine+user; anything else is still a
  # cross-machine secret we have no business copying) -- so anything present
  # gets stripped rather than only the two known placeholder shapes.
  if python3 - "$HOST_ANVIL/config.json" "$HOME/.claude-anvil/config.json" <<'PY'
import json, pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
cfg = json.loads(src.read_text(encoding="utf-8"))
for r in (cfg.get("reviewers") or {}).values():
    if r.get("api_key"):
        r["api_key"] = ""
dst.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
  then
    chmod 600 "$HOME/.claude-anvil/config.json"
    echo "    seeded ~/.claude-anvil/config.json (API keys stripped -- see anvil.env)"
  else
    echo "    WARN: could not seed ~/.claude-anvil/config.json from host"
  fi
fi

# Point ~/.claude-anvil/plugin-root at the container's plugin cache and rewrite
# the bare anvil commands copied in step 2, which still hold C:/Users/... paths.
# `sort -V | tail -1` alone would pick the lexicographically last cache dir even
# if it doesn't actually contain the scripts -- require the marker file too.
ANVIL_ROOT=""
while IFS= read -r dir; do
  [ -f "${dir}scripts/anvil-config.py" ] && ANVIL_ROOT="$dir"
done < <(ls -d "$DEST"/plugins/cache/*/claude-anvil/*/ 2>/dev/null | sort -V)
if [ -n "${ANVIL_ROOT:-}" ]; then
  python3 "${ANVIL_ROOT}scripts/anvil-config.py" create-shortcuts "${ANVIL_ROOT%/}" \
    >/dev/null 2>&1 || echo "    WARN: anvil create-shortcuts failed"
fi

echo "    claude config synced from host"
