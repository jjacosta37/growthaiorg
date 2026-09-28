/**
 * Stats: weekly drafts per agent, dismiss reasons and spend.
 * From "Luka - Stats.dc.html".
 *
 * Charts are hand-built CSS bars, as in the designs — no chart library. Every weekly
 * series in the payload is index-aligned to `weeks`.
 */

import { useState } from "react";

import { DetailPane } from "../../components/Shell";
import { EmptyState, ErrorState } from "../../components/feedback";
import { Segmented } from "../../components/primitives";
import { AGENT_LABEL, DISMISS_REASON_LABEL, money, percent, shortDate } from "../../lib/format";
import { useStats } from "../../lib/queries";
import { AGENT_TYPES, type AgentType, type StatsPayload } from "../../lib/types";
import "./stats.css";

const PERIODS = [
  { value: "4", label: "4 weeks" },
  { value: "8", label: "8 weeks" },
  { value: "12", label: "12 weeks" },
];

export default function StatsPage() {
  const [weeks, setWeeks] = useState("8");
  const stats = useStats(Number(weeks));

  if (stats.isError) {
    return (
      <DetailPane wide>
        <ErrorState title="Couldn't load stats" onRetry={() => void stats.refetch()} />
      </DetailPane>
    );
  }

  const data = stats.data;

  return (
    <DetailPane wide>
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">Stats</h1>
          <Segmented value={weeks} onChange={setWeeks} options={PERIODS} ariaLabel="Period" />
        </header>

        {!data ? (
          <EmptyState title="Loading…" />
        ) : (
          <>
            <DraftsChart data={data} />
            <AgentTotals data={data} />
            <DismissReasons data={data} />
            <Spend data={data} />
          </>
        )}
      </div>
    </DetailPane>
  );
}

/* ------------------------------------------------------- drafts per week */

function DraftsChart({ data }: { data: StatsPayload }) {
  // Stack the three agents' generated counts per week, split by outcome.
  const weekly = data.weeks.map((week, i) => {
    let posted = 0;
    let dismissed = 0;
    let generated = 0;
    for (const agent of AGENT_TYPES) {
      const series = data.drafts[agent];
      generated += series?.generated[i] ?? 0;
      posted += series?.posted[i] ?? 0;
      dismissed += series?.dismissed[i] ?? 0;
    }
    return { week, generated, posted, dismissed, pending: Math.max(0, generated - posted - dismissed) };
  });

  const max = Math.max(1, ...weekly.map((w) => w.generated));
  const empty = weekly.every((w) => w.generated === 0);

  return (
    <section className="card">
      <div className="card__header">
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="card__title">Weekly drafts</span>
          <span className="subtle">Generated, split by what you did with them</span>
        </div>
        <div className="legend">
          <span>
            <i className="legend__swatch legend__swatch--posted" /> Posted
          </span>
          <span>
            <i className="legend__swatch legend__swatch--pending" /> Pending
          </span>
          <span>
            <i className="legend__swatch legend__swatch--dismissed" /> Dismissed
          </span>
        </div>
      </div>
      <div className="card__body">
        {empty ? (
          <EmptyState title="No drafts in this period" />
        ) : (
          <div className="chart">
            {weekly.map((w) => (
              <div className="chart__col" key={w.week}>
                <div
                  className="chart__stack"
                  title={`${w.generated} generated · ${w.posted} posted · ${w.dismissed} dismissed`}
                >
                  <div
                    className="chart__bar chart__bar--dismissed"
                    style={{ height: `${(w.dismissed / max) * 100}%` }}
                  />
                  <div
                    className="chart__bar chart__bar--pending"
                    style={{ height: `${(w.pending / max) * 100}%` }}
                  />
                  <div
                    className="chart__bar chart__bar--posted"
                    style={{ height: `${(w.posted / max) * 100}%` }}
                  />
                </div>
                <span className="chart__label">{shortDate(w.week)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- totals */

function AgentTotals({ data }: { data: StatsPayload }) {
  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Per agent</span>
      </div>
      <div className="card__body" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Generated</th>
              <th>Posted</th>
              <th>Dismissed</th>
              <th>Pending</th>
              <th>Post rate</th>
            </tr>
          </thead>
          <tbody>
            {AGENT_TYPES.map((agent) => {
              const totals = data.totals[agent];
              if (!totals) return null;
              return (
                <tr key={agent}>
                  <td style={{ color: "var(--color-text)" }}>{AGENT_LABEL[agent]}</td>
                  <td>{totals.generated}</td>
                  <td>{totals.posted}</td>
                  <td>{totals.dismissed}</td>
                  <td>{totals.pending}</td>
                  <td className="table__mono">{percent(totals.post_rate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* -------------------------------------------------------- dismiss reasons */

function DismissReasons({ data }: { data: StatsPayload }) {
  const rows = AGENT_TYPES.map((agent) => ({
    agent,
    reasons: Object.entries(data.dismiss_reasons[agent] ?? {}).filter(([, n]) => n > 0),
  })).filter((row) => row.reasons.length);

  if (!rows.length) return null;

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Why drafts were dismissed</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
        {rows.map(({ agent, reasons }) => {
          const total = reasons.reduce((sum, [, n]) => sum + n, 0);
          return (
            <div key={agent} className="stack" style={{ gap: "var(--space-2)" }}>
              <span className="section-label">{AGENT_LABEL[agent as AgentType]}</span>
              {reasons.map(([reason, count]) => (
                <div key={reason} className="meter">
                  <span className="meter__label">
                    {DISMISS_REASON_LABEL[reason] ?? reason}
                  </span>
                  <span className="meter__track">
                    <span
                      className="meter__fill"
                      style={{ width: `${(count / total) * 100}%` }}
                    />
                  </span>
                  <span className="meter__value mono">{count}</span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- spend */

function Spend({ data }: { data: StatsPayload }) {
  const spend = data.spend;
  const max = Math.max(
    0.01,
    ...data.weeks.map((_, i) => (spend.llm_weekly[i] ?? 0) + (spend.apify_weekly[i] ?? 0)),
  );
  const perWeek = data.weeks.length || 1;

  return (
    <section className="card">
      <div className="card__header">
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="card__title">Spend</span>
          <span className="subtle">Model calls and data (Apify), weekly</span>
        </div>
        <div className="legend">
          <span>
            <i className="legend__swatch legend__swatch--llm" /> LLM
          </span>
          <span>
            <i className="legend__swatch legend__swatch--apify" /> Apify
          </span>
        </div>
      </div>

      <div className="card__body stack" style={{ gap: "var(--space-6)" }}>
        <div className="tiles">
          <Tile label="Total this period" value={money(spend.total)} />
          <Tile label="Avg / week LLM" value={money(spend.llm_total / perWeek)} />
          <Tile label="Avg / week Apify" value={money(spend.apify_total / perWeek)} />
          <Tile label="Cache hit rate" value={percent(spend.cache_hit_rate)} />
        </div>

        <div className="chart">
          {data.weeks.map((week, i) => {
            const llm = spend.llm_weekly[i] ?? 0;
            const apify = spend.apify_weekly[i] ?? 0;
            return (
              <div className="chart__col" key={week}>
                <div
                  className="chart__stack"
                  title={`${money(llm)} LLM · ${money(apify)} Apify`}
                >
                  <div
                    className="chart__bar chart__bar--apify"
                    style={{ height: `${(apify / max) * 100}%` }}
                  />
                  <div
                    className="chart__bar chart__bar--llm"
                    style={{ height: `${(llm / max) * 100}%` }}
                  />
                </div>
                <span className="chart__label">{shortDate(week)}</span>
              </div>
            );
          })}
        </div>

        <div className="breakdowns">
          <Breakdown title="LLM spend by agent" entries={spend.llm_by_agent} />
          <Breakdown title="LLM spend by model" entries={spend.llm_by_model} />
        </div>

        <span className="subtle">
          {spend.llm_calls} model calls
          {spend.llm_failed_calls > 0 &&
            ` · ${spend.llm_failed_calls} failed and were retried automatically`}
          .
        </span>
      </div>
    </section>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <span className="tile__label">{label}</span>
      <span className="tile__value">{value}</span>
    </div>
  );
}

function Breakdown({ title, entries }: { title: string; entries: Record<string, number> }) {
  const rows = Object.entries(entries)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);

  if (!rows.length) return null;
  const total = rows.reduce((sum, [, value]) => sum + value, 0);

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <span className="section-label">{title}</span>
      {rows.map(([key, value]) => (
        <div key={key} className="meter">
          <span className="meter__label">{key}</span>
          <span className="meter__track">
            <span className="meter__fill" style={{ width: `${(value / total) * 100}%` }} />
          </span>
          <span className="meter__value mono">{money(value)}</span>
        </div>
      ))}
    </div>
  );
}
