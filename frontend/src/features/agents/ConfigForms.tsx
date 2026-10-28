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
  Select,
  Slider,
  Textarea,
  cx,
} from "../../components/primitives";
import { X_FORMAT_LABEL } from "../../lib/format";
import {
  SEARCH_LANGUAGES,
  SEARCH_MARKETS,
  X_FORMATS,
  type ContentConfig,
  type OpportunityWeight,
  type OpportunityWeights,
  type RedditConfig,
  type XConfig,
} from "../../lib/types";

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
  onDirtyChange,
}: {
  config: RedditConfig;
  onSave: (config: RedditConfig) => void;
  saving?: boolean;
  /** Told when unsaved edits appear or go, so "Add" from suggestions can't overwrite them. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const { draft, setDraft, dirty, reset } = useDraftConfig(config);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
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

      <div className="config-grid">
        <Field label="Search market" hint="Where search volume and difficulty are measured.">
          <Select
            value={draft.search_country}
            onChange={(e) => {
              const market = SEARCH_MARKETS.find((m) => m.code === e.target.value);
              setDraft({
                ...draft,
                search_country: e.target.value,
                search_language: market?.language ?? draft.search_language,
              });
            }}
          >
            {SEARCH_MARKETS.map((m) => (
              <option key={m.code} value={m.code}>
                {m.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Search language">
          <Select
            value={draft.search_language}
            onChange={(e) => set("search_language", e.target.value)}
          >
            {SEARCH_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <WeightsField weights={draft.weights} onChange={(weights) => set("weights", weights)} />

      <SaveBar dirty={dirty} saving={saving} onSave={() => onSave(draft)} onReset={reset} />
    </>
  );
}

const WEIGHT_OPTIONS: { value: OpportunityWeight; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

const SIGNALS: { key: keyof OpportunityWeights; label: string; hint: string }[] = [
  { key: "volume", label: "Search volume", hint: "How many people search for the topic each month." },
  { key: "ease", label: "Ease of ranking", hint: "How easy it is to reach the first page of results." },
  { key: "reddit", label: "Reddit demand", hint: "How many Reddit posts ask the question." },
];

const BALANCED: OpportunityWeights = { volume: "medium", ease: "medium", reddit: "medium" };

const PRESETS: { label: string; weights: OpportunityWeights }[] = [
  { label: "Balanced", weights: BALANCED },
  { label: "Search first", weights: { volume: "high", ease: "medium", reddit: "low" } },
  { label: "Community first", weights: { volume: "low", ease: "low", reddit: "high" } },
];

const sameWeights = (a: OpportunityWeights, b: OpportunityWeights) =>
  a.volume === b.volume && a.ease === b.ease && a.reddit === b.reddit;

/** "What matters most": presets plus one Off/Low/Medium/High control per signal. */
function WeightsField({
  weights,
  onChange,
}: {
  weights: OpportunityWeights;
  onChange: (weights: OpportunityWeights) => void;
}) {
  return (
    <Field
      label="What matters most"
      hint="Decides the backlog's order and which topic is drafted next. Requested topics always go first."
    >
      <div className="stack" style={{ gap: "var(--space-3)" }}>
        <div className="row-flex" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
          {PRESETS.map((preset) => {
            const active = sameWeights(weights, preset.weights);
            return (
              <button
                key={preset.label}
                type="button"
                aria-pressed={active}
                className={cx("format-chip", active && "format-chip--active")}
                onClick={() => onChange(preset.weights)}
              >
                {preset.label}
              </button>
            );
          })}
          {!sameWeights(weights, BALANCED) && (
            <Button variant="ghost" size="sm" onClick={() => onChange(BALANCED)}>
              Reset to default
            </Button>
          )}
        </div>

        {SIGNALS.map((signal) => (
          <div key={signal.key} className="weight-row">
            <div className="stack" style={{ gap: "var(--space-1)" }}>
              <span>{signal.label}</span>
              <span className="subtle">{signal.hint}</span>
            </div>
            <Segmented<OpportunityWeight>
              ariaLabel={signal.label}
              value={weights[signal.key]}
              onChange={(value) => onChange({ ...weights, [signal.key]: value })}
              options={WEIGHT_OPTIONS}
            />
          </div>
        ))}
      </div>
    </Field>
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
