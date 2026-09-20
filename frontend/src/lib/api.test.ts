import { describe, expect, it } from "vitest";

import { ApiError, summarise, toFieldErrors } from "./api";

describe("toFieldErrors", () => {
  it("flattens DRF's field errors", () => {
    expect(toFieldErrors({ cron: ["Bad cron"], name: ["Required", "Too short"] })).toEqual({
      cron: ["Bad cron"],
      name: ["Required", "Too short"],
    });
  });

  it("unwraps the pydantic shape into dotted paths", () => {
    const body = {
      config: [
        { loc: ["subreddits", 0], msg: "String should match pattern", type: "string_pattern" },
        { loc: ["relevance_threshold"], msg: "Input should be less than 100", type: "less_than" },
      ],
    };
    expect(toFieldErrors(body)).toEqual({
      "subreddits.0": ["String should match pattern"],
      relevance_threshold: ["Input should be less than 100"],
    });
  });

  it("keeps the wrapper key when an issue has no location", () => {
    expect(toFieldErrors({ content: [{ loc: [], msg: "Invalid content" }] })).toEqual({
      content: ["Invalid content"],
    });
  });

  it("ignores `detail`, which is a message rather than a field", () => {
    expect(toFieldErrors({ detail: "A reddit run is already in progress" })).toEqual({});
  });

  it("returns nothing for shapes that carry no field errors", () => {
    expect(toFieldErrors(null)).toEqual({});
    expect(toFieldErrors("gateway timeout")).toEqual({});
    expect(toFieldErrors(["a", "b"])).toEqual({});
  });
});

describe("summarise", () => {
  it("joins field errors into one line", () => {
    expect(summarise({ cron: ["Bad cron"], name: ["Required"] })).toBe(
      "cron: Bad cron · name: Required",
    );
  });

  it("drops the label for non-field errors", () => {
    expect(summarise({ non_field_errors: ["Invalid credentials."] })).toBe("Invalid credentials.");
  });
});

describe("ApiError", () => {
  it("surfaces `detail` as the human message", () => {
    const error = new ApiError(409, { detail: "A reddit run is already in progress" });
    expect(error.detail).toBe("A reddit run is already in progress");
    expect(error.isConflict).toBe(true);
  });

  it("falls back to its own message when there is no detail", () => {
    expect(new ApiError(500, null).detail).toBe("Request failed with 500");
  });

  it("treats 401 and 403 as unauthenticated, but not 409", () => {
    expect(new ApiError(403, null).isUnauthenticated).toBe(true);
    expect(new ApiError(401, null).isUnauthenticated).toBe(true);
    expect(new ApiError(409, null).isUnauthenticated).toBe(false);
  });

  it("exposes field errors from the body", () => {
    const error = new ApiError(400, { reason: ["Not a valid choice"] });
    expect(error.fieldErrors).toEqual({ reason: ["Not a valid choice"] });
  });
});
