/**
 * Agent pages: one layout, three config bodies.
 * From "Luka - Agent Pages.dc.html".
 *
 * Reddit adds the skipped list; Content adds the topic backlog and request form.
 */

import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { RunStatusIndicator } from "../../components/badges";
import { DetailPane } from "../../components/Shell";
import { Dialog, EmptyState, ErrorState, useToast } from "../../components/feedback";
import { Button, Field, Toggle } from "../../components/primitives";
import { ProgressTimeline } from "../../components/feedback";
import { ApiError } from "../../lib/api";
import { AGENT_LABEL, dateTime, relative, runSummary } from "../../lib/format";
import {
  useAgent,
  useAgentRuns,
  useRunEvents,
  useRunNow,
  useUpdateAgent,
} from "../../lib/queries";
import { AGENT_TYPES, type AgentType } from "../../lib/types";
import { ContentConfigForm, RedditConfigForm, XConfigForm } from "./ConfigForms";
import { ScheduleEditor } from "./ScheduleEditor";
import { SkippedList } from "./SkippedList";
import { TopicBacklog } from "./TopicBacklog";
import "./agents.css";

export default function AgentPage() {
  const { agentType } = useParams();
  if (!AGENT_TYPES.includes(agentType as AgentType)) {
    return <Navigate to="/inbox" replace />;
  }
  return <AgentBody key={agentType} type={agentType as AgentType} />;
}

function AgentBody({ type }: { type: AgentType }) {
  const agent = useAgent(type);
  const update = useUpdateAgent(type);
  const runNow = useRunNow(type);
  const runs = useAgentRuns(type);
  const toast = useToast();
  const [openRun, setOpenRun] = useState<number | null>(null);

  if (agent.isLoading) {
    return (
      <DetailPane wide>
        <div className="page">
          <EmptyState title="Loading…" />
        </div>
      </DetailPane>
    );
  }

  if (agent.isError || !agent.data) {
    return (
      <DetailPane wide>
        <ErrorState title="Couldn't load this agent" onRetry={() => void agent.refetch()} />
      </DetailPane>
    );
  }

  const data = agent.data;
  const lastRun = data.last_run;

  const saveConfig = (config: unknown) =>
    update.mutate(
      { config },
      {
        onSuccess: () => toast.show("Configuration saved"),
        onError: (error) =>
          toast.error(
            error instanceof ApiError
              ? Object.values(error.fieldErrors).flat().join(" · ") || error.detail
              : "Couldn't save",
          ),
      },
    );

  return (
    <DetailPane wide>
      <div className="page">
        <header className="page__header">
          <div>
            <h1 className="page__title">{AGENT_LABEL[type]}</h1>
            <div className="page__subtitle row-flex" style={{ gap: "var(--space-2)" }}>
              {lastRun ? (
                <>
                  <span>Last run {relative(lastRun.finished_at ?? lastRun.created_at)}</span>
                  <span>·</span>
                  <RunStatusIndicator status={lastRun.status} />
                </>
              ) : (
                <span>Never run</span>
              )}
              {data.next_run_at && data.enabled && (
                <>
                  <span>·</span>
                  <span>Next run {relative(data.next_run_at)}</span>
                </>
              )}
            </div>
          </div>

          <div className="row-flex" style={{ gap: "var(--space-3)" }}>
            <Toggle
              checked={data.enabled}
              label={data.enabled ? "Enabled" : "Disabled"}
              onChange={(enabled) =>
                update.mutate(
                  { enabled },
                  {
                    onSuccess: () =>
                      toast.show(enabled ? "Agent enabled" : "Agent disabled"),
                  },
                )
              }
            />
            <Button
              variant="primary"
              loading={runNow.isPending}
              onClick={() =>
                runNow.mutate(undefined, {
                  onSuccess: () => toast.show("Run started"),
                  onError: (error) =>
                    toast.error(error instanceof ApiError ? error.detail : "Couldn't start"),
                })
              }
            >
              Run now
            </Button>
          </div>
        </header>

        {data.last_error && (
          <div className="banner banner--danger">{data.last_error}</div>
        )}

        <section className="card">
          <div className="card__header">
            <span className="card__title">Configuration</span>
            {update.isPending && <span className="subtle">Saving…</span>}
          </div>
          <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
            {type === "reddit" && (
              <RedditConfigForm
                config={data.config as never}
                onSave={saveConfig}
                saving={update.isPending}
              />
            )}
            {type === "content" && (
              <ContentConfigForm
                config={data.config as never}
                onSave={saveConfig}
                saving={update.isPending}
              />
            )}
            {type === "x" && (
              <XConfigForm
                config={data.config as never}
                onSave={saveConfig}
                saving={update.isPending}
              />
            )}

            <Field label="Schedule">
              <ScheduleEditor
                cron={data.cron}
                onSave={(cron) =>
                  update.mutate(
                    { cron },
                    {
                      onSuccess: () => toast.show("Schedule saved"),
                      onError: (error) =>
                        toast.error(
                          error instanceof ApiError
                            ? error.fieldErrors.cron?.join(" ") || error.detail
                            : "Couldn't save the schedule",
                        ),
                    },
                  )
                }
              />
            </Field>
          </div>
        </section>

        <section className="card">
          <div className="card__header">
            <span className="card__title">Run history</span>
          </div>
          <div className="card__body" style={{ padding: 0 }}>
            {runs.data?.results.length ? (
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Trigger</th>
                    <th>Status</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.results.map((run) => (
                    <tr key={run.id} onClick={() => setOpenRun(run.id)}>
                      <td className="table__mono">{dateTime(run.created_at)}</td>
                      <td>{run.trigger === "manual" ? "Manual" : "Scheduled"}</td>
                      <td>
                        <RunStatusIndicator status={run.status} />
                      </td>
                      <td>{run.error || runSummary(run.kind, run.stats)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="No runs yet" body="Press Run now to try it." />
            )}
          </div>
        </section>

        {type === "reddit" && <SkippedList threshold={(data.config as never as { relevance_threshold: number }).relevance_threshold} />}
        {type === "content" && <TopicBacklog />}
      </div>

      <RunLogDialog runId={openRun} onClose={() => setOpenRun(null)} />
    </DetailPane>
  );
}

function RunLogDialog({ runId, onClose }: { runId: number | null; onClose: () => void }) {
  const events = useRunEvents(runId, false);
  return (
    <Dialog
      open={runId !== null}
      title="Run log"
      wide
      onClose={onClose}
      actions={
        <Button variant="primary" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div style={{ maxHeight: 380, overflowY: "auto" }}>
        {events.data?.length ? (
          <ProgressTimeline
            steps={events.data.map((event) => ({
              id: event.id,
              level: event.level,
              message: event.message,
            }))}
          />
        ) : (
          <p className="subtle">No events recorded for this run.</p>
        )}
      </div>
    </Dialog>
  );
}
