/** Login. Accounts are created by an admin, so there is no signup — from "Helmly - Login.dc.html". */

import { useState, type FormEvent } from "react";

import { Logo } from "../../components/brand";
import { Button, Field, TextInput } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { useLogin } from "../../lib/queries";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!username || !password) return;
    login.mutate({ username, password });
  };

  const message =
    login.error instanceof ApiError
      ? login.error.status === 0
        ? "Can't reach Helmly. Check your connection and try again."
        : login.error.detail
      : login.error
        ? "Something went wrong. Try again."
        : null;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "var(--space-6)",
        background: "var(--color-bg)",
      }}
    >
      <form
        onSubmit={submit}
        className="card"
        style={{ width: "100%", maxWidth: 360, padding: "var(--space-7)" }}
      >
        <div style={{ display: "flex", justifyContent: "center", marginBottom: "var(--space-6)" }}>
          <Logo size={28} />
        </div>

        <div className="stack" style={{ gap: "var(--space-4)" }}>
          {message && (
            <div className="banner banner--danger" role="alert">
              {message}
            </div>
          )}

          <Field label="Username" htmlFor="username">
            <TextInput
              id="username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              invalid={!!message}
            />
          </Field>

          <Field label="Password" htmlFor="password">
            <TextInput
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              invalid={!!message}
            />
          </Field>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            loading={login.isPending}
            disabled={!username || !password}
          >
            Sign in
          </Button>
        </div>
      </form>
    </div>
  );
}
