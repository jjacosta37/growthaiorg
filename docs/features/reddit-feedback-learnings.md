---
title: Reddit Agent feedback, learnings and reply voice
status: shipped
prd:
prs: [4, 5, 11]
updated: 2026-10-08
---
# Reddit Agent feedback, learnings and reply voice

The Reddit Agent learns from what you tell it about its drafts, follows your standing instructions, writes replies that sound like a person rather than an AI, and pitches each reply to the person who asked.

## Summary
Before this, every Reddit draft came from the same fixed prompt, and nothing you said about a draft carried over to the next one. Now you can rate and comment on any Reddit draft. An LLM folds that feedback into a short, editable list of **learnings**: lessons about *writing* replies, and lessons about *which posts* to reply to. Every later draft and scoring call uses them. Alongside that, the agent has a **Custom instructions** box, a drafting prompt with explicit "sound like a person" rules, and a one-line read of the poster ("Written for: …") that shapes how technical the reply is.

## Why
Four problems with the Reddit Agent:
1. **No memory.** The same mistakes came back draft after draft, and the only fix was editing each draft by hand.
2. **Replies sounded like AI.** Openers like "Great question", closers like "Hope this helps", em dashes, bold headers and tidy bullet lists. Reddit readers spot that and downvote it.
3. **No way to give standing instructions.** The Content and X agents already had a guidance field; Reddit didn't.
4. **Replies ignored who was asking.** A self-described beginner got the same jargon an expert would.

## How it behaves

**Giving feedback** (Inbox → a Reddit draft → the **Feedback** card, under the comment):
- Pick 👍 or 👎, write a comment, or both, then **Save feedback**. An empty submission is refused.
- Feedback you've already given on that draft is listed in the card.
- Feedback is accepted on any Reddit draft, including posted and dismissed ones.
- The card says "Remembered for future replies" and links to the Reddit Agent page.

**Remembering a regenerate instruction:** in **Regenerate ▾ → Custom instruction…**, tick **Remember for future replies**. The draft is regenerated as usual, and the instruction is also saved as feedback. The toggle only appears on Reddit drafts.

**What isn't feedback:** dismissing a draft, its dismiss reason or note, and edits you make before posting. Dismissals were left out on purpose; see Decisions.

**How feedback becomes learnings:**
- About a minute after you give feedback, a background step folds every entry not yet absorbed into the learnings. Ten quick comments cost one call.
- Until then, the new entries are already passed to the drafting prompt as they are, so writing feedback applies to the very next draft.
- The step generalizes from the specific case ("too long" becomes "keep replies short") and keeps each section to about 250 words, with the newer lesson winning when two conflict.
- Feedback that asks for something the content rules forbid is ignored. The content rules always win.

**The Learnings card** (the Reddit Agent page, between Run history and Skipped):
- Two boxes you can edit freely:
  - **Writing:** how replies should be written. It goes to every draft.
  - **Post selection:** which posts are worth a reply. It goes to the scoring step.
- A status line: "Updating from new feedback…", "N new entries not folded in yet (already used in new drafts)", "Edited by you …" or a default hint.
- **Feedback given:** the latest 50 entries, each with its rating, comment, source, age and a link to its draft, and a × to delete it.
- **Rebuild** re-learns from the feedback alone and replaces the learnings, hand edits included. It asks before doing that, and says so if a digest is already running.
- While a digest is running the card refreshes itself; it also checks every 15 seconds while entries are waiting.

**Your edits are kept:** once you edit the learnings, later digests keep your wording and only add to it. Deleting a feedback entry doesn't remove a lesson already learned from it; Rebuild does. Rebuilding with no feedback left clears the learnings.

**Custom instructions** (the Reddit Agent page → Configuration): free text, up to 2000 characters, added to every reply. The content rules still take priority, as the field's hint says.

**How replies read now:**
- Plain words, contractions, sentences of different lengths, first person where natural, but never an invented personal experience.
- No praising or restating the question, no closing pep talk, no em dashes, none of the phrases that mark text as generated ("it's worth noting", "delve"…), no headings or bold, and a list only when the answer really is steps.
- The draft shows **Written for: …** above the comment when the poster said something about themselves, e.g. that they aren't technical. A beginner gets terms explained; an expert gets the specifics. With no cues the line is hidden and the reply is pitched at a smart non-specialist. The agent never guesses at things the poster didn't say.

**Priority when they conflict:** the content rules, then your custom instructions and the learnings, then the default style.

## Decisions
- **A digest, plus the newest raw entries, rather than sending all feedback.** Sending every entry grows the prompt with each one and leaves the model to reconcile contradictions; keeping only the latest N forgets old lessons. The digest stays about the same size, stays readable and editable, and the raw entries close the gap until it runs. Rejected: all raw entries, and the latest N only.
- **Dismissals are not feedback.** Your call during review: a dismiss reason is too open to interpret and could steer the agent in unexpected ways. Rejected: turning dismiss reasons and notes into feedback.
- **Edits before posting are not used either.** Offered as an option and not chosen. Rejected: learning from the diff between the AI draft and the posted text.
- **Learnings also steer post selection.** Your choice, so "stop picking posts like this" changes which posts get drafts, not only how they're written.
- **Two sections, writing and selection.** They feed different steps: scoring runs on the fast model for every post (up to 200 a run), and drafting runs on the writer model only for posts above the threshold. Writing lessons would cost tokens on every post and could skew scores; selection lessons are noise once a post is chosen. Rejected: one combined learnings text.
- **Raw entries reach drafting at once, but not scoring.** Scoring sees only the digested selection lessons, so selection feedback takes effect after the digest (about a minute). This keeps unprocessed text out of the per-post scoring prompt.
- **A one-minute delay before digesting.** Bursts of feedback become one call. The delay is a setting.
- **Learnings sit after the prompt-cache breakpoint.** The cached prefix (guardrails and context documents) stays identical, so prompt caching keeps working.
- **Storage is per agent, not Reddit-only.** Feedback and learnings are keyed by agent type, so the Content and X agents can use them later. Only the Reddit Agent reads them today.
- **Third-party text is kept out of the instructions.** Reddit post titles and draft excerpts go to the digest only, escaped and marked as data. The drafting prompt gets only your rating and your own words. A crafted post title could otherwise pose as a lesson and steer every future draft (found by the security scan on #4).
- **The poster read is written before the reply.** `poster_read` is the first field of the model's structured output, so the model reads the poster before writing, and it's stored with the draft so you can see who the reply was pitched at.

## How it works

### Flow
1. **Feedback in:** `POST /api/drafts/<id>/feedback/`, or a regenerate request with `remember: true`. Both call `services.record()`, which stores an `AgentFeedback` row pinned to the draft's current version. After the transaction commits, it schedules `digest_feedback_task` with a delay of `FEEDBACK_DIGEST_DELAY_SECONDS`.
2. **Digest:** `digest_feedback_task` does nothing if no feedback is pending. Otherwise it creates a `digest_feedback` run with `start_digest()`, then `run_digest_task` runs it.
3. **Inside the run:** `pipeline.digest_feedback()` takes the pending entries (oldest first, at most 100). It sends them with the current learnings to `feedback.digest`, saves the result to `AgentLearnings` and stamps the entries' `digested_at`. If more feedback arrived meanwhile, it schedules another digest.
4. **Drafting:** `comment_variables()` in the Reddit pipeline adds the custom instructions, the writing learnings and up to 20 pending entries to the `reddit.comment` prompt. Regenerations use the same function.
5. **Scoring:** `post_variables()` adds the selection learnings to `reddit.score`. Both the "Run now" and the scheduled batch scoring paths build their input from it.
6. **Rebuild:** `POST .../learnings/rebuild/` creates the run in the view (409 if a digest is active) and queues `run_digest_task`. The run re-learns from the newest 100 entries without the current learnings.

### Data model
- **`AgentFeedback`** (`apps/feedback/models.py`): project, agent type, draft and draft version, source (`explicit` for the feedback box, `instruction` for a remembered regenerate instruction), rating (`up`, `down` or blank), text (up to 2000 characters) and `digested_at` (empty while pending).
- **`AgentLearnings`**: one per project and agent. `writing_md`, `selection_md`, and source (`ai` or `human`; editing sets `human`, and a digest sets it back to `ai`).
- **`AgentRun.Kind.DIGEST_FEEDBACK`**: the digest's run kind.
- **`RedditCommentContent.poster_read`**: stored with each Reddit draft version (`apps/inbox/content.py`).
- **`RedditAgentConfig.guidance`**: the custom instructions (`apps/reddit/config.py`).

### API
| Method | Path | Does |
|---|---|---|
| POST | `/api/drafts/<id>/feedback/` | Record `{rating?, text?}` on a draft; returns the draft with its `feedback` list |
| GET | `/api/agents/<type>/learnings/` | The learnings, `pending` count, `digesting` flag and the latest 50 entries |
| PATCH | `/api/agents/<type>/learnings/` | Hand-edit `{writing?, selection?}` (up to 4000 characters each) |
| POST | `/api/agents/<type>/learnings/rebuild/` | Re-learn from all feedback; 409 while a digest runs |
| DELETE | `/api/agents/<type>/feedback/<id>/` | Delete one entry |

Also: `POST /api/drafts/<id>/regenerate/` accepts `remember`, and the draft detail response includes `feedback`.

### LLM calls
| Prompt | Tier | Gets | Returns |
|---|---|---|---|
| `backend/prompts/feedback/digest/v1.md` | fast, `max_tokens` 2000, no context docs | the current learnings (and whether you edited them), plus each entry's rating, comment, escaped post title and a 300-character draft excerpt | `FeedbackDigest {writing, selection}` |
| `backend/prompts/reddit/comment/v4.md` | writer | the post, the custom instructions, the writing learnings, pending entries (rating and your text only) | `RedditComment {poster_read, body, mentions_product}` |
| `backend/prompts/reddit/score/v5.md` | fast | the post, plus the selection learnings | `RelevanceScore` (unchanged) |

- `reddit/comment/v4.md` replaced v3 and carries the human-voice and write-for-the-poster rules.
- `reddit/score/v4.md` is kept only while scheduled batches submitted with it are still pending, because a batch is collected with the prompt version it was submitted with. Delete it once none are.

### Frontend
- `frontend/src/features/inbox/FeedbackCard.tsx`: the Feedback card, mounted in `DraftDetail.tsx` for Reddit drafts.
- `frontend/src/features/agents/LearningsCard.tsx`: the Learnings card, mounted in `AgentPage.tsx` for the Reddit Agent.
- `DraftDetail.tsx`: the "Remember for future replies" toggle in the custom-instruction dialog.
- `RedditRenderer.tsx`: the "Written for: …" line. `ConfigForms.tsx`: the Custom instructions field.
- Hooks in `frontend/src/lib/queries.ts`: `useDraftFeedback`, `useLearnings`, `useSaveLearnings`, `useRebuildLearnings`, `useDeleteFeedback`.

### Configuration
- `FEEDBACK_DIGEST_DELAY_SECONDS` (env, default 60): the wait before digesting new feedback.
- Code constants: `RECENT_FEEDBACK_LIMIT` = 20 and `FEEDBACK_TEXT_LIMIT` = 2000 (`apps/feedback/services.py`); `DIGEST_BATCH_LIMIT` = 100 and `EXCERPT_CHARS` = 300 (`apps/feedback/pipeline.py`); `ENTRIES_SHOWN` = 50 (`apps/feedback/views.py`).

## Security and tenancy
- **Scoping:** every endpoint is scoped to the caller's project. Draft feedback goes through `drafts_qs(request)`; the learnings and entry endpoints use `current_project(request)` and check the agent type against the registry. The digest works only from `run.project`. Cases in `tests/test_tenancy.py` cover feedback on another project's draft, and reading, editing or deleting another project's learnings and entries.
- **Model output:** writing `AgentLearnings` is on the `docs/security-patterns.md` §7 allowlist. It's shown, editable and rebuildable, and it only shapes drafts and scores, which a human triages.
- **Prompt injection:** third-party text in the digest is escaped (`tag_safe`), delimited and labelled as data, and it never reaches the drafting prompt's system section (see Decisions).
- **Spend (§11):** one digest at a time per project, the one-minute delay, at most 100 entries per digest, a 2000-token output cap, and at most 20 raw entries per drafting call.

## Observability
- **Each digest is an `AgentRun` of kind `digest_feedback`.** It shows in the status line while running, and its RunEvents record how many entries were folded in, their ids and the output length. They never contain the feedback text.
- **Log lines:** recording feedback logs the entry, draft and project ids. A digest deferred because another is running, or rescheduled for late feedback, is logged with ids.
- **Spend:** digest calls are `LLMCall` rows with task `feedback.digest`, so they show in Stats like any other call.

## Testing
- `backend/tests/test_feedback.py` covers:
  - recording from both sources, and that dismissing records nothing
  - that the digest folds in only pending entries and reschedules for late ones
  - rebuild, clearing when empty, and the 409 while a digest runs
  - that hand edits reach the digest as human-written
  - the prompt inputs: guidance, learnings, raw entries, and unchanged prompts when there's no feedback
  - that `poster_read` is stored
  - escaping of a hostile post title
- `backend/tests/test_tenancy.py`: the tenancy cases above.
- **Manual:** the UI was checked in a browser with seeded data. A run against the real model hasn't been recorded, so how much less AI-like the replies read is unverified.

## Limitations and follow-ups
- **Only the Reddit Agent uses it.** The Content and X agents don't yet, although the storage is ready for them.
- **Selection feedback waits for the digest**, about a minute (see Decisions).
- **Deleting an entry doesn't unlearn its lesson** until you click Rebuild, and Rebuild replaces hand edits.
- **The learnings have no revision history.** An overwrite can't be undone, unlike context documents.
- **The digest can drop or blur a lesson** when merging. The learnings are visible and editable for that reason.
- **A failed digest isn't retried automatically.** The entries stay pending and are still sent raw to the drafting prompt, and the next feedback or a Rebuild tries again.
- **`reddit/score/v4.md`** should be deleted once no pending batch uses it.

## Where to look
| What | Where |
|---|---|
| Recording feedback, prompt variables | `backend/apps/feedback/services.py` (`record`, `learning_variables`, `selection_learnings`) |
| The digest | `backend/apps/feedback/pipeline.py` (`digest_feedback`), `backend/apps/feedback/tasks.py` |
| Endpoints | `backend/apps/feedback/views.py`, `backend/apps/feedback/urls.py` |
| Remember on regenerate | `backend/apps/inbox/views.py` (`RegenerateView`) |
| Drafting and scoring inputs | `backend/apps/reddit/pipeline.py` (`comment_variables`, `post_variables`, `comment_content`) |
| Prompts | `backend/prompts/feedback/digest/v1.md`, `backend/prompts/reddit/comment/v4.md`, `backend/prompts/reddit/score/v5.md` |
| Output schemas | `backend/llm/schemas.py` (`RedditComment`, `FeedbackDigest`) |
| UI | `frontend/src/features/inbox/FeedbackCard.tsx`, `frontend/src/features/agents/LearningsCard.tsx` |

## History
- 2026-10-01 · #4 · Shipped: feedback and learnings, custom instructions, the human-voice comment prompt and the poster read. The security scan added escaping of third-party text, the 409 on rebuild and the tenancy tests.
- 2026-10-01 · #5 · Python code standards applied to this code (type hints and docstrings, no behaviour change). It merged into #4's branch instead of `main`, so #11 brings it to `main`.
