#!/bin/zsh
# Re-applyable GitHub repo configuration for RandyBeaman1985/vinylvision.
# Tier S / solo / public: squash merges, tidy branches, security scanning on.
set -euo pipefail
REPO="RandyBeaman1985/vinylvision"

# merge policy: squash only, auto-delete merged branches, allow auto-merge
gh api -X PATCH "repos/$REPO" \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true -F allow_auto_merge=true \
  -F has_wiki=false -F has_projects=false >/dev/null

# topics
gh api -X PUT "repos/$REPO/topics" \
  -f "names[]=vinyl" -f "names[]=music-video" -f "names[]=shazam" \
  -f "names[]=audio-fingerprinting" -f "names[]=macos" -f "names[]=yt-dlp" \
  -f "names[]=generative-ai" >/dev/null

# security: dependabot alerts + auto security fixes, secret scanning + push protection
gh api -X PUT "repos/$REPO/vulnerability-alerts" >/dev/null
gh api -X PUT "repos/$REPO/automated-security-fixes" >/dev/null
gh api -X PATCH "repos/$REPO" --input - >/dev/null <<'JSON'
{"security_and_analysis": {
  "secret_scanning": {"status": "enabled"},
  "secret_scanning_push_protection": {"status": "enabled"}}}
JSON

echo "repo settings applied to $REPO"
# NOTE (solo mode): no branch protection — direct pushes to main are the
# workflow. When a second contributor shows up, add:
#   gh api -X PUT repos/$REPO/branches/main/protection ...
