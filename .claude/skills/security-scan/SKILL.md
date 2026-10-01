---
name: security-scan
description: Scan Luka's pending changes for security vulnerabilities against docs/security-patterns.md, fix every CRITICAL and HIGH finding, and mark HEAD as scanned so the push/PR gate opens. Run before every push or PR. Args - --all, --staged, --base REF, --backend, --frontend.
---

# Security scan

Check the changes on this branch against `docs/security-patterns.md` and fix what matters. A `PreToolUse` hook (`.claude/hooks/security-gate.sh`) blocks `git push` and PR creation until this skill has marked the current HEAD.

## Arguments

$ARGUMENTS

| Flag | Meaning |
|---|---|
| (none) | Scan the diff from `git merge-base HEAD origin/main` to the working tree. This is the default before a PR. |
| `--base REF` | Diff against `REF` instead of `origin/main` |
| `--staged` | Only staged changes |
| `--all` | Whole repo, not a diff. It audits against §14 as well: report baseline items but don't fix them unless asked. It does not mark HEAD. |
| `--backend` / `--frontend` | Limit to `backend/` or `frontend/` (combinable with the above) |

## Steps

### 1. Scope
- Run `git fetch origin main --quiet` if the network allows it, then find the base: `git merge-base HEAD origin/main`.
- Collect the changed files (`git diff --name-only <base>`, including uncommitted work) and the full diff.
- **Nothing to scan?** If the changes touch only `docs/` or root `*.md` files, or nothing at all, skip to step 7 and report "no code changes". `backend/prompts/**/*.md` and `.claude/**` are **not** docs; scan them.

### 2. Load the rules
Read all of `docs/security-patterns.md`, especially:
- the public-view table (§2)
- the model-output allowlist (§7)
- the severity rubric (§13)
- the known-concerns register (§14)
- the checklist

For each changed file, read the whole file and not just the hunk. A missing `project=` filter is invisible in a diff that only shows the new line.

### 3. Mechanical sweep
Run these over the files in scope and note every hit to check in step 4. Leave out `backend/tests/` and `migrations/`, except for the `pytest` run.

```bash
# auth / tenancy
rg -n "AllowAny|authentication_classes|permission_classes|csrf_exempt" <files>
rg -n "objects\.(get|filter|exclude)\(|get_object_or_404\(" <backend files>   # each hit: scoped by project/owner?
rg -n "project_id|\"project\"|'project'|owner" <serializers>                   # client-settable tenancy fields?
# dangerous calls
rg -n "yaml\.load\(|unsafe_load|pickle|marshal|eval\(|exec\(|subprocess|os\.system|shell=True|\.raw\(|\.extra\(|RawSQL|cursor\.execute|mark_safe|format_html|from_string|Template\(" <files>
# outbound HTTP / SSRF
rg -n "httpx|requests|urllib\.request|aiohttp|apify" <files>                   # outside providers/ or llm/?
rg -n "follow_redirects|\.get\(.*url|sitemap" <crawler files>
# frontend
rg -n "dangerouslySetInnerHTML|innerHTML|rehype-raw|urlTransform|window\.open|href=\{" <frontend files>
# secrets / config
rg -n "(sk-ant-|apify_api_|api[_-]?key\s*=\s*['\"][^'\"]{8,}|password\s*=\s*['\"])" <files>
rg -n "CORS|DEBUG\s*=\s*True|ALLOWED_HOSTS|SESSION_COOKIE|CSRF_COOKIE|SECURE_" <settings files>
# LLM effects
rg -n "tools:|VALID_TOOLS|web_search" <files>
```

Then run the mechanical tests. Try Docker first and fall back to a local run:

```bash
docker compose run --rm web pytest tests/test_security_patterns.py tests/test_tenancy.py -q \
  || (cd backend && pytest tests/test_security_patterns.py tests/test_tenancy.py -q)
```

A failure in either test is a finding at the severity the test names. If neither command can run, say so in the summary rather than skipping silently.

### 4. Independent review (subagent)
Launch **one** `general-purpose` subagent to do the review. It starts with a fresh context, so the session that wrote the code isn't the only one grading it. Give it:
- the scope (base, list of changed files) and the full diff
- the full text of `docs/security-patterns.md`
- the mechanical sweep hits and any test failures from step 3
- these instructions:

> You are a security engineer reviewing a PR to Luka, a multi-tenant Django/DRF + Celery + React app that crawls websites and runs LLM pipelines. Review ONLY what this diff introduces or makes worse; items already in §14 of the patterns doc are out of scope unless the diff worsens them. For every changed file, read the whole file and trace data from its entry point: request → serializer → queryset; crawled page or provider response → prompt → model output → database or UI; URL → fetch.
>
> Focus on: cross-tenant access (every query on a project-scoped model must go through `current_project(request)` or `owner=request.user`; Celery tasks scope from `run.project`); authentication and CSRF; SSRF in anything that fetches; model output causing effects outside the §7 allowlist; XSS via raw HTML or non-http(s) URLs; secrets; dangerous calls from §9; tracebacks or content leaking into responses, logs or `RunEvent.data`; call multipliers without a server-side bound.
>
> For each finding give: `file:line`, severity per §13, category, a one-line description, a concrete exploit scenario (who the attacker is, what they send, what they get), a fix, and your confidence 1–10. Only report findings with a concrete attack path. No style notes, no generic hardening advice, and nothing about test files. Do not edit files.

### 5. Verify CRITICAL and HIGH findings (parallel subagents)
For each CRITICAL or HIGH finding, launch a `general-purpose` subagent. Launch them **all in one message** so they run in parallel. Each one gets the finding, the patterns doc and the exclusions below. It must confirm or reject the finding by reading the code, and return a confidence score from 1 to 10. **Drop anything below 8.** MEDIUM and LOW findings don't need verification; list them as they are.

> **False-positive exclusions.** Reject findings that are:
> - denial of service, resource exhaustion or rate-limit concerns, **except** unbounded LLM/Apify spend (§11), which is in scope
> - theoretical race conditions
> - outdated dependencies
> - issues only in tests
> - log spoofing
> - regex injection or ReDoS
> - issues in Markdown docs
> - a missing audit log
> - hardening "best practices" with no concrete exploit
>
> **Precedents:**
> - Environment variables and settings are trusted.
> - UUIDs are unguessable. Integer pks are **not**, so a pk lookup still needs scoping.
> - React/JSX output is safe unless it uses `dangerouslySetInnerHTML`, `rehype-raw`, or a data-driven `href`/`window.open`.
> - Client-side auth checks are not a security boundary; the server must enforce them.
> - SSRF that controls only the path is not a finding. Control of the host or scheme is.
> - "User or crawled content appears in a prompt" is **not** a finding on its own; it becomes one only when model output reaches an effect outside the §7 allowlist.
> - Logging URLs and ids is fine. Logging secrets, or content covered by the CLAUDE.md logging rules, is not.
> - A view listed in the §2 public table is public by design.

### 6. Fix CRITICAL and HIGH
For each confirmed CRITICAL or HIGH finding:
1. Fix it the way the patterns doc describes, and keep to CLAUDE.md conventions: platform-neutral, logging rules, prompt versioning.
2. Add a regression test in the same style as nearby tests. Use `test_tenancy.py` for scoping, `test_crawler.py` / `test_crawl_units.py` for SSRF, `test_security_patterns.py` for a new mechanical rule, and the app's own test file otherwise.
3. Run the full suite: `docker compose run --rm web pytest`, or `cd backend && pytest`.
4. Check the fix: re-read the code path and confirm the exploit scenario no longer works.

If a finding **can't be fixed within this PR's scope**, for example because it needs a product or design decision, stop. Don't push, don't mark, and tell the user what the finding is and what the options are.

Don't fix MEDIUM or LOW findings unless the fix is small and local to code the PR already touches. Otherwise list them.

### 7. Keep the patterns doc true
In the same PR, update `docs/security-patterns.md` when the change:
- legitimately adds a public view (add it to §2 and to `PUBLIC_VIEWS` in the test)
- adds an outbound fetch (§6)
- adds a model-output effect (§7 allowlist)
- adds an LLM tool (§7)
- sends content to a new third party (§10)
- adds a call multiplier (§11)

When the user accepts a deferred MEDIUM finding, add it to §14. When a §14 item gets fixed, remove it.

### 8. Commit and mark
- Commit the fixes, tests and doc updates with a clear message.
- Confirm the working tree has no uncommitted tracked changes.
- Run `.claude/hooks/security-gate.sh --mark`.
- Skip the mark only for `--all` audits, or when step 6 stopped on an unfixable finding.

The mark covers exactly this HEAD. Any later commit, including one made after review feedback, needs a new scan before the next push.

### 9. Report
Write this section to `$(git rev-parse --git-path luka-security-summary.md)`, and print it for the user. It goes **in the PR description**; nothing is committed to the repo.

```markdown
## Security scan
Scope: `<base>..<head short sha>`, N files (backend: …, frontend: …)
Result: ✅ no open CRITICAL/HIGH  |  ⛔ blocked: <reason>

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 1 | 1 | 0 |
| MEDIUM | 2 | 0 | 2 |
| LOW | 0 | 0 | 0 |

**Fixed**
- HIGH `backend/apps/x/views.py:42`: <one line>. Fix: <one line>. Test: `tests/test_tenancy.py::test_…`

**Deferred (MEDIUM/LOW)**
- MEDIUM `path:line`: <one line>. Why deferred: <reason>

**Patterns doc**: <sections updated, or "no change">
**Mechanical checks**: test_security_patterns ✅, test_tenancy ✅ (or why they couldn't run)
```

When creating the PR, include this section verbatim in the body, e.g. `gh pr create --body-file <file>` with the rest of the description placed above it.
