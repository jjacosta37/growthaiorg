/**
 * The three-pane shell: sidebar | list | detail.
 *
 * From "Helmly - App Shell.dc.html". The sidebar owns the live status line and the
 * offline banner from "Helmly - Global States.dc.html".
 */

import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AGENT_LABEL } from "../lib/format";
import { useAgents, useInboxCounts, useProject, useStatus } from "../lib/queries";
import { AGENT_TYPES, type AgentType } from "../lib/types";
import { ChannelDot } from "./badges";
import { HelmTile } from "./brand";
import { Button, cx } from "./primitives";

function navClass({ isActive }: { isActive: boolean }): string {
  return cx("shell__nav-item", isActive && "shell__nav-item--active");
}

export function Shell() {
  const project = useProject();
  const counts = useInboxCounts();
  const agents = useAgents();
  const status = useStatus();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // status is the most frequent call, so its failure is the best offline signal.
  const offline = status.isError;

  const failedAgents = (agents.data ?? []).filter(
    (agent) => agent.last_run?.status === "failed",
  );

  return (
    <div className="shell">
      {offline && (
        <div className="shell__offline" role="alert">
          <span>Can't reach Helmly — showing the last loaded data. Retrying…</span>
          <Button
            size="sm"
            onClick={() => {
              void queryClient.refetchQueries();
            }}
          >
            Retry now
          </Button>
        </div>
      )}

      <div className="shell__body">
        <nav className="shell__sidebar">
          <div>
            <button
              type="button"
              className="shell__project"
              onClick={() => navigate("/settings")}
              title={project.data?.website_url ?? undefined}
            >
              <HelmTile size={20} />
              <span className="truncate" style={{ flex: 1, fontWeight: "var(--weight-semibold)" }}>
                {project.data?.name || "Helmly"}
              </span>
              <span className="subtle" style={{ fontSize: 10 }}>
                ▾
              </span>
            </button>

            <NavLink to="/inbox" className={navClass}>
              <span style={{ flex: 1, fontWeight: "var(--weight-medium)" }}>Inbox</span>
              {!!counts.data?.unread && (
                <span className="shell__count shell__count--strong">{counts.data.unread}</span>
              )}
            </NavLink>

            <div className="shell__section">Agents</div>
            {AGENT_TYPES.map((type) => {
              const agent = agents.data?.find((a) => a.agent_type === type);
              const failed = agent?.last_run?.status === "failed";
              return (
                <NavLink key={type} to={`/agents/${type}`} className={navClass}>
                  <ChannelDot channel={type} />
                  <span style={{ flex: 1 }}>{AGENT_LABEL[type].replace(" Agent", "")}</span>
                  {failed ? (
                    <span
                      className="shell__count"
                      style={{ color: "var(--color-danger)" }}
                      title="Last run failed"
                    >
                      !
                    </span>
                  ) : (
                    !!agent?.ready && <span className="shell__count">{agent.ready}</span>
                  )}
                </NavLink>
              );
            })}

            <div style={{ marginTop: "var(--space-3)" }}>
              <NavLink to="/context" className={navClass}>
                Context
              </NavLink>
              <NavLink to="/stats" className={navClass}>
                Stats
              </NavLink>
              <NavLink to="/settings" className={navClass}>
                Settings
              </NavLink>
            </div>
          </div>

          <StatusLine
            message={status.data?.message ?? null}
            active={!!status.data?.active.length}
            failedAgents={failedAgents.map((a) => a.agent_type)}
          />
        </nav>

        <Outlet />
      </div>
    </div>
  );
}

function StatusLine({
  message,
  active,
  failedAgents,
}: {
  message: string | null;
  active: boolean;
  failedAgents: AgentType[];
}) {
  const navigate = useNavigate();

  if (!active && failedAgents.length) {
    const type = failedAgents[0]!;
    return (
      <div className="shell__status">
        <span className="shell__status-dot" style={{ background: "var(--color-danger)" }} />
        <div className="stack" style={{ gap: "var(--space-2)", flex: 1 }}>
          <span style={{ color: "var(--color-danger)" }}>{AGENT_LABEL[type]} run failed</span>
          <button
            type="button"
            className="toast__action"
            style={{ textAlign: "left" }}
            onClick={() => navigate(`/agents/${type}`)}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!message) {
    return (
      <div className="shell__status">
        <span className="shell__status-dot shell__status-dot--idle" />
        <span>Idle</span>
      </div>
    );
  }

  return (
    <div className="shell__status">
      <span
        className={cx("shell__status-dot", active && "shell__status-dot--live")}
        aria-hidden
      />
      <span>{message}</span>
    </div>
  );
}

/** The middle pane: a filter header over a scrolling list, with an optional footer. */
export function ListPane({
  header,
  children,
  footer,
}: {
  header?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="shell__list">
      {header && <div className="shell__list-header">{header}</div>}
      <div className="shell__list-body">{children}</div>
      {footer}
    </div>
  );
}

/** The right pane. Full-width pages (Context, Stats, Settings) use `wide`. */
export function DetailPane({
  children,
  wide,
}: {
  children: ReactNode;
  wide?: boolean;
}) {
  return <div className={cx("shell__detail", wide && "shell__detail--wide")}>{children}</div>;
}
