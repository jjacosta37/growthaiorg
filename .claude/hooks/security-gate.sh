#!/usr/bin/env bash
# Security gate for Claude Code sessions (see CLAUDE.md, "Security").
#
# As a PreToolUse hook: blocks `git push`, `gh pr create` and GitHub MCP create-PR calls
# until /security-scan has passed for the current HEAD. Exit 2 blocks the call and hands
# stderr back to Claude. Pushes that change only docs are let through.
#
# As a command: `security-gate.sh --mark` records that HEAD passed the scan. The marker
# lives inside .git/, so it is never committed and doesn't survive a fresh clone.
#
# The gate only runs inside Claude Code; a human pushing from a terminal is unaffected.

set -u

marker="$(git rev-parse --git-path luka-security-scan 2>/dev/null)" || exit 0

if [ "${1:-}" = "--mark" ]; then
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "security-gate: commit your changes first; the mark applies to HEAD." >&2
    exit 1
  fi
  git rev-parse HEAD >"$marker"
  echo "security-gate: marked $(git rev-parse --short HEAD) as scanned."
  exit 0
fi

# Is this tool call a push or a PR? The hook payload is JSON on stdin.
gated="$(python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
tool = data.get("tool_name", "")
cmd = (data.get("tool_input") or {}).get("command") or ""
# `push` as the git subcommand, after any global options (`git -C dir push`), so a
# commit message that mentions "push" is not caught.
push = re.search(r"\bgit\s+(?:(?:-C|-c)\s+\S+\s+|--?[\w-]+(?:=\S+)?\s+)*push\b", cmd)
pr = re.search(r"\bgh\s+pr\s+create\b", cmd)
mcp_pr = re.search(r"create_pull_request", tool)
print("yes" if push or pr or mcp_pr else "")
' 2>/dev/null)"

[ "$gated" = "yes" ] || exit 0

# What would this push publish? Compare HEAD to where it branched from main.
base="$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main 2>/dev/null || true)"
if [ -n "$base" ]; then
  changed="$(git diff --name-only "$base" HEAD)"
  [ -z "$changed" ] && exit 0
  # Docs-only: files under docs/ or Markdown at the repo root. Prompts (backend/prompts/*.md)
  # and the .claude/ config are not docs; they change behaviour.
  code="$(printf '%s\n' "$changed" | grep -Ev '^docs/|^[^/]+\.md$' || true)"
  [ -z "$code" ] && exit 0
fi

head="$(git rev-parse HEAD)"
if [ -f "$marker" ] && [ "$(cat "$marker")" = "$head" ]; then
  exit 0
fi

cat >&2 <<EOF
Blocked by the security gate: commit $(git rev-parse --short HEAD) has not passed /security-scan.

Run /security-scan (the security-scan skill), fix every CRITICAL and HIGH finding, commit,
and let the skill mark HEAD. Then retry this command, and put the skill's "## Security scan"
section in the PR description. Any new commit needs a fresh scan.

Do not try to get around this gate. If a CRITICAL or HIGH finding can't be fixed in this
PR, stop and ask the user.
EOF
exit 2
