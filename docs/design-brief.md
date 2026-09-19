# Design brief: Sift, an AI growth assistant

The prompt used to create Sift's brand, design tokens, components and screens in Claude Design. Phase 2 (frontend) builds against the token names and screens listed here.

## What Sift is
Sift is a web app for founders and small marketing teams. You give it your company's website, and it:
1. crawls the site and writes "context documents" about the business (product, audience, brand voice, competitors, content strategy, compliance rules), and
2. runs three AI "agents" on a schedule that draft marketing content into an inbox:
   - **Reddit Agent:** finds relevant Reddit threads, scores their relevance (0–100) and drafts helpful comments
   - **Content Agent:** proposes blog topics and drafts full SEO blog posts
   - **X Agent:** drafts single posts and short threads for X (Twitter)

Nothing is ever posted automatically. The user reviews each draft, edits it if needed, copies it, posts it themselves, and marks it posted. Sift is a **triage tool**: the core loop is "open the inbox, go through drafts fast, act on each one". Think of an email client like Superhuman or Linear's inbox, not a dashboard.

The product name is **Sift**: sifting signal from noise. It should feel calm, precise, fast and trustworthy, with no hype. The user is a busy founder who wants to get through the inbox in minutes.

Use a fictional company in every example: **Acme**, a project-management tool for small teams (acme.example). Don't use any real company names.

## Deliverables

### 1. Brand guide
- Wordmark or logo for "Sift", plus a small square app icon (favicon size)
- Colour palette, typography (UI font plus a monospace font for code and keyboard hints) and voice notes for UI copy (short, plain, calm)

### 2. Design tokens: light and dark themes
Please deliver the tokens as a CSS file of custom properties, **using exactly these names** so the file drops into the code as-is. Add more if needed, but keep these:

```
/* Colour */
--color-bg, --color-surface, --color-surface-raised, --color-surface-sunken
--color-border, --color-border-strong
--color-text, --color-text-muted, --color-text-subtle, --color-text-inverse
--color-accent, --color-accent-hover, --color-accent-subtle, --color-on-accent
--color-success, --color-success-subtle
--color-warning, --color-warning-subtle
--color-danger, --color-danger-subtle
--color-focus-ring
--color-channel-reddit, --color-channel-x, --color-channel-content   /* channel identity; should work as small dots and badges */
--color-score-high, --color-score-mid, --color-score-low              /* relevance score pill */

/* Type */
--font-sans, --font-mono
--text-xs, --text-sm, --text-base, --text-lg, --text-xl, --text-2xl
--leading-tight, --leading-normal, --leading-relaxed
--weight-regular, --weight-medium, --weight-semibold

/* Space, shape, depth, motion */
--space-1 … --space-8        /* 4px scale */
--radius-sm, --radius-md, --radius-lg, --radius-full
--shadow-sm, --shadow-md, --shadow-lg
--duration-fast, --duration-normal, --ease-standard
```
Dark mode is selected with `[data-theme="dark"]` and also follows the system setting. Please check contrast (at least WCAG AA) in both themes.

### 3. Component library (every state: default, hover, focus, active, disabled, loading)
- Buttons: primary, secondary, ghost, danger; icon buttons; a button with a keyboard hint (for example "Copy & open  C")
- Keyboard key chip (`kbd`) for shortcut hints
- Text input, textarea, select, toggle, slider (relevance threshold 0–100), segmented control
- **Chip input** (add and remove chips by typing and pressing Enter), used for subreddits, keywords, competitors and blog keywords
- Badges: channel badge (Reddit / X / Blog), status badge (new / posted / dismissed), **relevance score pill** (for example 85, coloured by range), **compliance flag badge** (warning style, for example "missing_disclosure")
- Run status indicator: queued, running (animated), waiting for batch, succeeded, partial, failed
- List row (the inbox item; see below), empty state, error state, skeleton loaders
- Toast, confirm dialog, dropdown menu, popover, tabs, tooltip
- Markdown editor with an edit/preview toggle
- Progress timeline or log (a vertical list of steps with icons for info, success, warning and error)
- A character counter that turns warning and then danger colours near and over the limit (for example "243 / 280")

### 4. Screens
Desktop-first (1280–1440px wide, minimum 1024px). Mobile isn't needed.

**A. Login.** Username and password, and an error state. Single user, so no signup.

**B. Onboarding (first run)**
1. "Enter your website URL", with an optional product name
2. A live progress view that streams steps as they happen, for example:
   "Reading robots.txt and sitemap → Found 24 pages → Crawled 24 pages → Rendering 4 JavaScript pages → Identified Acme; using General content rules → Writing Product Information ✓ → Writing Target Audience… → Writing Brand Voice… → Competitor Analysis (researching the web)… → Content Strategy ✓ → Suggested 8 subreddits and 15 keywords ✓ → Context is ready"
3. Warning state: "Only 2 readable pages found" (the documents will be thin; suggest editing them)
4. Failure state: "No readable pages found". It should end on the Context page.

**C. App shell: three panes** (sidebar | item list | detail)
- **Sidebar:**
  - project name at the top (a switcher, for later)
  - Inbox with an unread count
  - Agents: Reddit, Content and X, each with a "ready" count
  - Context, Stats, Settings
  - pinned at the bottom, a **live status line** showing background activity, for example "Reddit Agent scanning r/projectmanagement +6 more…", "Scoring 10 posts in a batch (usually a few minutes)", or nothing when idle
- **Item list:**
  - filters for agent (all / Reddit / X / Blog) and status (new / posted / dismissed), and sort (newest / highest score)
  - each row shows the channel badge, a title, the relevance score (Reddit only), a compliance flag count if any, age ("2h") and an unread dot
  - selected, unread and read states
  - empty state: "All caught up"
- **Keyboard:** j/k to move through items, c copy & open, e edit, r regenerate, d dismiss. Hints should be visible but quiet, for example in a footer or next to the buttons.

**D. Detail pane: one variant per channel.** Each shows the draft as the real thing it will become.
1. **Reddit comment**
   - The source thread: subreddit, title, a body excerpt (expandable), upvotes, comment count and age, with a link to the thread
   - Relevance score pill with a one-line reason, for example "85 · Clear, general question about deadline tracking from the target audience"
   - The drafted comment in an editable comment box styled like Reddit (about 60–180 words)
2. **X post / thread**
   - Styled like a real X post (avatar, name, handle placeholder), with a live character counter per post (for example 243 / 280)
   - Threads show 3–5 stacked, connected posts, each editable, with an over-limit state
   - Format label (insight, how-to, question, observation, myth, thread, behind the scenes)
3. **Blog post**
   - The article rendered as formatted reading (about 1,500 words, with H2/H3 headings, lists and a closing italic disclaimer)
   - A **side panel** with title (60-character guide), meta description (155/160 counter), slug, keywords as chips, and the topic's angle
   - A "Copy as markdown" action

Shared across all three:
- **Compliance flags** banner or list: rule name, the quoted excerpt, a one-line explanation, and a way to jump to the excerpt. Warnings only; they never block.
- **Actions bar:**
  - **Copy & open** (primary)
  - **Regenerate** with a nudge menu: Shorter / More casual / Don't mention the product / Custom instruction…
  - **Mark as posted** (optional posted URL)
  - **Dismiss**, with a reason picker: not relevant, already answered well, too promotional, other (plus a note)
- **Regenerating** state (in progress, then shows the new version)
- **Version history:** a list of versions (AI original, your edit, regenerated with "shorter"…) that lets you view any of them
- **"Did you post it?" prompt**, shown when the user returns to the tab after "Copy & open": Yes, mark posted / Not yet
- Posted and dismissed read-only states, with Restore

**E. Agent pages** (Reddit, Content, X share a layout)
- **Status header:**
  - enabled toggle, last run (time and status), next run, and the last error if it failed
  - **Run now** button, with a running state
- **Config:**
  - Reddit: subreddits (chips), keywords (chips), relevance threshold slider (default 70), posts per scan, time window (hour / day / week)
  - Content: topics per run, drafts per run, target words, standing guidance
  - X: formats (multi-select chips), posts per run, max thread length, character limit (280, or more for Premium), standing guidance
  - A schedule editor in plain words ("Every 4 hours", "Weekdays at 2pm") rather than raw cron, with an advanced cron field
- **Run history:** a table of time, trigger (scheduled / manual), status, key numbers (for example "10 found · 3 scored ≥ 70 · 3 drafted") and cost. Clicking a row opens its progress log.
- **Reddit only, the skipped list:** scanned posts that weren't drafted, sorted by score, with the reason. It exists to tune the threshold (for example "12 posts scored 60–69 this week").
- **Content only, the topic backlog:** proposed / drafted / rejected topics, each with its angle and keywords; a "Request a topic" form (title, angle, keywords, "draft now"), and draft or reject actions on each topic

**F. Context page**
- Product name and a two-sentence summary
- Competitors as editable chips (name and URL)
- The six documents (Product Information, Target Audience, Brand Voice, Competitor Analysis, Content Strategy, Compliance Guidelines) as a list or tabs, each with source (AI / edited by you / from policy), last updated, **Regenerate** and **Revision history**
- The markdown editor, with edit/preview modes
- **Re-crawl site** (with "overwrite my edits?" confirmation) and a crawled-pages list (URL, title, size)

**G. Settings: content policy.** This is important: it's how Sift stays safe across industries.
- Industry pack selector: General / Financial services / Health & wellness, each with a short description. Switching packs shows a preview and asks for confirmation.
- Rules list, editable: each rule has an id, title and description, and you can add, edit and remove rules. Also: "Posts are written by the: [founder]", the disclosure line with a live preview ("(Disclosure: I'm the founder of Acme.)"), and the blog disclaimer (optional)
- Account section (change password, sign out) and theme (light / dark / system)

**H. Stats page**
- Period selector (4 / 8 / 12 weeks)
- Weekly drafts per agent: generated vs posted vs dismissed (chart), plus per-agent totals and "post rate"
- Dismiss reasons per agent
- Spend: weekly LLM and Apify (stacked), totals, LLM spend by agent and by model, cache hit rate, failed calls

**I. Global states**
- Loading skeletons for the list and detail panes
- Error banner (API unreachable)
- Toasts (copied, marked posted, regeneration started)
- Failed agent run (in the agent header and the status line)

## Sample data for the mockups (realistic lengths)
- Reddit thread: r/projectmanagement, "How do you keep deadlines from slipping on a 5-person team?", 23 upvotes, 14 comments, 3h ago. Score 85, reason "Clear, general question about deadline tracking from the target audience". A drafted comment of about 150 words.
- X post (insight): "Small teams don't miss deadlines because they're lazy. They miss them because nobody owns the date. Give every deadline exactly one name." (≈140 characters)
- X thread (4 posts) on "How we run a 20-minute retro"
- Blog: "Running Retrospectives, Step by Step". Meta: "Learn how to run a 20-minute retrospective your team will actually look forward to." Slug `running-retrospectives`, keywords `sprint retrospective`, `retro meeting`.
- Compliance flag: `missing_disclosure`, excerpt "Try Acme, it tracks this for you.", explanation "Mentions Acme without the disclosure: (Disclosure: I'm the founder of Acme.)"
- Stats: about 25 drafts a week, 40% posted, spend about $4.80/week LLM plus $0.30/week Apify, cache hit rate 77%

## Style direction
- Calm, dense and readable. Content is the hero, not chrome. Generous line length for reading, compact list rows for scanning.
- Clear hierarchy through type weight and spacing rather than heavy colour. Colour signals meaning (channel, score, status, warnings).
- The three channels should be instantly recognizable without imitating their brands too closely.
- Everything reachable by keyboard, with visible focus states.
