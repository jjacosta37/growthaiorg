import { describe, expect, it } from "vitest";

import { age, formatInZone, relative, repeatHintText, runSummary } from "./format";

const NOW = Date.parse("2026-09-19T12:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();

describe("age", () => {
  it("collapses recent times to 'now'", () => {
    expect(age(ago(30_000), NOW)).toBe("now");
  });

  it("steps through minutes, hours, days and weeks", () => {
    expect(age(ago(4 * 60_000), NOW)).toBe("4m");
    expect(age(ago(3 * 3_600_000), NOW)).toBe("3h");
    expect(age(ago(2 * 86_400_000), NOW)).toBe("2d");
    expect(age(ago(21 * 86_400_000), NOW)).toBe("3w");
  });

  it("is empty for missing or unparseable input", () => {
    expect(age(null, NOW)).toBe("");
    expect(age("not a date", NOW)).toBe("");
  });
});

describe("relative", () => {
  it("reads as past or future", () => {
    expect(relative(ago(2 * 3_600_000), NOW)).toBe("2h ago");
    expect(relative(new Date(NOW + 3 * 3_600_000).toISOString(), NOW)).toBe("in 3h");
  });

  it("names yesterday and tomorrow", () => {
    expect(relative(ago(30 * 3_600_000), NOW)).toBe("yesterday");
    expect(relative(new Date(NOW + 30 * 3_600_000).toISOString(), NOW)).toBe("tomorrow");
  });

  it("says never with no timestamp", () => {
    expect(relative(null, NOW)).toBe("never");
  });
});

describe("formatInZone", () => {
  it("shows a run in the project's timezone, following daylight saving", () => {
    expect(formatInZone("2026-10-24T07:00:00Z", "Europe/Madrid")).toBe("Sat 24 Oct, 9:00am");
    expect(formatInZone("2026-10-25T08:00:00Z", "Europe/Madrid")).toBe("Sun 25 Oct, 9:00am");
    expect(formatInZone("2026-10-25T08:00:00Z", "UTC")).toBe("Sun 25 Oct, 8:00am");
    expect(formatInZone("2026-10-25T20:30:00Z", "UTC")).toBe("Sun 25 Oct, 8:30pm");
  });
});

describe("runSummary", () => {
  it("reads like the run history column", () => {
    expect(
      runSummary("reddit", { fetched: 10, above_threshold: 3, threshold: 70, drafted: 3 }),
    ).toBe("10 found · 3 scored ≥ 70 · 3 drafted");
  });

  it("covers the other pipelines", () => {
    expect(runSummary("content", { topics_proposed: 3, drafted: 1 })).toBe("3 topics · 1 drafted");
    expect(runSummary("x", { planned: 3, drafted: 3, over_limit: 1 })).toBe(
      "3 planned · 3 drafted · 1 over limit",
    );
    expect(runSummary("onboarding", { pages_crawled: 24, pages_rendered: 4 })).toBe(
      "24 pages · 4 rendered",
    );
  });

  it("appends warnings and copes with nothing to say", () => {
    expect(runSummary("reddit", { fetched: 2, warnings: ["thin"] })).toBe("2 found · 1 warning");
    expect(runSummary("reddit", {})).toBe("—");
    expect(runSummary("reddit", null)).toBe("—");
  });

  it("keeps a zero count rather than dropping it", () => {
    expect(runSummary("reddit", { fetched: 0, drafted: 0 })).toBe("0 found · 0 drafted");
  });
});

describe("repeatHintText", () => {
  it("names the window and the gap between runs", () => {
    expect(repeatHintText({ time_window: "week", window_hours: 168, gap_hours: 4 })).toMatch(
      /^Each run searches the last week of posts but runs every 4 hours, so most results will be posts already seen/,
    );
    expect(repeatHintText({ time_window: "day", window_hours: 24, gap_hours: 1 })).toContain("runs every hour,");
  });
});
