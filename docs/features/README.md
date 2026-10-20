# Feature docs

A feature doc records what a feature **is**: how it behaves for the user, why it was built that way, and how it works in the code. It's what the user reviews a feature's PR from, and what you read months later, when you want to remember a feature, answer a question about it, or change it safely.

Create or update one with `/feature-doc <feature>` (`.claude/skills/feature-doc/SKILL.md`) on the feature's branch, **before the PR opens**, so it ships in the same PR. When review asks for a change that alters the feature, the doc is updated in the same commit (CLAUDE.md, "Feature docs").

## How it differs from a PRD
| | PRD (`docs/prds/`) | Feature doc (`docs/features/`) |
|---|---|---|
| Written | Before planning | With the feature, before its PR opens; kept current through review |
| Records | What was **agreed**: the acceptance criteria | What was **built**, and why |
| Content | Product only, no implementation | Product **and** technical |
| Changes | Only with approval, logged | Updated in every PR that changes the feature |

When a feature has a PRD, its doc links to it and doesn't copy the ACs. When it doesn't, the doc is the only record of the product decisions, so they go in it.

## Files
`<slug>.md`, a short kebab-case name for the feature, e.g. `reddit-feedback-learnings.md`. When the feature has a PRD, use the PRD's slug without its number, so the two pair up. One file per feature. A later change to the feature updates its doc, with a line under **History**; it doesn't start a new one. Changes made during a PR's own review don't get a History line of their own: the doc simply describes the feature as that PR ships it.

## Writing a good one
- **Accurate over complete.** Every name, path, limit and endpoint is checked against the code on the feature's branch at the time of writing. A doc that is wrong is worse than a short one.
- **The why is the valuable part.** The code shows what was built; only the doc keeps why, and what was rejected. Spend the effort on Decisions.
- **Point at the code; don't copy it.** Name the file and the function or class (`apps/feedback/pipeline.py`, `digest_feedback`). No line numbers: they drift with every edit.
- **Product first.** The top half reads without knowing the code; the technical half is for whoever changes it next.
- **One to three pages.** Leave out any section that has nothing in it, apart from Summary, Decisions and History.
- **Platform-neutral** like the rest of the repo: no customer or industry names or examples.
- **No secrets or content**: no keys, no real prompts' output, no user data.

## Template
```markdown
---
title: <Feature name>
status: shipped        # shipped | changed | removed: the feature as this PR ships it
prd:                   # docs/prds/NNNN-<slug>.md, if there is one
prs: []                # e.g. [4, 5]
updated: YYYY-MM-DD
---
# <Feature name>

<One or two sentences: what it does and for whom.>

## Summary
3–6 lines: the problem it solves, what the user can now do, and the moving parts in one breath.

## Why
What hurt before, for whom, and what prompted the work.

## How it behaves
The user's view, with no code:
- where it lives in the UI and how you reach it
- the main flow, step by step
- the rules: limits, defaults, what's automatic and what needs the user
- empty, loading, error and edge states
- how it interacts with other features

## Decisions
One bullet per product or technical call, with the reason and the alternative that was rejected.
- **<Decision>.** <Why.> Rejected: <alternative>, because <reason>.

## How it works
For whoever changes it next. Use the subsections that apply.
### Flow
A short numbered flow, or a mermaid diagram (as in `docs/backend-guide.md`), from trigger to result.
### Data model
New or changed models and the fields that matter.
### API
Endpoints: method, path, what it does.
### Pipelines and tasks
Runs, Celery tasks, schedules, and what each step does.
### LLM calls
Prompt files (`backend/prompts/<task>/vN.md`), model tier, what goes into the prompt, what comes out, and the bounds on calls and tokens.
### Frontend
Components and where they're mounted.
### Configuration
Settings, env vars and per-agent config fields, with their defaults.

## Security and tenancy
How it's scoped to a project, trust boundaries it adds, and the `docs/security-patterns.md` sections it touches.

## Observability
How to tell what it did: the runs and RunEvents it writes, the log lines, where its spend shows up.

## Testing
Test files and what they cover; anything that was only checked by hand.

## Limitations and follow-ups
Known gaps, accepted trade-offs and ideas that were left for later.

## Where to look
| What | Where |
|---|---|
| <thing> | `<path>` (`<symbol>`) |

## History
- YYYY-MM-DD · #<PR> · <what changed>
```

## Index
| Feature | Summary | Updated |
|---|---|---|
| [Blog posts as GitHub pull requests](github-blog-prs.md) | Connect a project's repository through the Luka GitHub App; blog drafts become PRs with one click or automatically, with the site's own frontmatter names. Luka never merges. | 2026-10-16 |
| [Evidence-backed blog topics](evidence-backed-topics.md) | Content Agent topics backed by Reddit questions and keyword search volume and difficulty, ranked by weights you set; topic research fetches Reddit posts that still get replies. | 2026-10-13 |
| [Friendly agent schedules](friendly-agent-schedules.md) | Plain-words schedule builder (every few hours, daily, chosen days, weekly, monthly) in the project's timezone, with a live preview of the next runs; no agent runs more than once an hour. | 2026-10-16 |
| [Reddit Agent feedback, learnings and reply voice](reddit-feedback-learnings.md) | Rate and comment on drafts; the agent folds it into editable learnings for writing and post selection. Plus custom instructions, a human-sounding reply style and replies pitched to the poster. | 2026-10-08 |
