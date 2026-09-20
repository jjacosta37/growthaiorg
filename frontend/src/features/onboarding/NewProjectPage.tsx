/**
 * Create a project.
 *
 * Shown on a first sign-in (an admin made the account but no project yet) and from
 * "New project…" in the switcher. Creating a project selects it; onboarding then runs
 * against it, so this is just the step before the existing onboarding flow.
 */

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Logo } from "../../components/brand";
import { Button, Field, TextInput } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { useCreateProject, useProjects } from "../../lib/queries";

export default function NewProjectPage({ first }: { first?: boolean }) {
  const [name, setName] = useState("");
  const create = useCreateProject();
  const projects = useProjects();
  const navigate = useNavigate();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name: name.trim() || undefined },
      { onSuccess: () => navigate("/onboarding", { replace: true }) },
    );
  };

  const fieldErrors = create.error instanceof ApiError ? create.error.fieldErrors : {};
  const canGoBack = !first && (projects.data?.length ?? 0) > 0;

  return (
    <div className="onboarding">
      <form onSubmit={submit} className="onboarding__card">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: "var(--space-6)" }}>
          <Logo size={28} />
        </div>

        <div className="stack" style={{ gap: "var(--space-5)" }}>
          <div className="stack" style={{ gap: "var(--space-2)", textAlign: "center" }}>
            <h1 className="page__title">
              {first ? "Set up your first project" : "New project"}
            </h1>
            <p className="muted">
              A project is one company's marketing — its context documents, agents and
              inbox. You'll point Helmly at the website next.
            </p>
          </div>

          <Field label="Project name" hint="You can rename it later." error={fieldErrors.name}>
            <TextInput
              autoFocus
              placeholder="Acme"
              value={name}
              onChange={(e) => setName(e.target.value)}
              invalid={!!fieldErrors.name}
            />
          </Field>

          <Button type="submit" variant="primary" size="lg" block loading={create.isPending}>
            Create project
          </Button>

          {canGoBack && (
            <Button variant="ghost" block onClick={() => navigate(-1)}>
              Cancel
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
