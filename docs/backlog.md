# Backlog

Work we've decided to leave for later, so it isn't forgotten. Each item says what the problem is, why it was left, and the options already considered, so it can be picked up without redoing the analysis.

- **Add** an item when you defer something that should be solved at some point: a finding accepted for now, a follow-up from a PR, a limitation you chose to live with.
- **Remove** an item, in the same PR, when it's done. The PR and git history keep the record.
- **Security items** are tracked in `docs/security-patterns.md` §14 (the known-concerns register). An item here only adds the product context and links to it; the register stays the source of truth for severity.

## Items

### The app isn't usable at phone width
- **Added:** 2026-10-16 · from PR for friendly agent schedules (`docs/prds/0003-friendly-agent-schedules.md`, AC-16)
- **Problem:** the three-pane shell has `min-width: 1024px` (`frontend/src/styles/shell.css`, "Desktop-first"), so on a phone every page scrolls sideways. Components such as the schedule editor fit a phone-width column, but the shell around them doesn't.
- **Why it was left:** out of scope for the schedule builder; it touches every page. AC-16 of PRD 0003 was narrowed to the editor itself (approved by the user, 2026-10-16).
- **Options:**
  1. **A responsive shell:** below a breakpoint, show one pane at a time (sidebar as a drawer, list, then detail), as most mail clients do.
  2. **Keep desktop-only** and say so on the login page for small screens.
- **Related:** `docs/design-brief.md` (shell and screens).

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

### Open blog PRs without write access to the customer's repository
- **Added:** 2026-10-15 · from PRD 0002 (blog posts as GitHub pull requests)
- **Problem:** to open a PR, Luka's GitHub App needs Contents: write. GitHub can't narrow that to one folder or one branch prefix, so the app could technically write anywhere in a granted repo. Luka's code prevents this, and protecting the base branch makes GitHub enforce it too. Some customers still won't grant write access to their code.
- **Why it was left:** both alternatives give up part of PRD 0002: Automatic mode, "Update PR", or both. The GitHub App with downscoped tokens is the standard pattern.
- **Options:**
  1. **Issue plus a workflow in the customer's repo.** Luka needs only Issues: write. It files an issue carrying the post, and a workflow file Luka provides turns the issue into a branch and PR using the repo's own token. Costs:
     - the customer adds the workflow and allows Actions to create PRs
     - PRs opened by Actions don't trigger the repo's other workflows
     - updates go through the same workflow
  2. **Prefilled "new file" link.** No app at all: Luka opens GitHub's web editor with the file filled in, and the user commits and opens the PR themselves. Manual mode only, no Update PR, and long posts may exceed URL length limits.
- **Related:** `docs/prds/0002-github-blog-prs.md`, `docs/security-patterns.md` §14 (GitHub App key).
