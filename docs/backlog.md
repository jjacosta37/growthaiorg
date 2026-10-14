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

### Internal links in blog posts
- **Added:** 2026-10-14 · from PRD 0002 (blog posts as GitHub pull requests)
- **Problem:** Content Agent posts don't link to the company's own pages. Internal links help search engines understand and rank a site, and they keep readers on it. Luka already has the site's crawled pages, but the post prompt doesn't use them for links.
- **Why it was left:** it changes how posts are written, not how they reach the site, so it's a separate Content Agent improvement from PRD 0002.
- **Options:**
  1. **Give the post prompt a short list of the site's crawled pages** (URL, title, one line on what each covers) and ask for 2–4 relevant internal links. Only listed URLs are allowed, which is checked in code after generation. This needs a prompt version bump, and the links become a new model-output effect to add to `docs/security-patterns.md` §7.
  2. **Also link to earlier Luka posts** once they're marked Posted with a URL.
- **Related:** `backend/prompts/content/post/`, `docs/security-patterns.md` §7.

### Support more blog architectures for GitHub PRs
- **Added:** 2026-10-14 · from PRD 0002 (blog posts as GitHub pull requests)
- **Problem:** PRD 0002 writes one Markdown file per post with renamable frontmatter and constant fields. Blogs are built in many other ways, and those break or need a one-time change on the site first:
  - posts listed in one shared code or data file (e.g. a TypeScript or JSON array)
  - HTML bodies instead of Markdown
  - MDX with components
  - one folder per post with an `index.md`
  - computed fields such as reading time
  - required cover images
  - a CMS rather than a repository
  - a date in the path or file name
- **Why it was left:** a narrow first version keeps the PR predictable and makes sure Luka never edits a site's source code. A live test against a real site showed it needed the site to switch to one file per post first.
- **Options:**
  1. **File layout options:** path patterns (`{folder}/{slug}.md`, `{folder}/{slug}/index.md`, `{date}-{slug}.md`) and the file extension (`.md`/`.mdx`).
  2. **Body format option:** Markdown or HTML.
  3. **Computed fields** such as reading time and word count, plus an optional cover image once posts have images.
  4. **Learn the format from an existing post** in the chosen folder, by copying its frontmatter keys and layout, and show the result in the preview.
  5. **Shared-file sites:** append an entry to a JSON or YAML data file (data, not code). Editing source files (TS/JS) stays out because of escaping and merge conflicts.
  6. **CMS targets** (headless CMS APIs) behind the same publish interface, as a separate PRD.
- **Related:** `docs/prds/0002-github-blog-prs.md` (Out of scope list).
