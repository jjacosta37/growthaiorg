/** Channel, status, score and compliance badges, plus the run status indicator. */

import { CHANNEL_LABEL, RUN_STATUS_LABEL, ruleLabel } from "../lib/format";
import type { AgentType, DraftStatus, RunStatus } from "../lib/types";
import { cx } from "./primitives";

export function ChannelBadge({ channel }: { channel: AgentType }) {
  return (
    <span className={`badge badge--channel-${channel}`}>
      <span className="badge__dot" aria-hidden />
      {CHANNEL_LABEL[channel]}
    </span>
  );
}

/** The small colour dot on its own, for the sidebar's agent list. */
export function ChannelDot({ channel }: { channel: AgentType }) {
  return (
    <span
      aria-hidden
      style={{
        width: 6,
        height: 6,
        borderRadius: "var(--radius-full)",
        background: `var(--color-channel-${channel})`,
        flexShrink: 0,
      }}
    />
  );
}

export function StatusBadge({ status }: { status: DraftStatus }) {
  const label = status === "new" ? "New" : status === "posted" ? "Posted" : "Dismissed";
  return <span className={`badge badge--status-${status}`}>{label}</span>;
}

/**
 * The relevance score pill. The three bands match --color-score-high/mid/low; the
 * thresholds mirror how the designs colour 85 (high), 65 (mid) and below (low).
 */
export function ScorePill({ score }: { score: number }) {
  const band = score >= 70 ? "high" : score >= 50 ? "mid" : "low";
  return (
    <span className={`score score--${band}`} title={`Relevance ${score}`}>
      {score}
    </span>
  );
}

export function ComplianceFlagBadge({ rule }: { rule: string }) {
  return (
    <span className="flag">
      <span aria-hidden>⚠</span>
      {ruleLabel(rule)}
    </span>
  );
}

/** The flag count shown on an inbox row. */
export function FlagCount({ count }: { count: number }) {
  if (!count) return null;
  return (
    <span className="flag" title={`${count} compliance flag${count === 1 ? "" : "s"}`}>
      <span aria-hidden>⚠</span>
      {count}
    </span>
  );
}

export function RunStatusIndicator({
  status,
  label,
}: {
  status: RunStatus;
  label?: string;
}) {
  const live = status === "running" || status === "queued" || status === "waiting_batch";
  return (
    <span className={`runstatus runstatus--${status}`}>
      <span className={cx("runstatus__dot", live && "runstatus__dot--pulse")} aria-hidden />
      {label ?? RUN_STATUS_LABEL[status]}
    </span>
  );
}
