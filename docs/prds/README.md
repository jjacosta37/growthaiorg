# Feature PRDs

A PRD records what a complex feature does before anyone plans how to build it. Its acceptance criteria (ACs) are the contract between the user and Claude Code: the implementation plan maps every AC, and the PR shows how each one was checked. Create one with `/prd <feature description>` (`.claude/skills/prd/SKILL.md`).

## Files
`NNNN-<slug>.md`: a zero-padded number (the next free one) plus a short kebab-case slug, e.g. `0003-draft-snooze.md`. Numbers are never reused, including for dropped PRDs.

## Lifecycle
| Status | Meaning |
|---|---|
| `draft` | Being discussed. ACs can still change and be renumbered freely. |
| `agreed` | The user explicitly accepted every AC. Committed as the first commit of `feat/<slug>`. |
| `building` | Implementation has started. |
| `shipped` | The PR has merged. |
| `dropped` | Not built. Keep the file and add one line saying why. |

From `agreed` on, ACs change only with the user's approval, and each change is logged under **Changes after agreement**. Never edit an agreed AC silently.

## Writing good ACs
- Each one is **observable and checkable**: someone could watch the app or read a test and say pass or fail.
- Describe **behaviour, not implementation**: what the user sees or what the system does, never tables, endpoints or files.
- Plain statements. Use Given/When/Then only when a precondition matters.
- Cover the states the feature implies: empty, failure, another project's data, existing users after the change, anything that spends money.
- Tag how each one will be verified: `test`, `manual` or `both`.
- Keep them platform-neutral: no customer or industry names or examples.

## Template
```markdown
---
id: NNNN
title: <Feature name>
status: draft
created: YYYY-MM-DD
agreed:
branch:
---
# <Feature name>

## Problem
2–4 sentences: what hurts today, for whom, why now.

## Outcome
What is true for the user once this ships. 1–3 bullets.

## Scope
**In:**
-

**Out (non-goals):**
-

## Behaviour
A short walkthrough of the main flow and its states (empty, loading, error),
in user terms. Bullets or a numbered flow; no screens or APIs.

## Acceptance criteria
- **AC-1** … *(verify: test)*
- **AC-2** … *(verify: manual)*

## Decisions
Product calls made during alignment, one line each with the reason.
Constraints the user cares about go here too (e.g. "no new paid services").

## Open questions
None. (This must be empty before the status moves to agreed.)

## Changes after agreement
<!-- YYYY-MM-DD · AC-n · what changed · why (approved by the user) -->
```
