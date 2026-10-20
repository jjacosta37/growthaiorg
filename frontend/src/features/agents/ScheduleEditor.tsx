/**
 * Schedule builder: how often, which days, what times, in the project's timezone.
 *
 * The server owns the rules (hourly minimum, 1–4 times, days 1–28), the plain-words summary and
 * the next runs; the editor asks it for a live preview so what you see is what beat will do.
 * A `custom` schedule (a cron saved before the builder) can only be replaced.
 */

import { useEffect, useMemo, useState } from "react";

import { useToast } from "../../components/feedback";
import { Button, IconButton, Select, TextInput, cx } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { formatInZone } from "../../lib/format";
import { useSchedulePreview, useUpdateAgent } from "../../lib/queries";
import type { AgentSummary, AgentType, Schedule } from "../../lib/types";

type BuilderSchedule = Exclude<Schedule, { kind: "custom" }>;
type BuilderKind = BuilderSchedule["kind"];

const MAX_TIMES = 4;
const HOURS = [1, 2, 3, 4, 6, 8, 12] as const;
/** Monday first, as people read a week; values are cron's 0 = Sunday. */
const WEEK = [
  { day: 1, short: "Mon", long: "Monday" },
  { day: 2, short: "Tue", long: "Tuesday" },
  { day: 3, short: "Wed", long: "Wednesday" },
  { day: 4, short: "Thu", long: "Thursday" },
  { day: 5, short: "Fri", long: "Friday" },
  { day: 6, short: "Sat", long: "Saturday" },
  { day: 0, short: "Sun", long: "Sunday" },
];

const KIND_LABEL: Record<BuilderKind, string> = {
  every_hours: "Every few hours",
  daily: "Every day",
  weekdays: "On chosen days",
  weekly: "Once a week",
  monthly: "Once a month",
};

function firstTime(s: Schedule): string {
  if ("times" in s) return s.times[0] ?? "09:00";
  if ("time" in s) return s.time;
  return "09:00";
}

/** Switching "how often" keeps the time already picked, where the new kind has one. */
function scheduleOfKind(kind: BuilderKind, from: Schedule): BuilderSchedule {
  const time = firstTime(from);
  const times = "times" in from && from.times.length ? from.times : [time];
  switch (kind) {
    case "every_hours":
      return { kind, hours: 4, minute: 0 };
    case "daily":
      return { kind, times };
    case "weekdays":
      return { kind, days: [1, 2, 3, 4, 5], times };
    case "weekly":
      return { kind, day: 1, time };
    case "monthly":
      return { kind, day: 1, time };
  }
}

function toMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

/** A time for "Add time": an hour after the last one, skipping times already listed. */
function nextFreeTime(times: string[]): string {
  let mark = (toMinutes(times[times.length - 1] ?? "08:00") + 60) % (24 * 60);
  for (let i = 0; i < 24; i += 1) {
    const t = `${String(Math.floor(mark / 60)).padStart(2, "0")}:${String(mark % 60).padStart(2, "0")}`;
    if (!times.includes(t)) return t;
    mark = (mark + 60) % (24 * 60);
  }
  return "09:00";
}

/** The server's messages without field names: they already say what's wrong. */
function errorText(error: ApiError): string {
  return Object.values(error.fieldErrors).flat().join(" · ") || error.detail;
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function timezoneOptions(current: string): string[] {
  let zones: string[] = [];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  return Array.from(new Set(["UTC", current, ...zones])).sort((a, b) =>
    a === "UTC" ? -1 : b === "UTC" ? 1 : a.localeCompare(b),
  );
}

export function ScheduleEditor<T extends AgentType>({ type, agent }: { type: T; agent: AgentSummary<T> }) {
  const [editing, setEditing] = useState(false);
  const isCustom = agent.schedule.kind === "custom";

  return (
    <div className="stack schedule" style={{ gap: "var(--space-3)" }}>
      {!editing && (
        <>
          <div className="row-flex schedule__row">
            <span>{isCustom ? "Custom schedule" : agent.schedule_summary}</span>
            {isCustom && <span className="subtle">({agent.timezone})</span>}
            <span style={{ flex: 1 }} />
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              {isCustom ? "Replace" : "Edit"}
            </Button>
          </div>
          {agent.schedule_warning === "too_frequent" && (
            <div className="banner banner--warning" role="status">
              This schedule runs more often than once an hour, which is no longer allowed. It keeps
              running until you replace it.
            </div>
          )}
          {isCustom && <NextRuns runs={agent.next_runs} timeZone={agent.timezone} />}
        </>
      )}
      {editing && <Builder type={type} agent={agent} onDone={() => setEditing(false)} />}
    </div>
  );
}

function NextRuns({ runs, timeZone }: { runs: string[]; timeZone: string }) {
  if (!runs.length) return <span className="subtle">No upcoming runs</span>;
  return (
    <ul className="schedule__runs subtle" aria-label="Next runs">
      {runs.map((iso) => (
        <li key={iso}>{formatInZone(iso, timeZone)}</li>
      ))}
    </ul>
  );
}

function Builder<T extends AgentType>({
  type,
  agent,
  onDone,
}: {
  type: T;
  agent: AgentSummary<T>;
  onDone: () => void;
}) {
  const toast = useToast();
  const update = useUpdateAgent(type);
  const preview = useSchedulePreview();
  const [schedule, setSchedule] = useState<BuilderSchedule>(() =>
    agent.schedule.kind === "custom" ? { kind: "daily", times: ["09:00"] } : agent.schedule,
  );
  // A project that never chose a timezone is offered the browser's; nothing is stored until save.
  const [timezone, setTimezone] = useState(() => (agent.timezone_set ? agent.timezone : browserTimezone()));
  const zones = useMemo(() => timezoneOptions(timezone), [timezone]);

  const { mutate: runPreview } = preview;
  const body = useMemo(() => ({ schedule, timezone }), [schedule, timezone]);
  useEffect(() => {
    const timer = window.setTimeout(() => runPreview(body), 250);
    return () => window.clearTimeout(timer);
  }, [body, runPreview]);

  const previewError =
    preview.error instanceof ApiError
      ? errorText(preview.error)
      : preview.error
        ? "Couldn't preview this schedule"
        : "";

  const onSave = () => {
    const timezoneChanged = !agent.timezone_set || timezone !== agent.timezone;
    update.mutate(
      { schedule, ...(timezoneChanged ? { timezone } : {}) },
      {
        onSuccess: () => {
          toast.show(timezoneChanged && agent.timezone_set ? "Schedule and timezone saved" : "Schedule saved");
          onDone();
        },
        onError: (error) =>
          toast.error(
            error instanceof ApiError
              ? errorText(error)
              : "Couldn't save the schedule",
          ),
      },
    );
  };

  return (
    <>
      <div className="schedule__row row-flex">
        <label className="schedule__label" htmlFor={`${type}-schedule-kind`}>
          How often
        </label>
        <Select
          id={`${type}-schedule-kind`}
          value={schedule.kind}
          onChange={(e) => setSchedule(scheduleOfKind(e.target.value as BuilderKind, schedule))}
        >
          {(Object.keys(KIND_LABEL) as BuilderKind[]).map((kind) => (
            <option key={kind} value={kind}>
              {KIND_LABEL[kind]}
            </option>
          ))}
        </Select>
      </div>

      <KindFields schedule={schedule} onChange={setSchedule} />

      <div className="schedule__row row-flex">
        <label className="schedule__label" htmlFor={`${type}-schedule-tz`}>
          Timezone
        </label>
        <Select id={`${type}-schedule-tz`} value={timezone} onChange={(e) => setTimezone(e.target.value)}>
          {zones.map((zone) => (
            <option key={zone} value={zone}>
              {zone.replace(/_/g, " ")}
            </option>
          ))}
        </Select>
      </div>
      <span className="subtle">
        {agent.timezone_set
          ? "The timezone applies to every agent in this project; their times of day stay the same."
          : "Proposed from your browser. It applies to every agent in this project once you save."}
      </span>

      <div className="schedule__preview" aria-live="polite">
        {previewError ? (
          <span className="schedule__error">{previewError}</span>
        ) : preview.data ? (
          <>
            <strong>{preview.data.summary}</strong>
            <NextRuns runs={preview.data.next_runs} timeZone={timezone} />
          </>
        ) : (
          <span className="subtle">Checking…</span>
        )}
      </div>

      <div className="row-flex" style={{ gap: "var(--space-3)", justifyContent: "flex-end" }}>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Discard
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={update.isPending}
          disabled={Boolean(previewError) || !preview.data || preview.isPending}
          onClick={onSave}
        >
          Save schedule
        </Button>
      </div>
    </>
  );
}

function KindFields({
  schedule,
  onChange,
}: {
  schedule: BuilderSchedule;
  onChange: (next: BuilderSchedule) => void;
}) {
  switch (schedule.kind) {
    case "every_hours":
      return (
        <div className="schedule__row row-flex">
          <Select
            aria-label="Interval"
            value={schedule.hours}
            onChange={(e) =>
              onChange({ ...schedule, hours: Number(e.target.value) as (typeof HOURS)[number] })
            }
          >
            {HOURS.map((h) => (
              <option key={h} value={h}>
                {h === 1 ? "Every hour" : `Every ${h} hours`}
              </option>
            ))}
          </Select>
          <span className="subtle">at</span>
          <Select
            aria-label="Minutes past the hour"
            value={schedule.minute}
            onChange={(e) => onChange({ ...schedule, minute: Number(e.target.value) })}
          >
            {Array.from(new Set([...Array.from({ length: 12 }, (_, i) => i * 5), schedule.minute]))
              .sort((a, b) => a - b)
              .map((m) => (
                <option key={m} value={m}>
                  :{String(m).padStart(2, "0")}
                </option>
              ))}
          </Select>
          <span className="subtle">past the hour</span>
        </div>
      );
    case "daily":
      return <TimeList times={schedule.times} onChange={(times) => onChange({ ...schedule, times })} />;
    case "weekdays":
      return (
        <>
          <DayPicker days={schedule.days} onChange={(days) => onChange({ ...schedule, days })} />
          <TimeList times={schedule.times} onChange={(times) => onChange({ ...schedule, times })} />
        </>
      );
    case "weekly":
      return (
        <div className="schedule__row row-flex">
          <Select
            aria-label="Day of the week"
            value={schedule.day}
            onChange={(e) => onChange({ ...schedule, day: Number(e.target.value) })}
          >
            {WEEK.map((d) => (
              <option key={d.day} value={d.day}>
                {d.long}
              </option>
            ))}
          </Select>
          <span className="subtle">at</span>
          <TimeInput value={schedule.time} onChange={(time) => onChange({ ...schedule, time })} />
        </div>
      );
    case "monthly":
      return (
        <div className="schedule__row row-flex">
          <span className="subtle">On day</span>
          <Select
            aria-label="Day of the month"
            value={schedule.day}
            onChange={(e) => onChange({ ...schedule, day: Number(e.target.value) })}
          >
            {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
          <span className="subtle">at</span>
          <TimeInput value={schedule.time} onChange={(time) => onChange({ ...schedule, time })} />
        </div>
      );
  }
}

function TimeInput({
  value,
  onChange,
  label = "Time of day",
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <TextInput
      type="time"
      step={60}
      className="schedule__time"
      aria-label={label}
      value={value}
      required
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function TimeList({ times, onChange }: { times: string[]; onChange: (times: string[]) => void }) {
  const duplicate = new Set(times).size !== times.length;
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div className="schedule__row row-flex">
        <span className="subtle">At</span>
        {times.map((t, i) => (
          <span key={i} className="row-flex schedule__time-row">
            <TimeInput
              value={t}
              label={`Time ${i + 1}`}
              onChange={(value) => onChange(times.map((x, j) => (j === i ? value : x)))}
            />
            {times.length > 1 && (
              <IconButton
                label={`Remove time ${i + 1}`}
                variant="ghost"
                size="sm"
                onClick={() => onChange(times.filter((_, j) => j !== i))}
              >
                ×
              </IconButton>
            )}
          </span>
        ))}
        <Button
          variant="ghost"
          size="sm"
          disabled={times.length >= MAX_TIMES}
          title={times.length >= MAX_TIMES ? `Up to ${MAX_TIMES} times a day` : undefined}
          onClick={() => onChange([...times, nextFreeTime(times)])}
        >
          Add time
        </Button>
      </div>
      {duplicate && <span className="schedule__error">Each time can only be listed once.</span>}
    </div>
  );
}

function DayPicker({ days, onChange }: { days: number[]; onChange: (days: number[]) => void }) {
  return (
    <div className="schedule__row row-flex" role="group" aria-label="Days of the week">
      {WEEK.map(({ day, short, long }) => {
        const active = days.includes(day);
        return (
          <button
            key={day}
            type="button"
            aria-pressed={active}
            aria-label={long}
            className={cx("format-chip", active && "format-chip--active")}
            onClick={() =>
              onChange(active ? days.filter((d) => d !== day) : [...days, day].sort((a, b) => a - b))
            }
          >
            {short}
          </button>
        );
      })}
      {days.length === 0 && <span className="schedule__error">Pick at least one day.</span>}
    </div>
  );
}
