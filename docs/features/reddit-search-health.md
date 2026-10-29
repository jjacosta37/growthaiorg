---
title: Reddit search health
status: shipped
prd:
prs: [23]
updated: 2026-10-29
---
# Reddit search health

The Reddit search now stays under Reddit's search-length limit. Every search also checks its own yield against recent runs, so a search that keeps finding nothing is reported as a failure instead of passing as a quiet day.

## Summary
Reddit search returns no results, and no error, when a query is longer than about 256 characters. Our adapter grouped keywords into queries of up to 400 characters, so many keywords were never really searched. After "Suggest more" lengthened the keyword list, every query went over the limit and every run came back empty while still reporting success. Keywords are now split into queries of at most 230 characters. Each search also records how many posts matched each keyword. Two checks then compare the search with the project's earlier ones: several empty searches in a row, or most keywords matching nothing over several searches, is reported as an error that files a Sentry issue.

## Why
On 2026-10-29 every Reddit run returned "0 results, 0 usable" and finished as "No new posts since the last scan". The Apify actor runs succeeded, the run succeeded, and nothing anywhere said the search was broken. An investigation with live Apify runs found the cause:

| Query | Characters | Posts |
|---|---|---|
| 16 short keywords | 148 | 5 |
| 10 keywords | 238 | 5 |
| 11 to 16 keywords | 293 to 394 | 0 |

The limit is the query's length, not the number of keywords, and the actor's new build that day was not the cause: both the old and the new build returned the same results. Looking back, the problem was older than the outage. Each subreddit had a long query (about 390 characters) and a short one, and only the short one ever matched. Most keywords had silently found nothing for weeks, and per-subreddit totals hid it because the short query still produced posts.

## How it behaves
- **Searches cover every keyword again.** Keywords are OR-joined into queries of at most 230 characters, so a project with many keywords gets more queries per subreddit (for example about 4 instead of 2). It's still one Apify run per search, so one start fee. The cost per result is still capped by `APIFY_REDDIT_MAX_ITEMS`.
- **Per-keyword counts in the run log.** The "Found N posts, M new" event and the run's stats carry `by_keyword`: for each configured keyword, how many returned posts match it, with an explicit 0.
- **Empty streak → error.** When a search finds no posts at all and the two previous searches of the same kind (Reddit Agent runs, or Content Agent topic research) also found none, the run logs "The last 3 searches found no posts at all. The search is probably failing, not just quiet". The run finishes as **partial** and a Sentry issue is filed. One or two empty searches are normal and say nothing.
- **Dead keywords → warning, or error when most are dead.** When a keyword matched no posts in each of the last 5 searches, the run logs a warning such as "1 of 12 keywords matched no posts in the last 5 searches", with the keywords in the event's data. That's worth tuning, nothing more. When the dead keywords are more than half of those checked (and at least 2), the searches themselves are probably failing for them. The event is then an error, the run is partial, and Sentry gets an issue.
- **New keywords get a fair chance.** A keyword is judged only once it has been in all 5 searches. A keyword added since then is left out, and nothing is judged until 5 searches with per-keyword counts exist.
- **An empty search doesn't also flag every keyword.** When the search found nothing, only the streak check runs.

## Decisions
- **230 characters, not 256.** The live test found the cliff somewhere between 238 (matched) and 293 (nothing). 230 leaves a margin without testing the exact limit. Rejected: bisecting the exact limit, because the gain from a few more characters per query is negligible and the limit may move.
- **Count matches per keyword, not per query.** The actor's results don't say which search URL produced them, and the grouping into queries is the Apify adapter's own detail. Matching each post against each keyword in the pipeline works the same whatever the provider is, and tells the user which keywords to fix. Rejected: per-query counts, because they can't be attributed reliably and wouldn't mean anything to the user.
- **Count over every returned post, before the `max_posts` cut.** The adapter keeps only the newest `max_posts`, so counting only those would make a working keyword look dead whenever its matches were older. The search result carries the full list as `candidates`.
- **Approximate matching, judged over several runs.** Each word of a keyword must appear in the title or body as a substring ("contribution" matches "contributions"), and a quoted keyword must appear as an exact phrase. That's close to, but not the same as, Reddit's own matching. So one miss means nothing, and only 5 misses in a row are flagged.
- **Errors only for patterns that mean "broken".** A quiet subreddit or a niche keyword is normal, so a single dead keyword is a warning in the run log. An empty streak, or most keywords dead at once, is the shape of a provider or query failure, so it pages through Sentry. Rejected: a Sentry issue for every empty run, which would fire on legitimately quiet days.
- **One exception type for both alerts.** `SearchYieldError` is passed to `reporter.error(exc=...)`, so Sentry groups by its type and fixed message rather than by message text that names changing counts.

## How it works
### Flow
1. `fetch` (`apps/reddit/pipeline.py`) runs the search through the `RedditSource` adapter, as before.
2. `keyword_hits` counts matches per keyword over `result.candidates`, using `keyword_matches`.
3. `previous_searches` reads the stats of this project's earlier runs of the same kind that searched (those with `fetched` in their stats), newest first, up to 4.
4. `fetched` and `by_keyword` are saved on the run's stats, and the fetch event is written.
5. `check_search_yield` applies the two checks and reports through `reporter.error` or `reporter.warning`.

### Data model
No new models. `AgentRun.stats` of a run that searched gains `by_keyword: {keyword: count}`, next to `fetched` and `by_subreddit`. `RedditSearchResult` (`providers/reddit/base.py`) gains `candidates`: every distinct post before the `max_posts` cut. `ApifyRedditSource` and `FakeRedditSource` both fill it.

### Configuration
Module constants, not settings:
- `MAX_QUERY_CHARS = 230` in `providers/reddit/apify.py`
- `ZERO_YIELD_RUNS = 3` and `KEYWORD_HISTORY_RUNS = 5` in `apps/reddit/pipeline.py`

## Observability
This feature is the observability. An empty streak or mostly dead keywords shows up as an error event in the run log, a **partial** run, and a Sentry issue titled `SearchYieldError` and tagged with the run, the kind and the project. A few dead keywords show up as a warning event with `dead_keywords` in its data. `by_keyword` is on every search's fetch event and stats.

## Testing
- `tests/test_reddit_adapter.py`: queries stay within `MAX_QUERY_CHARS`, and nothing is dropped when keywords are split.
- `tests/test_reddit_pipeline.py`:
  - per-keyword counts include posts cut by `max_posts`, with phrase and multi-word matching
  - 3 empty searches in a row give a partial run and one `SearchYieldError` sent to Sentry
  - a single empty search is not an error
  - one dead keyword is a warning
  - most keywords dead is an error
  - nothing is judged on a short history
- Checked by hand with live Apify runs on 2026-10-29: the query-length table above, and both actor builds returning the same results.

## Limitations and follow-ups
- A single keyword longer than 230 characters still gets a query of its own and still matches nothing. The dead-keyword warning would show it.
- Keyword matching is an approximation of Reddit's. A keyword Reddit matches only through stemming that substring matching misses could be flagged wrongly, though only after 5 searches.
- The Apify actor build isn't pinned, so an upstream change still reaches production unannounced. Pinning it, with a live check before upgrading, was discussed and left for later.

## Where to look
| What | Where |
|---|---|
| Query length limit | `backend/providers/reddit/apify.py` (`MAX_QUERY_CHARS`, `keyword_queries`) |
| Candidates before the cut | `backend/providers/reddit/base.py` (`RedditSearchResult.candidates`) |
| Per-keyword counts | `backend/apps/reddit/pipeline.py` (`keyword_hits`, `keyword_matches`) |
| Yield checks | `backend/apps/reddit/pipeline.py` (`check_search_yield`, `previous_searches`, `SearchYieldError`) |
| Tests | `backend/tests/test_reddit_pipeline.py`, `backend/tests/test_reddit_adapter.py` |

## History
- 2026-10-29 · #23 · first version
