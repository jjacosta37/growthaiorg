/**
 * First run: URL entry, then a live progress log.
 *
 * From "Helmly - Onboarding.dc.html". Both the thin-content warning and the
 * no-readable-pages failure end on Context — failure is never a dead end.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Logo } from "../../components/brand";
import { ProgressTimeline, type TimelineStep } from "../../components/feedback";
import { Button, Field, TextInput } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { keys, useRunEvents, useRun, useStartOnboarding } from "../../lib/queries";
import { isRunActive, type AgentRun } from "../../lib/types";

export default function OnboardingPage() {
  const [runId, setRunId] = useState<number | null>(null);

  return (
    <div className="onboarding">
      <div className="onboarding__card">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: "var(--space-6)" }}>
          <Logo size={28} />
        </div>
        {runId === null ? <StartForm onStarted={setRunId} /> : <Progress runId={runId} />}
      </div>
    </div>
  );
}

function StartForm({ onStarted }: { onStarted: (runId: number) => void }) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const start = useStartOnboarding();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const website_url = url.trim();
    if (!website_url) return;
    start.mutate(
      { website_url, name: name.trim() || undefined },
      { onSuccess: (run) => onStarted(run.id) },
    );
  };

  const fieldError = start.error instanceof ApiError ? start.error.fieldErrors : {};
  const detail =
    start.error instanceof ApiError && !Object.keys(fieldError).length
      ? start.error.detail
      : null;

  return (
    <form onSubmit={submit} className="stack" style={{ gap: "var(--space-5)" }}>
      <div className="stack" style={{ gap: "var(--space-2)", textAlign: "center" }}>
        <h1 className="page__title">Let's read your website</h1>
        <p className="muted">
          Helmly crawls your site and writes the context documents its agents work from.
        </p>
      </div>

      {detail && (
        <div className="banner banner--danger" role="alert">
          {detail}
        </div>
      )}

      <Field label="Website URL" htmlFor="website_url" error={fieldError.website_url}>
        <TextInput
          id="website_url"
          placeholder="https://example.com"
          autoFocus
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          invalid={!!fieldError.website_url}
        />
      </Field>

      <Field label="Product name" hint="Optional — Helmly works it out from the site." htmlFor="name">
        <TextInput id="name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>

      <Button
        type="submit"
        variant="primary"
        size="lg"
        block
        loading={start.isPending}
        disabled={!url.trim()}
      >
        Start
      </Button>
    </form>
  );
}

function Progress({ runId }: { runId: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const run = useRun(runId);
  const active = run.data ? isRunActive(run.data.status) : true;
  const events = useRunEvents(runId, active);

  // Context now exists, so anything cached from before the run is stale.
  useEffect(() => {
    if (run.data && !isRunActive(run.data.status)) {
      void queryClient.invalidateQueries({ queryKey: keys.project });
      void queryClient.invalidateQueries({ queryKey: keys.docs });
    }
  }, [run.data, queryClient]);

  const steps: TimelineStep[] = (events.data ?? []).map((event, index, all) => ({
    id: event.id,
    level: event.level,
    message: event.message,
    active: active && index === all.length - 1,
  }));

  if (active && !steps.length) {
    steps.push({ id: "start", level: "info", message: "Starting…", active: true });
  }

  return (
    <div className="stack" style={{ gap: "var(--space-5)" }}>
      <div className="stack" style={{ gap: "var(--space-2)", textAlign: "center" }}>
        <h1 className="page__title">Reading your website</h1>
        <p className="muted">This usually takes a couple of minutes.</p>
      </div>

      <div className="onboarding__log">
        <ProgressTimeline steps={steps} />
      </div>

      {run.data && !isRunActive(run.data.status) && (
        <Outcome run={run.data} onContinue={() => navigate("/context", { replace: true })} />
      )}
    </div>
  );
}

function Outcome({ run, onContinue }: { run: AgentRun; onContinue: () => void }) {
  const pages = run.stats.pages_crawled ?? 0;
  const failed = run.status === "failed";
  const thin = !failed && pages < 3;

  return (
    <div className="stack" style={{ gap: "var(--space-4)" }}>
      {failed && (
        <div className="banner banner--danger">
          {pages === 0
            ? "No readable pages found. You can write the context documents yourself, or try a different URL."
            : run.error || "The run failed. The documents may be incomplete."}
        </div>
      )}

      {thin && !failed && (
        <div className="banner banner--warning">
          Only {pages === 1 ? "1 readable page" : `${pages} readable pages`} found, so the
          documents will be thin. Worth editing them by hand on the next screen.
        </div>
      )}

      {!failed && !thin && (
        <div className="banner banner--info">
          Context is ready. You can edit any document before the agents use it.
        </div>
      )}

      <Button variant="primary" size="lg" block onClick={onContinue}>
        Go to Context
      </Button>
    </div>
  );
}
