---
name: prd
description: Agree on WHAT a complex feature is before planning HOW. Asks product questions, writes a light PRD to docs/prds/ whose acceptance criteria are the contract, iterates on the ACs until the user explicitly accepts all of them, then branches and commits the PRD as the input to implementation planning. Use as the first step for any complex feature. Args - a high-level description of the feature.
---

# PRD: align on the product before planning

The user has described a feature at a high level. Your job here is to agree with them on **what** is being built, not how. The output is a short PRD in `docs/prds/` whose acceptance criteria (ACs) are the contract for the implementation. The template and the lifecycle are in `docs/prds/README.md`; read it first.

## Feature

$ARGUMENTS

If this is empty, ask the user to describe the feature in a few sentences and stop.

## Hard rule: no implementation planning

For the whole skill, don't design the solution. No file paths, models, fields, endpoints, prompts, task lists or architecture, either in the PRD or in the conversation. If you catch yourself designing, stop and turn the thought into a product question ("should a snoozed draft still count as unread?") or a Decision the user cares about ("no new paid services"). Don't enter plan mode. Planning comes after this skill, from the agreed PRD.

Luka is a platform, not a bespoke build: no customer or industry names, rules or examples in the PRD (see CLAUDE.md).

## Steps

### 1. Ground (brief, silent)
- Read `docs/prds/README.md` and list `docs/prds/` for PRDs that overlap with or constrain this one.
- Read the plan in `CLAUDE.md`. Skim the parts of the product this feature touches (the relevant `backend/apps/` app, the `frontend/src/features/` folder, `docs/design-brief.md` for screens) to learn **how it behaves today**.
- The goal is informed questions ("today dismissing a draft removes it from the inbox; should snoozing look the same?") and not asking what the code already answers. Keep it short; this is not a code review.

### 2. Questions
- Ask **one round of at most ~8 questions**, numbered and grouped by theme: who and why · scope · main behaviour and edge cases · empty, failure and loading states · limits and spend · interaction with existing features.
- **Every question carries your proposed default**, so the user can reply "all defaults except 3 and 5".
- Use `AskUserQuestion` for crisp either/or choices; ask open questions as numbered text.
- Don't ask about things with an obvious default; list them as **Assumptions** under the questions so the user can object.
- Ask a second, smaller round only if the answers open new forks. Then write the draft.

### 3. Draft the PRD
- Next id: the highest `NNNN` in `docs/prds/` plus one (start at `0001`). Slug: short kebab-case from the feature name.
- Write `docs/prds/NNNN-<slug>.md` from the template, `status: draft`, `created:` today. Write it to disk now, so the work survives a long conversation or a `/clear`.
- Keep it light: one to two pages. Problem and Outcome are a few lines each. The ACs are where the effort goes.
- Every answered question lands somewhere: an AC, an Out-of-scope bullet, or a Decision.

### 4. Align on the ACs
**First critique your own draft.** Flag, inline next to the AC concerned:
- ACs that can't be checked, or are ambiguous ("fast", "handles errors gracefully", "intuitive")
- missing cases the feature implies: empty state, failure, another project's data, long or odd inputs, what an existing user sees after the change, anything that spends money
- ACs that describe implementation instead of observable behaviour
- anything customer- or industry-specific

**Then present and ask.** In chat, show (not the whole doc):
- the full numbered AC list, with your flags inline
- the Out-of-scope list
- any open questions

Ask the user to go through **every AC**: accept, change or drop, and add anything missing. A reply like "1–6 fine, 7 is wrong because…, add one for X" is the expected shape. **Then stop and wait for their reply.**

**Iterate.** Apply the feedback to the file, show what changed as a short diff ("AC-4 reworded, AC-9 added, AC-6 moved to Out of scope"), and ask again about anything still open. Renumbering is fine while the status is `draft`.

**Exit condition: explicit acceptance of the whole set.** Move on only when the user has accepted *all* the ACs and the Out-of-scope list in so many words ("agreed", "ACs accepted"). Before moving on, restate the final AC list once and ask for that sign-off. None of these count as acceptance:
- silence, or feedback on only some ACs. Ask about the ones not mentioned.
- "looks good, go build it" while any of your flags are unanswered. Name them and ask.
- acceptance given before the latest round of edits. Show the edits and ask again.

`Open questions` must be empty before you go on.

### 5. Store
Only after the explicit acceptance in step 4.
1. In the PRD set `status: agreed`, `agreed:` today and `branch: feat/<slug>`.
2. Follow the git workflow in `CLAUDE.md`: `git switch main && git pull`, then `git switch -c feat/<slug>`. If the working tree has unrelated changes, or you're already on a feature branch, ask before switching.
3. Commit only the PRD file (`Add PRD NNNN: <title>`), ending with the commit attribution lines from the system reminder.
4. Don't push. The push and `/security-scan` happen with the implementation.

### 6. Hand off
Finish with:
- the PRD path and the AC count
- the next prompt, ready to paste: `Plan the implementation of docs/prds/NNNN-<slug>.md`
- one line on context. Continuing in this session is the default, since the Q&A helps the planner. If alignment took more than ~3 rounds of AC edits, or the conversation is long, suggest `/clear` first: the PRD is self-contained, and a plan built from it alone shows that it really is.
