/** Public landing page — from the Claude Design handoff "Helmly - Landing Page.dc.html".
 *  Its only job is waitlist signups; copy is final and used verbatim. */

import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { HelmMark } from "../../components/brand";
import { applyTheme, readTheme } from "../../lib/theme";
import { WaitlistForm } from "./WaitlistForm";
import {
  ContentIcon,
  InstagramIcon,
  LinkIcon,
  PlusIcon,
  RedditIcon,
  SeoIcon,
  TikTokIcon,
  XIcon,
} from "./icons";
import "./landing.css";

const HERO_INPUT_ID = "waitlist-hero-email";

const CONTEXT_DOCS = [
  "product-information",
  "target-audience",
  "brand-voice",
  "competitor-analysis",
  "content-strategy",
  "compliance-guidelines",
];

type Channel = "reddit" | "x" | "content";

const MOCK_ROWS: { channel: Channel; title: string; score?: number }[] = [
  { channel: "reddit", title: "How do you keep deadlines…", score: 85 },
  { channel: "x", title: "How we run a 20-min retro" },
  { channel: "content", title: "Running Retrospectives…" },
  { channel: "reddit", title: "Best PM tool for remote…", score: 78 },
  { channel: "x", title: "Small teams don't miss…" },
  { channel: "reddit", title: "What do you use to track…", score: 52 },
];

const AGENTS: { name: string; blurb: string; icon: ReactNode; live?: Channel }[] = [
  {
    name: "Reddit Agent",
    blurb: "Finds relevant threads, scores them 0–100, and drafts a helpful comment — not a pitch.",
    icon: <RedditIcon />,
    live: "reddit",
  },
  {
    name: "Content Agent",
    blurb: "Proposes blog topics from your context and drafts full SEO posts, ready to review.",
    icon: <ContentIcon />,
    live: "content",
  },
  {
    name: "X Agent",
    blurb: "Drafts single posts and short threads in your voice, formatted the way you'd actually post.",
    icon: <XIcon />,
    live: "x",
  },
  {
    name: "SEO Agent",
    blurb: "Audits your pages, finds keyword gaps, and suggests fixes that help you rank.",
    icon: <SeoIcon />,
  },
  {
    name: "Instagram Agent",
    blurb: "Plans posts and captions in your brand voice, matched to your content calendar.",
    icon: <InstagramIcon />,
  },
  {
    name: "TikTok Agent",
    blurb: "Writes short-video ideas, hooks, and scripts built around what your audience watches.",
    icon: <TikTokIcon />,
  },
  {
    name: "Link Building Agent",
    blurb: "Finds sites worth a backlink and drafts outreach that earns a reply.",
    icon: <LinkIcon />,
  },
];

function scrollTo(id: string, focus?: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
}

function scoreTone(score: number) {
  return score >= 70 ? "high" : "mid";
}

function ProductMock() {
  return (
    <div className="landing-mock" aria-hidden>
      <div className="landing-mock__sidebar">
        <div className="landing-mock__project">Acme</div>
        <div className="landing-mock__nav landing-mock__nav--active">Inbox · 12</div>
        <div className="landing-mock__nav">Reddit</div>
        <div className="landing-mock__nav">Content</div>
        <div className="landing-mock__nav">X</div>
      </div>
      <div className="landing-mock__list">
        {MOCK_ROWS.map((row, i) => (
          <div key={i} className={`landing-mock__row${i === 0 ? " landing-mock__row--active" : ""}`}>
            <span className={`landing-dot landing-dot--${row.channel}`} />
            <span className="landing-mock__title">{row.title}</span>
            {row.score !== undefined && (
              <span className={`landing-score landing-score--${scoreTone(row.score)}`}>{row.score}</span>
            )}
          </div>
        ))}
      </div>
      <div className="landing-mock__detail">
        <div className="landing-mock__badges">
          <span className="landing-mock__channel">
            <span className="landing-dot landing-dot--reddit" />
            Reddit
          </span>
          <span className="landing-score landing-score--high landing-score--lg">85</span>
        </div>
        <div className="landing-mock__question">How do you keep deadlines from slipping on a 5-person team?</div>
        <div className="landing-mock__draft">
          Small teams don't miss deadlines because they're lazy — they miss them because nobody actually
          owns the date…
        </div>
      </div>
    </div>
  );
}

function Step({ label, title, sub, subWidth, children }: {
  label: string;
  title: string;
  sub: string;
  subWidth: number;
  children?: ReactNode;
}) {
  return (
    <section className="landing-step">
      <div className="landing-step__label">{label}</div>
      <h2 className="landing-h2">{title}</h2>
      <p className="landing-step__sub" style={{ maxWidth: subWidth }}>
        {sub}
      </p>
      {children}
    </section>
  );
}

export default function LandingPage() {
  // The page is designed for the light theme only; put the viewer's choice back on the way out.
  useEffect(() => {
    applyTheme("light");
    return () => applyTheme(readTheme());
  }, []);

  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-brand">
          <HelmMark size={22} />
          <span className="landing-brand__word">Helmly</span>
        </div>
        <nav className="landing-nav__links">
          <a href="#how" className="landing-nav__anchor" onClick={(e) => { e.preventDefault(); scrollTo("how"); }}>
            How it works
          </a>
          <a
            href="#compliance"
            className="landing-nav__anchor"
            onClick={(e) => { e.preventDefault(); scrollTo("compliance"); }}
          >
            Compliance
          </a>
          <Link to="/login" className="landing-nav__login">
            Log in
          </Link>
          <button type="button" className="landing-btn" onClick={() => scrollTo("top", HERO_INPUT_ID)}>
            Join waitlist
          </button>
        </nav>
      </header>

      <main>
        <section id="top" className="landing-hero">
          <div className="landing-pill">An AI marketing team for founders who don't have one yet</div>
          <h1 className="landing-h1">Your AI marketing team, always on</h1>
          <p className="landing-hero__sub">
            Paste your website URL. Helmly reads your public pages to learn your business, then works around the
            clock across every growth channel — researching, writing, and finding opportunities — so solo founders
            and small teams can grow without a marketing hire.
          </p>
          <WaitlistForm source="hero" inputId={HERO_INPUT_ID} note="Not open yet — we'll email you when it is." />
        </section>

        <div className="landing-mock-wrap">
          <ProductMock />
        </div>

        <div id="how" className="landing-how">
          <Step
            label="Step 1 — Research"
            title="Like any good hire, it learns your business first"
            sub="Six context documents, built once from your website and kept up to date. Every agent drafts from the same documents, so nothing drifts off-message."
            subWidth={520}
          >
            <div className="landing-chips">
              {CONTEXT_DOCS.map((doc) => (
                <span key={doc} className="landing-chip">
                  {doc}
                </span>
              ))}
            </div>
          </Step>

          <Step
            label="Step 2 — Draft"
            title="A specialist for every channel, working every day"
            sub="Each one works on a schedule. Channel by channel, you choose: review drafts before they go out, or let Helmly publish on its own. More channels are on the way."
            subWidth={480}
          >
            <div className="landing-agents">
              {AGENTS.map((agent) => (
                <div
                  key={agent.name}
                  className={`landing-agent ${agent.live ? `landing-agent--${agent.live}` : "landing-agent--next"}`}
                >
                  <div className="landing-agent__head">
                    {agent.icon}
                    {!agent.live && <span className="landing-agent__next">Up next</span>}
                  </div>
                  <div className="landing-agent__name">{agent.name}</div>
                  <div className="landing-agent__blurb">{agent.blurb}</div>
                </div>
              ))}
              <div className="landing-agent landing-agent--more">
                <div className="landing-agent__head">
                  <PlusIcon />
                </div>
                <div className="landing-agent__name">More to come</div>
                <div className="landing-agent__blurb">New specialists join the team as Helmly grows.</div>
              </div>
            </div>
          </Step>

          <Step
            label="Step 3 — Grow"
            title="You set the direction, Helmly does the work"
            sub="Adjust guidance, tune each agent, and see what gets posted and what works, all in one place."
            subWidth={480}
          />
        </div>

        <section id="compliance" className="landing-compliance">
          <div className="landing-compliance__inner">
            <div className="landing-compliance__copy">
              <h2 className="landing-h2 landing-h2--compliance">
                Compliance rules for your industry, checked on every draft
              </h2>
              <p>
                General, financial services, or health &amp; wellness — pick the rule pack that fits, or write your
                own. Helmly flags what needs your attention, like a missing disclosure. Flagged drafts are held for
                your review.
              </p>
            </div>
            <div className="landing-flag" aria-label="Example compliance flag">
              <div className="landing-flag__badge">⚠ missing_disclosure</div>
              <div className="landing-flag__excerpt">"Try Acme, it tracks this for you."</div>
              <div className="landing-flag__why">Mentions Acme without the disclosure line.</div>
            </div>
          </div>
        </section>

        <section className="landing-cta">
          <h2 className="landing-h2">Put your growth on autopilot</h2>
          <p className="landing-cta__sub">Join the waitlist — we'll email you when Helmly is ready for your website.</p>
          <WaitlistForm source="cta" inputId="waitlist-cta-email" />
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-brand landing-brand--muted">
          <HelmMark size={16} />
          <span>Helmly</span>
        </div>
        <div>© 2026 Helmly</div>
      </footer>
    </div>
  );
}
