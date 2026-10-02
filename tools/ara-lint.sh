#!/usr/bin/env bash
# ara-lint.sh — pre-push lint for ARA cert tracks in elastic/instruqt-traqs-dev.
# Authoring tool; nothing in a sandbox runs it.
# Run from a traqs-dev checkout root (or set ARA_TRACKS_DIR); optional track slug argument.
# Exit code: 0 = clean, 1 = findings.
set -uo pipefail 2>/dev/null || set -u

TRACKS_DIR="${ARA_TRACKS_DIR:-$PWD/tracks}"
ERRORS=0
WARNINGS=0

slug="${1:-}"
if [[ -n "$slug" ]]; then
  TRACK_DIRS=("${TRACKS_DIR}/${slug}")
else
  TRACK_DIRS=("${TRACKS_DIR}"/cert-sk-ara-*)
fi

err()  { echo "  ERROR: $*"; ERRORS=$((ERRORS + 1)); }
warn() { echo "  WARN:  $*"; WARNINGS=$((WARNINGS + 1)); }

for track_dir in "${TRACK_DIRS[@]}"; do
  [[ -d "$track_dir" ]] || { echo "Not found: $track_dir"; exit 2; }
  track=$(basename "$track_dir")
  echo "── $track"

  # ── Model / vendor names outside env-default lines ────────────────────────
  VENDOR_PAT='gpt-4o|claude-sonnet-5|claude-3|gemini-2\.\d|sonnet-[0-9]|haiku-[0-9]|OpenAI|Anthropic\b|Google\b'
  EXEMPT_COMMENT='ARA_MODEL_FAST\|ARA_MODEL_STRONG\|openai.*pip\|pip.*openai\|openai.*package\|base_url\|EnvironmentError\|docstring\|__init__'
  # Vendor check: exclude private/ (root-only, not learner-facing)
  while IFS= read -r hit; do
    [[ "$hit" == *"/private/"* ]]             && continue  # private/ is exempt
    [[ "$hit" == *"#"*"ARA_MODEL"* ]]         && continue
    [[ "$hit" == *"pip install openai"* ]]    && continue
    [[ "$hit" == *"from openai import"* ]]    && continue  # package import
    [[ "$hit" == *"import openai"* ]]         && continue
    [[ "$hit" == *"OpenAI("* ]]               && continue  # client constructor
    [[ "$hit" == *"os.environ"*"ARA_MODEL"* ]] && continue  # env var read
    [[ "$hit" == *"base_url"* ]]              && continue
    [[ "$hit" == *"EnvironmentError"* ]]      && continue
    [[ "$hit" == *"e.g."* ]]                 && continue
    err "Vendor/model literal: $hit"
  done < <(grep -rn --include="*.sh" --include="*.py" --include="*.md" --include="*.json" \
    -E "$VENDOR_PAT" "$track_dir" 2>/dev/null || true)

  # ── Em-dashes in learner-facing prose ─────────────────────────────────────
  # Scope: assignment.md, track.yml title/teaser/description, slides.md
  for f in "$track_dir"/**/assignment.md "$track_dir"/track.yml; do
    [[ -f "$f" ]] || continue
    if python3 -c "import sys; sys.exit(0 if '—' in open('$f').read() else 1)" 2>/dev/null; then
      err "Em-dash in learner-facing file: $f"
    fi
  done

  # ── Brief challenge gate (pattern spec 3.6, option 1, 13 §10.7) ─────────────
  brief_dir=$(find "$track_dir" -maxdepth 1 -type d -name "01-brief*" 2>/dev/null | head -1)
  if [[ -n "$brief_dir" ]]; then
    amd="$brief_dir/assignment.md"
    # Brief MUST have the environment-gate check script
    if [[ ! -f "$brief_dir/check-elastic-serverless" ]]; then
      err "Brief missing check-elastic-serverless (environment gate): $brief_dir"
    fi
    # Brief MUST have the waiting solve script
    if [[ ! -f "$brief_dir/solve-elastic-serverless" ]]; then
      err "Brief missing solve-elastic-serverless (wait loop): $brief_dir"
    fi
    # Brief sidebar and closing line must say Check, not Next
    if [[ -f "$amd" ]] && grep -qi '\*\*Next\*\*' "$amd"; then
      err "Brief assignment.md says Next; spec 3.5 requires Check: $amd"
    fi
    # Brief must have custom_layout in assignment.md frontmatter
    if [[ -f "$amd" ]] && ! grep -q 'custom_layout' "$amd"; then
      err "Brief assignment.md missing custom_layout: $amd"
    fi
  fi

  # ── skipping_enabled on capstones ─────────────────────────────────────────
  # Note: instruqt track push rewrites track.yml on sync; check the challenge
  # assignment.md frontmatter instead, where the field survives a push.
  if [[ "$track" == *"-1-c-"* || "$track" == *"-2-c-"* || "$track" == *"-3-c-"* ]]; then
    if ! grep -rq 'skipping_enabled: false' "$track_dir"/**/assignment.md 2>/dev/null; then
      warn "Capstone may be missing skipping_enabled: false in a challenge assignment.md: $track_dir"
    fi
  fi

  # ── timelimit in every challenge ──────────────────────────────────────────
  for amd in "$track_dir"/**/assignment.md; do
    [[ -f "$amd" ]] || continue
    if ! grep -q '^timelimit:' "$amd"; then
      err "Missing timelimit in frontmatter: $amd"
    fi
  done

  # ── ARA_ASSETS_REF must be pinned when status is not dev ──────────────────
  status_tag=$(grep '- status/' "$track_dir/track.yml" 2>/dev/null | head -1 | tr -d ' ' | cut -d/ -f2)
  if [[ "$status_tag" != "dev" && "$status_tag" != "" ]]; then
    setup=$(find "$track_dir/01-"* -name setup-elastic-serverless 2>/dev/null | head -1)
    if [[ -n "$setup" ]] && grep -q 'ARA_ASSETS_REF="main"' "$setup"; then
      err "ARA_ASSETS_REF still points to main but status is $status_tag: $setup"
    fi
  fi

  # ── ara-embed.py drift check ──────────────────────────────────────────────
  setup=$(find "$track_dir/01-"* -name setup-elastic-serverless 2>/dev/null | head -1)
  if [[ -n "$setup" ]] && grep -q 'BEGIN GENERATED FROM private' "$setup"; then
    if ! python3 "$(dirname "${BASH_SOURCE[0]}")/ara-embed.py" "$track" --tracks-dir "$TRACKS_DIR" --check 2>/dev/null; then
      err "private/ and setup heredoc have drifted: run vestal_project tools/ara-embed.py $track"
    fi
  fi

  # ── pyflakes on private/checks/ (catches import-before-use, unused imports) ─
  # grading standard T7: `import os` after first use raised NameError in capstone
  if command -v pyflakes >/dev/null 2>&1 && [[ -d "$track_dir/private/checks" ]]; then
    if ! pyflakes "$track_dir/private/checks/" 2>/dev/null; then
      err "pyflakes errors in private/checks/ — fix before pushing: $track_dir/private/checks/"
    fi
  fi

  echo ""
done

echo "── Summary"
echo "   Errors:   $ERRORS"
echo "   Warnings: $WARNINGS"
[[ $ERRORS -eq 0 ]]
