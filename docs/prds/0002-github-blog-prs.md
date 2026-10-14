---
id: 0002
title: Blog posts as GitHub pull requests
status: draft
created: 2026-10-14
agreed:
branch:
---
# Blog posts as GitHub pull requests

## Problem
The Content Agent writes finished blog posts, but getting one onto the company's site is manual: copy the Markdown out of Luka, create the file in the site's repository, add the frontmatter, open a pull request. For teams whose blog lives in a GitHub repository, that copy-paste step is where drafts stall.

## Outcome
- A project can connect a GitHub repository, and a blog post draft becomes a pull request against it in one click (Manual) or as soon as it is written (Automatic).
- The user stays in control of publishing: Luka opens PRs, people merge them.

## Scope
**In:**
- Connecting one GitHub repository (and a folder in it) per project, with access limited to the repositories the user grants.
- A per-project mode on the Content Agent: Manual (a "Create PR" action on the draft) or Automatic.
- One branch and one PR per blog post, containing one Markdown file with a fixed frontmatter set.
- Updating an open PR from Luka after editing or regenerating the draft.
- Clear failure states with retry, and a "needs reconnecting" status for the connection.

**Out (non-goals):**
- Tracking PR merge/close state. The user marks the draft Posted by hand, as today.
- Editing `robots.txt`, the sitemap or any other site file. Only the post's own file is added.
- Custom frontmatter templates or file layouts beyond the fixed set.
- Checking that a published post can be indexed (page loads, no `noindex`, in the sitemap): a backlog follow-up.
- Images and other assets.
- Reddit and X drafts.
- GitLab, Bitbucket and GitHub Enterprise.
- Luka merging PRs or pushing to the base branch.
- Subscription gating.

## Behaviour
1. **Connect.** In the project's settings the user connects GitHub, grants access to the repositories they choose, then picks one repository, a base branch (defaults to the repo's default branch) and a folder for posts. Until then nothing about the Content Agent changes.
2. **Choose a mode.** On the Content Agent's settings: Manual (default) or Automatic. The mode is disabled, with a hint, while no repository is connected.
3. **Manual.** A blog post draft shows "Create PR". Pressing it creates a branch and a PR with the post's file, and the draft then shows "PR open" with a link to it.
4. **Automatic.** When the agent finishes a blog post, Luka opens the PR right away. A post with compliance flags is not PR'd; it stays in the inbox with a note saying it was held for review, and offers "Create PR" like Manual.
5. **The PR.** One Markdown file named from the slug in the chosen folder. Its frontmatter holds title, description, slug, keywords and date, then the body, then the project's blog disclaimer if one is set. The PR description shows the meta fields, any compliance flags, and a link back to the draft in Luka.
6. **After the PR.** Editing or regenerating the draft offers "Update PR", which pushes the current version to the same branch. Nothing is pushed automatically. Once the user merges the PR on GitHub, they mark the draft Posted in Luka as they do today.
7. **Failures.** If the PR can't be created or updated (access revoked, repo or base branch gone, a file with the same name already on the base branch), the draft shows what went wrong and a "Retry". Luka never overwrites an existing file; on a name clash it asks the user to change the slug in the draft's slug field. When access is lost, the connection shows "needs reconnecting".
8. **Disconnect.** Stops new PRs and switches the mode back to Manual. Existing PRs and branches on GitHub are left alone.

## Acceptance criteria
- **AC-1** A project with no GitHub connection behaves exactly as today: no "Create PR" action, and Automatic mode can't be selected. *(verify: both)*
- **AC-2** A user can connect GitHub to a project and pick one repository, a base branch (default: the repo's default branch) and a folder. Luka can reach only the repositories the user granted. *(verify: manual)*
- **AC-3** A project's connection, repository and PRs are invisible and unusable from any other project, including another project of the same user. *(verify: test)*
- **AC-4** In Manual mode, "Create PR" on a blog post draft creates one new branch and one PR against the chosen base branch, adding exactly one file in the chosen folder. The draft then shows "PR open" and links to the PR. *(verify: both)*
- **AC-5** The file is named from the post's slug. Its frontmatter contains title, description, slug, keywords and date (the day the PR is created), followed by the body and then the project's blog disclaimer when one is set. *(verify: test)*
- **AC-6** A blog post draft has its own editable slug field, shown with the draft's SEO fields and accepted only as lowercase words separated by hyphens. The file name follows it. Changing the slug of a draft whose PR is open renames the file in that PR on the next "Update PR". *(verify: test)*
- **AC-7** The PR description contains the meta fields, every compliance flag on the draft, and a link to the draft in Luka. *(verify: test)*
- **AC-8** In Automatic mode, a blog post with no compliance flags gets its PR as soon as the agent finishes it, with no user action. *(verify: test)*
- **AC-9** In Automatic mode, a blog post with compliance flags gets no PR. The draft says it was held for review and offers "Create PR". *(verify: test)*
- **AC-10** A draft with an open PR offers "Update PR" after it is edited or regenerated. Pressing it pushes the current version to the same branch and PR; no new PR is opened. Edits never update the PR without that action. *(verify: test)*
- **AC-11** "Create PR" can't open a second PR for a draft that already has one, including on a double click or a retry. *(verify: test)*
- **AC-12** Luka never pushes to the base branch, never merges a PR, and never overwrites a file that already exists on the base branch. On a name clash the draft shows an error asking for a different slug. *(verify: test)*
- **AC-13** When creating or updating a PR fails (access revoked, repo or base branch missing), the draft shows a one-line reason and a "Retry". In Automatic mode the draft still lands in the inbox. Lost access marks the connection "needs reconnecting". *(verify: test)*
- **AC-14** Dismissed drafts and drafts that aren't blog posts never get a PR, and never offer "Create PR". *(verify: test)*
- **AC-15** A user marks a draft with a PR as Posted by hand, exactly as today. Luka does not change the draft's status based on the PR. *(verify: test)*
- **AC-16** Disconnecting stops new PRs, switches the project back to Manual, and leaves existing PRs and branches on GitHub untouched. Drafts that already have a PR keep their link. *(verify: manual)*
- **AC-17** Each PR created or updated shows in the run's or the draft's activity trail, with the repository and PR number. No post content goes to logs. *(verify: test)*

## Decisions
- One repository and one folder per project: matches "one project = one company website".
- Default mode is Manual, so nothing reaches a repository without a person choosing it.
- Flagged posts are held in Automatic mode: the compliance lint warns in the inbox today, and an unattended PR would bypass that warning.
- Luka opens PRs only; merging stays with people, so the site's own review and deploy process stays in charge.
- No PR-state tracking for now: it needs either polling or webhooks reaching the home-hosted server; the user marks Posted by hand.
- The frontmatter date is the day the PR is created; the user can change it in the PR before merging.
- The slug gets its own field: the file name depends on it, and a name clash is fixed by changing it.
- Fixed frontmatter set: covers the common static-site setups without a template language.
- Sitemap and `robots.txt` are left to the site: most site frameworks regenerate the sitemap on build, and editing generated files from a PR would be fragile.

## Open questions
None.

## Changes after agreement
<!-- YYYY-MM-DD · AC-n · what changed · why (approved by the user) -->
