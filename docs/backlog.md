# Backlog

Work we've decided to leave for later, so it isn't forgotten. Each item says what the problem is, why it was left, and the options already considered, so it can be picked up without redoing the analysis.

- **Add** an item when you defer something that should be solved at some point: a finding accepted for now, a follow-up from a PR, a limitation you chose to live with.
- **Remove** an item, in the same PR, when it's done. The PR and git history keep the record.
- **Security items** are tracked in `docs/security-patterns.md` §14 (the known-concerns register). An item here only adds the product context and links to it; the register stays the source of truth for severity.

## Items

### Topic research can repeat on a frequent Content Agent schedule
- **Added:** 2026-10-14 · from PR #14 (evidence-backed topics, `docs/prds/0001-evidence-backed-topics.md`)
- **Problem:** when a Content Agent run needs topics and there are no unused relevant Reddit posts, it searches Reddit and scores the posts (topic research), then looks up keyword data. If the configured subreddits never yield relevant posts and the agent's schedule is very frequent, every run repeats the Reddit search, its scoring and a keyword lookup. Each run is bounded (Reddit search ≤ 500 results / $1, keyword lookup ≤ 50 keywords / $0.50), but the repeats add up.
- **Why it was left:** accepted for now by the operator (2026-10-14). A per-run bound exists, and agent schedules are set by account holders.
- **Options:**
  1. **A minimum interval for agent schedules** (recommended). It fixes the root cause for every agent, and it's the fix for §14 Medium 4, which this item makes worse. AC-14 stays as agreed.
  2. **Limit topic research to once every N hours per project.** It narrows only this path, and it changes AC-14 of PRD 0001, so the PRD would log a change after agreement and the feature doc would be updated.
- **Related:** `docs/security-patterns.md` §11 (spend) and §14 Medium 4 (no minimum interval for agent cron).

### Check that a published blog post can be indexed
- **Added:** 2026-10-14 · from PRD 0002 (blog posts as GitHub pull requests, `docs/prds/0002-github-blog-prs.md`)
- **Problem:** once a post is merged and deployed, nothing tells the user if search engines can't index it. The page might 404, carry a `noindex` tag, sit under a folder that `robots.txt` blocks, or be missing from the sitemap. Nobody notices until the post gets no traffic.
- **Why it was left:** PRD 0002 deliberately adds only the post's own file to the PR. Editing `robots.txt` or the sitemap from a PR is fragile, because most site frameworks generate them at build time. A check after publishing catches the real failures without touching site files.
- **Options:**
  1. **Check when the user marks a draft Posted with its URL** (recommended). Luka fetches the page and checks that it returns 200, has no `noindex`, isn't disallowed by `robots.txt` and is listed in the sitemap (Luka already reads sitemaps during onboarding). Problems show on the draft. The check is an outbound fetch, so it follows the SSRF rules in `docs/security-patterns.md` §6.
  2. **Re-check periodically** until the post shows up in the sitemap. This catches deploys that land later, but costs a scheduled task per post.
- **Related:** `docs/prds/0002-github-blog-prs.md` (Out of scope: robots.txt and sitemap edits; no PR-state tracking).
