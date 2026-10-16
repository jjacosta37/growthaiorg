---
title: Blog posts as GitHub pull requests
status: shipped
prd: docs/prds/0002-github-blog-prs.md
prs: [18]
updated: 2026-10-16
---
# Blog posts as GitHub pull requests

A project can connect the GitHub repository its blog lives in. Each blog post the Content Agent writes then becomes a pull request in that repository, opened with one click or automatically. People still review and merge it on GitHub.

## Summary
Before this, getting a post onto the site meant copying the Markdown out of Luka, creating the file, writing its frontmatter and opening a PR by hand. Now a project connects one repository through the Luka GitHub App and picks:
- a base branch
- a folder
- the names its site uses for frontmatter fields

A blog draft then gets **Create PR**: Luka adds one Markdown file on a new `luka/…` branch and opens a PR. After an edit, **Update PR** pushes the new version to the same PR. In **Automatic** mode, posts with no flags get their PR as soon as they're written, and flagged posts wait for review. Luka never merges and never writes to the base branch. The user marks the draft Posted after merging, as before.

## Why
- **The last step was manual.** Drafts were finished in Luka but stalled at copy-paste, file creation and PR creation.
- **Most marketing sites built with a static site generator keep posts in git**, so a PR fits how those teams already review and deploy.
- **Control stays with people.** A PR is a proposal: the site's own review and deploy process stays in charge.

## How it behaves

**Connecting** (Settings → **GitHub pull requests**):
1. **Connect GitHub** opens GitHub's install screen. The user picks which repositories Luka may see ("Only select repositories" is recommended) and returns to Settings.
2. They choose:
   - the **repository** (from the ones they granted)
   - the **base branch** (prefilled with the repository's default)
   - the **folder** for posts (empty means the repository root)
3. Optionally, they rename the standard frontmatter fields (title, description, slug, keywords, date), for example `description` → `excerpt`. They can also add **constant fields** that every post gets, such as `author: The Team` or `featured: false`, typed as text, number or true/false. A live **preview** shows the path and frontmatter the latest blog draft would get, or a sample post's when there are no drafts.
4. **Save** checks the repository and branch with GitHub. The connection is then ready.
5. If the base branch isn't protected on GitHub, a warning explains why it should be (see Decisions).

**On a blog draft** (the inbox detail pane, above the SEO card):
- **Create PR** opens a PR. The card then shows "PR open" with a link (`#1 on GitHub`).
  - The file is `<folder>/<slug>.md`: the frontmatter, then the body, then the project's blog disclaimer if it isn't already there.
  - The frontmatter date is the day the PR is created, and updates keep it.
  - The PR description lists the meta description, slug, keywords, every flag on the draft, and a link back to the draft in Luka.
- After an **edit or regeneration**, the card says the draft changed and offers **Update PR**. Nothing is pushed without that click. A changed **slug** renames the file in the same PR.
- The slug is checked as lowercase words separated by single hyphens (at most 100 characters), both while typing and on save.
- While a create or update runs, the card says so and refreshes on its own.

**Automatic mode** (Content Agent page → **Pull requests**):
- **Manual** is the default. **Automatic** can only be chosen while the project has a ready connection.
- When a post is written in Automatic mode:
  - **No flags:** the PR opens in the same run.
  - **Any flag, SEO warnings included:** no PR. The draft says "Held for review: N flags to check first" and offers Create PR.
- **The compliance check couldn't run** (the model call failed): the draft is held the same way, with a note saying so.
- Regenerating a draft never opens or updates a PR on its own.

**Failures** show on the draft as one line plus **Retry** (or **Retry update**):
- **Name clash:** a file with the same name already exists on the base branch. Luka never overwrites it and asks for a different slug.
- **Lost access:** the app was uninstalled or suspended, or its access changed. The connection shows "needs reconnecting" in Settings, with a **Reconnect** button.
- **Missing repository or branch.** After a merge, Update PR explains that the PR's branch is gone.
- **GitHub outage:** "Try again in a few minutes."

In Automatic mode, a failed PR never stops the draft landing in the inbox.

**What doesn't change:**
- Projects without a connection see nothing new.
- Dismissed drafts and Reddit or X drafts never get a PR.
- Luka never changes a draft's status from the PR. The user marks it Posted after merging.
- **Disconnect** stops new PRs and switches the Content Agent back to Manual. Existing PRs and branches stay on GitHub, and drafts keep their links. To remove access completely, the user uninstalls the app on GitHub.

## Decisions
- **A GitHub App, not OAuth tokens or personal access tokens.** Customers choose the repositories, tokens expire after an hour, permissions can't silently grow, and org admins see and approve the install. Rejected: an OAuth app with the `repo` scope (as several git-based CMSs use), because it grants every repository the user can see.
- **Permissions: Contents and Pull requests write, Metadata read, nothing else.** Opening a PR requires pushing a branch, so some write access is unavoidable. Without Workflows, GitHub itself blocks changes to CI files.
- **Tokens narrowed per step.** Each installation token names the one repository and only the permissions that step needs. Checks get read-only tokens.
- **Code-level guard plus a branch-protection warning** (logged as a change to AC-2 after agreement). Contents: write applies to the whole repository: GitHub can't limit an app to a folder or a branch prefix. So "never the base branch, never merge" (AC-13) is enforced in Luka's code. Only branch protection makes GitHub enforce it against a bug or a leaked key, so Luka warns until the base branch is protected. Rejected for now, both kept in `docs/backlog.md`:
  - filing an issue that a workflow in the customer's repository turns into a PR (needs only Issues: write)
  - a prefilled "new file" link (no app at all)

  They give up Automatic mode or Update PR.
- **Verify the installation on connect.** GitHub returns the installation id through the browser, where anyone can edit it. Luka requires a signed state for this user and project, and a one-time OAuth code proving the installation is among the user's own. Without that, one tenant could open PRs in another's repositories. The check also records which repositories the user can **push** to on GitHub. GitHub lists an installation for anyone who can merely read one of its repositories, and Luka acts with the installation's own access, so only those repositories can be chosen. This was found by the security scan's review. The state must come back in the URL, and GitHub returns it there; this was checked against the registered app. An earlier version also accepted a copy kept in the session, in case GitHub dropped it. That copy was removed once the test showed it wasn't needed, because it let a crafted link use a real Connect click for up to 15 minutes.
- **One new file per post; never edit existing site files.** Concurrent PRs then never conflict, and Luka never edits a site's source code. Sites that list posts in one shared code file have to switch to one file per post first. A live check against a real site showed exactly that.
- **Renamable standard fields plus constant fields, not a template language.** This covers the common setups (an `excerpt` instead of `description`, an `author`, a `featured` flag) with nothing to inject into. Values are written with `yaml.safe_dump`.
- **Hold every flagged post in Automatic mode, SEO flags included** (the user's call). Flags are warnings in the inbox, and an unattended PR would bypass them.
- **No tracking of the PR's state.** Luka would need polling, or webhooks reaching the home-hosted server. The user marks Posted after merging.
- **No sitemap or `robots.txt` edits.** Most site frameworks generate them at build time. A check after publishing that the post can be indexed is in the backlog.
- **The PR body neutralises `@` and `#`** in model-written text, so a draft can't notify people or close issues on GitHub.
- **Automatic mode fails closed.** A post whose compliance check couldn't run is held like a flagged one. Otherwise "no flags" would mean "unchecked", which text in a source could provoke.

## How it works

### Flow
1. **Connect:** `POST /api/github/connect/` returns the install URL with a signed state. GitHub sends the browser to `GET /api/github/callback/` and echoes the state there.
2. **Callback:** `connections.complete_install` checks the state and project ownership, then calls `verify_installation`. That exchanges the OAuth code, looks for the installation in `GET /user/installations`, and collects the repositories the user can push to. With none, nothing is saved. Errors go back as codes (`ConnectError.code`). The connection is saved as `incomplete`, or `ready` on a reconnect when the saved repository is still reachable.
3. **Settings:** `connections.save_settings` checks:
   - the repository is in the installation's list and in `allowed_repos`
   - the base branch exists and isn't a `luka/` branch, and records whether it's protected
   - the folder (`clean_folder`) and the field settings (`FrontmatterSettings`)

   On success the status becomes `ready`.
4. **Create:** the view calls `services.request(draft, "create")`. It locks the draft row, refuses with 409 when the draft can't take a PR or a publish run is already queued, and queues a `publish_pr` run (`publish_pr_task`). The task then calls `services.open_pull_request`:
   1. Claims the draft's `DraftPullRequest` row.
   2. Reads the base branch and refuses if `<folder>/<slug>.md` exists there.
   3. Creates `luka/<draft id>-<slug>` (at most 100 characters), or reuses it.
   4. Commits the rendered file (`frontmatter.render_post`).
   5. Reuses an open PR from that branch, or creates one.

   Each step is safe to retry.
5. **Update:** `services.update_pull_request` pushes the current version to the same branch. On a slug change it checks the new name is free on the base branch, adds the new file and deletes the old one on Luka's branch. Then it refreshes the PR's title and body.
6. **Automatic:** the content run's `draft_post` calls `services.after_draft_written` after linting. It holds a flagged draft, or calls `open_pull_request` inside the same run.

### Data model
- **`GitHubConnection`**, one per project: `installation_id`, `account`, `allowed_repos` (the ones the connecting user can push to), `repo`, `base_branch`, `base_branch_protected`, `folder`, `field_names` (standard field → name in the file), `constant_fields` (`[{key, value}]`), and `status`: `incomplete` / `ready` / `needs_reconnect`.
- **`DraftPullRequest`**, one per draft, enforced by a one-to-one key: `state` (`held` / `pending` / `open` / `failed`), `repo`, `branch`, `file_path`, `number`, `url`, `post_date`, `pushed_version` and `note`. `note` holds why the draft was held, or the last failure, in Luka's own words. A `pending` row older than 10 minutes (`PENDING_TIMEOUT`) no longer blocks a retry, so a create that died mid-way can't stick.
- `AgentConfig.PublishMode` gains `automatic`, and `AgentRun.Kind` gains `publish_pr`.
- `BlogContent.slug` (`apps/inbox/content.py`) is validated as kebab case.

### API
| Method and path | What it does |
|---|---|
| `GET /api/github/` | Whether this server has a GitHub App configured, the project's connection, and the standard field names |
| `POST /api/github/connect/` | The install URL (409 if the app isn't configured) |
| `GET /api/github/callback/` | GitHub's return; redirects to `/settings?github=connected\|requested\|error` |
| `GET /api/github/repos/` | Repositories the installation can reach |
| `PATCH /api/github/connection/` | Save repository, branch, folder and field settings |
| `DELETE /api/github/connection/` | Disconnect |
| `POST /api/github/preview/` | Path and frontmatter for unsaved settings |
| `POST /api/drafts/:id/pull-request/` | Create, or retry creating (202 with the run, or 409 with the reason) |
| `POST /api/drafts/:id/pull-request/update/` | Push the current version to the PR |

- `GET /api/drafts/:id/` gains `pull_request`: state, number, url, repo, note, busy, `can_create`, `needs_update` and `can_update`. It is null for drafts that aren't blog posts, and for blog drafts when there's no connection and no PR.
- `PATCH /api/agents/:type/` accepts `publish_mode`, and the agent summary carries `automatic_available`.

### Frontend
- `features/settings/GitHubCard.tsx`: connect, settings form, constant fields, live preview, protection warning, reconnect and disconnect.
- `features/inbox/PullRequestCard.tsx`, mounted in `BlogRenderer`'s side panel. The slug field validates inline.
- The **Pull requests** select on the Content Agent page (`features/agents/AgentPage.tsx`).
- `App.tsx` honours `?project=` on a deep link, so the PR's "Open this draft in Luka" link opens the right project.
- `useDraft` polls while `pull_request.busy`.

### Configuration
| Env var | Default | Meaning |
|---|---|---|
| `GIT_HOST` | `github` | `fake`: an in-memory host, one per process (local dev; tests always use it) |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_CLIENT_ID` | empty | The app's identity |
| `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_CLIENT_SECRET` | empty | The app's secrets (`\n` allowed for line breaks in the key) |
| `LUKA_APP_URL` | `http://localhost:5173` | Where GitHub sends users back, and the base of the link in PR descriptions |

Registration steps are in the README ("GitHub pull requests").

Other limits:
- at most 10 constant fields, each value one line of at most 200 characters
- field names: a letter or `_` first, then letters, digits, `-` or `_`, 40 characters at most
- folders: at most 200 characters, with no `..` and no hidden segments
- the connect state expires after 15 minutes

## Security and tenancy
- **Tenancy:**
  - Every endpoint resolves the project through `current_project`. Draft actions use `drafts_qs`.
  - The callback trusts nothing from the query string except the OAuth code, which GitHub verifies.
  - The publish task loads the draft scoped to `run.project`.
  - Cases are in `tests/test_tenancy.py`.
- **New trust boundary:** the worker writes into a tenant's repository. See `docs/security-patterns.md`:
  - §1: the trust boundaries table
  - §2: connecting GitHub
  - §4: the new secrets
  - §6: GitHub as a fixed-host provider, called through `guarded_client`
  - §7: the new allowlist row
  - §10: GitHub as a third party that receives content
  - §11: no spend, bounded by drafts
  - §14 Medium 13: the reach of the app key
- **The write guard:** `check_writable` refuses any branch outside `luka/` before a request is made, in both the GitHub host and the fake.
- **What reaches the browser:** GitHub's response text never does. Errors are Luka's own messages (`GitHostError.reason`), and PR links are accepted only as `https://github.com/<repo>/pull/…` (`safe_pr_url`).

## Observability
- Each Create or Update click is a `publish_pr` run. Automatic PRs appear inside the content run.
- `record_external(provider="github", purpose="create_pr" | "update_pr")` writes an `ExternalUsage` row (cost 0) and a run event carrying the repository, PR number and duration. Failures appear as a warning with Luka's reason.
- Every GitHub call is a LangSmith tool span (`github.<operation>`) with status and duration.
- Log lines carry ids only: draft, project, installation, PR number and repository. Unexpected GitHub failures (not lost access, not found, or a name clash) are logged at ERROR, so they file a Sentry issue.

## Testing
- `tests/test_git_host.py`: the GitHub client against a stubbed HTTP layer:
  - the JWT and narrowed tokens
  - the write guard before any request
  - mapping HTTP failures to Luka's errors, without GitHub's text
  - installation verification
- `tests/test_publishing.py`: every AC against `FakeGitHost`:
  - connect, tampered or foreign installations, a return without `state`
  - settings validation and preview
  - the file format, including YAML-hostile titles
  - create, update, rename, retry and no second PR
  - Automatic mode and holds, failures, disconnect
  - the trail carrying no content
- `tests/test_tenancy.py`: the GitHub section.
- **Checked by hand in the browser with `GIT_HOST=fake`:** the settings card, Create PR, edit then Update PR, and the mode select.
- **Not yet checked against real GitHub:** AC-2 and AC-17 need the GitHub App registered (README steps).

## Limitations and follow-ups
- **Returns that start on GitHub are refused.** Installing from the app's GitHub page, changing its repository access there, or an owner approving an install request all send the browser to Luka without `state`. Settings then asks the user to click Connect or Reconnect in Luka, which picks up the installation they already made.
- `GIT_HOST=fake` keeps one fake per process, so in local dev the web and worker processes see different fake repositories.
- Backlog:
  - checking a published post can be indexed
  - internal links in posts
  - more blog layouts (shared data files, MDX, HTML bodies, a CMS)
  - opening PRs without write access

## Where to look
| What | Where |
|---|---|
| GitHub host interface, write guard, errors | `backend/providers/git_host/base.py` (`GitHost`, `check_writable`, `GitHostError`) |
| GitHub App client | `backend/providers/git_host/github.py` (`GitHubAppHost`) |
| In-memory host | `backend/providers/git_host/fake.py` (`FakeGitHost`) |
| Connecting and settings | `backend/apps/publishing/connections.py` (`complete_install`, `save_settings`, `disconnect`) |
| File format | `backend/apps/publishing/frontmatter.py` (`FrontmatterSettings`, `render_post`, `clean_folder`) |
| Create, update, automatic | `backend/apps/publishing/services.py` (`request`, `open_pull_request`, `update_pull_request`, `after_draft_written`) |
| Task | `backend/apps/publishing/tasks.py` (`publish_pr_task`) |
| Endpoints | `backend/apps/publishing/views.py`, `backend/apps/publishing/urls.py` |
| Slug rule | `backend/apps/inbox/content.py` (`BlogContent`) |
| Disclaimer rule | `backend/apps/policy/service.py` (`with_blog_disclaimer`) |
| UI | `frontend/src/features/settings/GitHubCard.tsx`, `frontend/src/features/inbox/PullRequestCard.tsx` |

## History
- 2026-10-15 · #18 · First version.
- 2026-10-16 · Connecting requires `state` in GitHub's return URL; the session fallback is removed, since the registered app showed GitHub sends it back.
