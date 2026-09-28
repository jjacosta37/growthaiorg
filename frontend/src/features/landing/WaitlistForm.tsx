/** The email + "Join waitlist" row, used by the hero and the final call to action. */

import { useState, type FormEvent } from "react";

import { ApiError } from "../../lib/api";
import { useJoinWaitlist } from "../../lib/queries";

// Deliberately loose: the server's EmailField is the real check. This only catches
// obvious typos before a round trip.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach Luka. Check your connection and try again.";
    if (error.status === 429) return "Too many tries from here. Try again in a little while.";
    if (error.fieldErrors.email?.length) return "That doesn't look like an email address.";
  }
  return "Something went wrong. Try again.";
}

export function WaitlistForm({
  source,
  inputId,
  note,
}: {
  source: string;
  inputId: string;
  note?: string;
}) {
  const [email, setEmail] = useState("");
  const [invalid, setInvalid] = useState(false);
  const join = useJoinWaitlist();

  if (join.isSuccess) {
    return (
      <div className="landing-waitlist__done" role="status">
        You're on the list. We'll email you when Luka is ready.
      </div>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = email.trim();
    if (!EMAIL_RE.test(value)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    join.mutate({ email: value, source });
  };

  const message = invalid
    ? "Enter a valid email address."
    : join.isError
      ? errorMessage(join.error)
      : null;
  const errorId = `${inputId}-error`;

  return (
    <form className="landing-waitlist" onSubmit={submit} noValidate>
      <div className="landing-waitlist__row">
        <label htmlFor={inputId} className="visually-hidden">
          Email address
        </label>
        <input
          id={inputId}
          className="landing-input"
          type="email"
          name="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            if (invalid) setInvalid(false);
          }}
          aria-invalid={!!message}
          aria-describedby={message ? errorId : undefined}
        />
        <button type="submit" className="landing-btn landing-btn--lg" disabled={join.isPending}>
          {join.isPending ? "Joining…" : "Join waitlist"}
        </button>
      </div>
      {message ? (
        <div id={errorId} className="landing-waitlist__error" role="alert">
          {message}
        </div>
      ) : (
        note && <div className="landing-waitlist__note">{note}</div>
      )}
    </form>
  );
}
