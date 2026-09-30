/**
 * Per-agent configuration bodies. Each field maps to a key in the agent's pydantic
 * config schema, so a save is a straight PATCH of the whole config object.
 */

import { useEffect, useState } from "react";

import {
  Button,
  ChipInput,
  Field,
  NumberInput,
  Segmented,
  Slider,
  Textarea,
  cx,
} from "../../components/primitives";
import { X_FORMAT_LABEL } from "../../lib/format";
import { X_FORMATS, type ContentConfig, type RedditConfig, type XConfig } from "../../lib/types";

/** Tracks edits against the saved config and reveals Save only when they differ. */
function useDraftConfig<T>(config: T) {
  const [draft, setDraft] = useState<T>(config);

  // Follow the server after a save or a refetch.
  useEffect(() => {
    setDraft(config);
  }, [config]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(config);
  return { draft, setDraft, dirty, reset: () => setDraft(config) };
}

function SaveBar({
  dirty,
  saving,
  onSave,
  onReset,
}: {
  dirty: boolean;
  saving?: boolean;
  onSave: () => void;
  onReset: () => void;
}) {
  if (!dirty) return null;
  return (
    <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
      <Button variant="ghost" size="sm" onClick={onReset}>
        Discard
      </Button>
      <Button variant="primary" size="sm" loading={saving} onClick={onSave}>
        Save changes
      </Button>
    </div>
  );
}

/* ---------------------------------------------------------------- reddit */

export function RedditConfigForm({
  config,
  onSave,
  saving,
}: {
  config: RedditConfig;
  onSave: (config: RedditConfig) => void;
  saving?: boolean;
}) {
  const { draft, setDraft, dirty, reset } = useDraftConfig(config);
  const set = <K extends keyof RedditConfig>(key: K, value: RedditConfig[K]) =>
    setDraft({ ...draft, [key]: value });

  return (
    <>
      <Field label="Subreddits" hint="Press Enter after each one.">
        <ChipInput
          values={draft.subreddits}
          onChange={(next) => set("subreddits", next)}
          placeholder="r/example"
          transform={(raw) => (raw.startsWith("r/") ? raw : `r/${raw.replace(/^\/+/, "")}`)}
        />
      </Field>

      <Field label="Keywords">
        <ChipInput
          values={draft.keywords}
          onChange={(next) => set("keywords", next)}
          placeholder="deadline tracking"
        />
      </Field>

      <Field
        label="Relevance threshold"
        hint="Posts scoring at or above this get a drafted comment."
      >
        <Slider
          value={draft.relevance_threshold}
          onChange={(value) => set("relevance_threshold", value)}
        />
      </Field>

      <div className="config-grid">
        <Field label="Posts per scan">
          <NumberInput
            value={draft.max_posts_per_run}
            min={1}
            max={200}
            onChange={(value) => set("max_posts_per_run", value)}
          />
        </Field>

        <Field label="Time window">
          <Segmented
            value={draft.time_window}
            onChange={(value) => set("time_window", value)}
            ariaLabel="Time window"
            options={[
              { value: "hour", label: "Hour" },
              { value: "day", label: "Day" },
              { value: "week", label: "Week" },
            ]}
          />
        </Field>
      </div>

      <Field
        label="Custom instructions"
        hint="Applied to every reply this agent writes. The content rules still take priority."
      >
        <Textarea
          rows={4}
          maxLength={2000}
          value={draft.guidance}
          onChange={(e) => set("guidance", e.target.value)}
          placeholder="Keep replies under 120 words. Write in a friendly, first-person voice."
        />
      </Field>

      <SaveBar dirty={dirty} saving={saving} onSave={() => onSave(draft)} onReset={reset} />
    </>
  );
}

/* --------------------------------------------------------------- content */

export function ContentConfigForm({
  config,
  onSave,
  saving,
}: {
  config: ContentConfig;
  onSave: (config: ContentConfig) => void;
  saving?: boolean;
}) {
  const { draft, setDraft, dirty, reset } = useDraftConfig(config);
  const set = <K extends keyof ContentConfig>(key: K, value: ContentConfig[K]) =>
    setDraft({ ...draft, [key]: value });

  return (
    <>
      <div className="config-grid">
        <Field label="Topics per run">
          <NumberInput
            value={draft.topics_per_run}
            min={1}
            max={10}
            onChange={(value) => set("topics_per_run", value)}
          />
        </Field>

        <Field label="Drafts per run">
          <NumberInput
            value={draft.drafts_per_run}
            min={0}
            max={3}
            onChange={(value) => set("drafts_per_run", value)}
          />
        </Field>

        <Field label="Target words">
          <NumberInput
            value={draft.target_words}
            min={500}
            max={3000}
            onChange={(value) => set("target_words", value)}
          />
        </Field>

        <Field label="Minimum backlog" hint="Top up the backlog below this many topics.">
          <NumberInput
            value={draft.min_backlog}
            min={0}
            max={20}
            onChange={(value) => set("min_backlog", value)}
          />
        </Field>
      </div>

      <Field label="Standing guidance" hint="Applied to every post this agent writes.">
        <Textarea
          rows={3}
          maxLength={2000}
          value={draft.guidance}
          onChange={(e) => set("guidance", e.target.value)}
          placeholder="Favor concrete, step-by-step advice. Avoid generic listicles."
        />
      </Field>

      <SaveBar dirty={dirty} saving={saving} onSave={() => onSave(draft)} onReset={reset} />
    </>
  );
}

/* --------------------------------------------------------------------- x */

export function XConfigForm({
  config,
  onSave,
  saving,
}: {
  config: XConfig;
  onSave: (config: XConfig) => void;
  saving?: boolean;
}) {
  const { draft, setDraft, dirty, reset } = useDraftConfig(config);
  const set = <K extends keyof XConfig>(key: K, value: XConfig[K]) =>
    setDraft({ ...draft, [key]: value });

  const toggleFormat = (format: (typeof X_FORMATS)[number]) => {
    const next = draft.formats.includes(format)
      ? draft.formats.filter((f) => f !== format)
      : [...draft.formats, format];
    set("formats", next);
  };

  return (
    <>
      <Field label="Formats" hint="The mix this agent chooses from.">
        <div className="row-flex" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
          {X_FORMATS.map((format) => {
            const active = draft.formats.includes(format);
            return (
              <button
                key={format}
                type="button"
                aria-pressed={active}
                className={cx("format-chip", active && "format-chip--active")}
                onClick={() => toggleFormat(format)}
              >
                {X_FORMAT_LABEL[format]}
              </button>
            );
          })}
        </div>
      </Field>

      <div className="config-grid">
        <Field label="Posts per run">
          <NumberInput
            value={draft.posts_per_run}
            min={1}
            max={10}
            onChange={(value) => set("posts_per_run", value)}
          />
        </Field>

        <Field label="Max thread length">
          <NumberInput
            value={draft.max_thread_posts}
            min={2}
            max={10}
            onChange={(value) => set("max_thread_posts", value)}
          />
        </Field>

        <Field label="Character limit" hint="280, or more with Premium.">
          <NumberInput
            value={draft.char_limit}
            min={100}
            max={25000}
            onChange={(value) => set("char_limit", value)}
          />
        </Field>

        <Field label="Recent window" hint="Past drafts passed in to avoid repetition.">
          <NumberInput
            value={draft.recent_window}
            min={0}
            max={200}
            onChange={(value) => set("recent_window", value)}
          />
        </Field>
      </div>

      <Field label="Standing guidance">
        <Textarea
          rows={3}
          maxLength={2000}
          value={draft.guidance}
          onChange={(e) => set("guidance", e.target.value)}
        />
      </Field>

      <SaveBar dirty={dirty} saving={saving} onSave={() => onSave(draft)} onReset={reset} />
    </>
  );
}
