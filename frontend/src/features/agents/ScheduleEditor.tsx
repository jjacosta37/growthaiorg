/**
 * Schedule in plain words, with the raw cron behind an "advanced" disclosure.
 * The backend only stores cron, so the presets are a frontend convenience.
 */

import { useEffect, useState } from "react";

import { Button, Select, TextInput } from "../../components/primitives";
import { SCHEDULE_PRESETS, cronToPhrase, looksLikeCron, scheduleLabel } from "../../lib/format";

const CUSTOM = "__custom__";

export function ScheduleEditor({
  cron,
  onSave,
}: {
  cron: string;
  onSave: (cron: string) => void;
}) {
  const [value, setValue] = useState(cron);
  const [advanced, setAdvanced] = useState(() => !cronToPhrase(cron));

  useEffect(() => {
    setValue(cron);
  }, [cron]);

  const known = SCHEDULE_PRESETS.some((preset) => preset.cron === value);
  const dirty = value !== cron;
  const valid = looksLikeCron(value);

  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      <div className="row-flex" style={{ gap: "var(--space-3)" }}>
        {advanced ? (
          <TextInput
            mono
            value={value}
            invalid={!valid}
            onChange={(e) => setValue(e.target.value)}
            placeholder="0 */4 * * *"
          />
        ) : (
          <Select
            value={known ? value : CUSTOM}
            onChange={(e) => {
              if (e.target.value === CUSTOM) setAdvanced(true);
              else setValue(e.target.value);
            }}
          >
            {SCHEDULE_PRESETS.map((preset) => (
              <option key={preset.cron} value={preset.cron}>
                {preset.label}
              </option>
            ))}
            {!known && <option value={value}>{scheduleLabel(value)}</option>}
            <option value={CUSTOM}>Custom…</option>
          </Select>
        )}

        <button
          type="button"
          className="toast__action"
          onClick={() => setAdvanced((v) => !v)}
        >
          {advanced ? "Use a preset" : "Advanced"}
        </button>
      </div>

      <div className="row-flex" style={{ gap: "var(--space-3)" }}>
        <span className="subtle">
          {valid ? scheduleLabel(value) : "Needs five fields, e.g. 0 */4 * * *"}
          {valid && advanced && cronToPhrase(value) === null && (
            <span className="mono"> · {value}</span>
          )}
        </span>
        <span style={{ flex: 1 }} />
        {dirty && (
          <>
            <Button variant="ghost" size="sm" onClick={() => setValue(cron)}>
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!valid}
              onClick={() => onSave(value.trim())}
            >
              Save schedule
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
