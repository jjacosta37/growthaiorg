/**
 * Settings: the content policy, account and theme.
 * From "Luka - Settings.dc.html".
 *
 * Switching an industry pack previews the incoming rules and asks for confirmation
 * before it replaces the current set.
 */

import { useState } from "react";

import { DetailPane } from "../../components/Shell";
import { ConfirmDialog, ErrorState, useToast } from "../../components/feedback";
import {
  Button,
  Field,
  Segmented,
  TextInput,
  Textarea,
  cx,
} from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { useApplyPack, useLogout, usePolicy, usePolicyPacks, useUpdatePolicy } from "../../lib/queries";
import { useTheme, type Theme } from "../../lib/theme";
import type { PolicyRule } from "../../lib/types";
import "./settings.css";

export default function SettingsPage() {
  const policy = usePolicy();
  const packs = usePolicyPacks();
  const [pendingPack, setPendingPack] = useState<string | null>(null);
  const applyPack = useApplyPack();
  const toast = useToast();

  if (policy.isError) {
    return (
      <DetailPane wide>
        <ErrorState title="Couldn't load your settings" onRetry={() => void policy.refetch()} />
      </DetailPane>
    );
  }

  const data = policy.data;
  const incoming = packs.data?.find((pack) => pack.id === pendingPack);

  return (
    <DetailPane wide>
      <div className="page">
        <header className="page__header">
          <div>
            <h1 className="page__title">Settings</h1>
            <p className="page__subtitle">
              Rules Luka checks every draft against, before it reaches your inbox.
            </p>
          </div>
        </header>

        <section className="card">
          <div className="card__header">
            <span className="card__title">Industry pack</span>
            {data && <span className="subtle">Currently {data.pack_name}</span>}
          </div>
          <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
            <div className="packs">
              {(packs.data ?? []).map((pack) => (
                <button
                  key={pack.id}
                  type="button"
                  className={cx("pack", data?.pack === pack.id && "pack--active")}
                  onClick={() => data?.pack !== pack.id && setPendingPack(pack.id)}
                >
                  <strong>{pack.name}</strong>
                  <span className="subtle">{pack.description}</span>
                  <span className="subtle">{pack.rules.length} rules</span>
                </button>
              ))}
            </div>
            <span className="subtle">
              Switching packs replaces the rule set below. You'll see what's coming first.
            </span>
          </div>
        </section>

        {data && <RulesCard rules={data.rules} />}
        {data && <DisclosureCard />}

        <AccountCard />
      </div>

      <ConfirmDialog
        open={pendingPack !== null}
        title={`Switch to ${incoming?.name ?? "this pack"}?`}
        confirmLabel="Replace my rules"
        danger
        busy={applyPack.isPending}
        onCancel={() => setPendingPack(null)}
        onConfirm={() =>
          pendingPack &&
          applyPack.mutate(pendingPack, {
            onSuccess: () => {
              setPendingPack(null);
              toast.show("Content policy updated");
            },
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.detail : "Couldn't switch packs"),
          })
        }
      >
        <p className="dialog__text">
          This replaces your current {data?.rules.length ?? 0} rules with the{" "}
          {incoming?.rules.length ?? 0} below. Any rules you wrote yourself will be lost.
        </p>
        <div className="rule-preview">
          {incoming?.rules.map((rule) => (
            <div key={rule.id} className="stack" style={{ gap: "var(--space-1)" }}>
              <strong>{rule.title}</strong>
              <span className="subtle">{rule.description}</span>
            </div>
          ))}
        </div>
      </ConfirmDialog>
    </DetailPane>
  );
}

/* ------------------------------------------------------------------ rules */

function RulesCard({ rules }: { rules: PolicyRule[] }) {
  const update = useUpdatePolicy();
  const toast = useToast();
  const [draft, setDraft] = useState<PolicyRule[] | null>(null);

  const current = draft ?? rules;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(rules);

  const set = (index: number, patch: Partial<PolicyRule>) => {
    const next = [...current];
    next[index] = { ...next[index]!, ...patch };
    setDraft(next);
  };

  const save = () =>
    update.mutate(
      { rules: current },
      {
        onSuccess: () => {
          setDraft(null);
          toast.show("Rules saved");
        },
        onError: (error) =>
          toast.error(
            error instanceof ApiError
              ? Object.values(error.fieldErrors).flat().join(" · ") || error.detail
              : "Couldn't save the rules",
          ),
      },
    );

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Rules</span>
        <Button
          size="sm"
          onClick={() =>
            setDraft([
              ...current,
              { id: `rule_${current.length + 1}`, title: "", description: "" },
            ])
          }
        >
          + Add rule
        </Button>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
        {current.map((rule, index) => (
          <div key={index} className="rule">
            <div className="stack" style={{ gap: "var(--space-3)", flex: 1 }}>
              <div className="rule__head">
                <TextInput
                  mono
                  value={rule.id}
                  placeholder="rule_id"
                  onChange={(e) => set(index, { id: e.target.value })}
                  style={{ width: 180 }}
                />
                <TextInput
                  value={rule.title}
                  placeholder="Short title"
                  onChange={(e) => set(index, { title: e.target.value })}
                />
              </div>
              <Textarea
                rows={2}
                value={rule.description}
                placeholder="What the rule means in practice."
                onChange={(e) => set(index, { description: e.target.value })}
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDraft(current.filter((_, i) => i !== index))}
            >
              Remove
            </Button>
          </div>
        ))}

        <span className="subtle">
          Rule ids are lowercase letters, digits and underscores, and must be unique.
        </span>

        {dirty && (
          <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
            <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>
              Discard
            </Button>
            <Button variant="primary" size="sm" loading={update.isPending} onClick={save}>
              Save rules
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- disclosure */

function DisclosureCard() {
  const policy = usePolicy();
  const update = useUpdatePolicy();
  const toast = useToast();
  const data = policy.data!;

  const [role, setRole] = useState<string | null>(null);
  const [disclosure, setDisclosure] = useState<string | null>(null);
  const [disclaimer, setDisclaimer] = useState<string | null>(null);

  const currentRole = role ?? data.author_role;
  const currentDisclosure = disclosure ?? data.disclosure;
  const currentDisclaimer = disclaimer ?? data.blog_disclaimer;

  const dirty =
    currentRole !== data.author_role ||
    currentDisclosure !== data.disclosure ||
    currentDisclaimer !== data.blog_disclaimer;

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Disclosure</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
        <Field label="Posts are written by the">
          <Segmented
            value={currentRole}
            onChange={setRole}
            ariaLabel="Author role"
            options={[
              { value: "founder", label: "Founder" },
              { value: "marketing team", label: "Marketing team" },
              { value: "company", label: "Company" },
            ]}
          />
        </Field>

        <Field
          label="Disclosure line"
          hint="{role} and {project} are filled in automatically."
        >
          <TextInput
            value={currentDisclosure}
            onChange={(e) => setDisclosure(e.target.value)}
          />
          <div className="banner banner--info">{data.disclosure_preview}</div>
        </Field>

        <Field label="Blog disclaimer" hint="Optional — appended to every blog post.">
          <Textarea
            rows={2}
            value={currentDisclaimer}
            onChange={(e) => setDisclaimer(e.target.value)}
          />
        </Field>

        {dirty && (
          <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setRole(null);
                setDisclosure(null);
                setDisclaimer(null);
              }}
            >
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={update.isPending}
              onClick={() =>
                update.mutate(
                  {
                    author_role: currentRole,
                    disclosure: currentDisclosure,
                    blog_disclaimer: currentDisclaimer,
                  },
                  {
                    onSuccess: () => {
                      setRole(null);
                      setDisclosure(null);
                      setDisclaimer(null);
                      toast.show("Disclosure saved");
                    },
                  },
                )
              }
            >
              Save
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- account */

function AccountCard() {
  const [theme, setTheme] = useTheme();
  const logout = useLogout();

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Account</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
        <Field label="Theme">
          <Segmented<Theme>
            value={theme}
            onChange={setTheme}
            ariaLabel="Theme"
            options={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
              { value: "system", label: "System" },
            ]}
          />
        </Field>

        <div>
          <Button variant="danger" loading={logout.isPending} onClick={() => logout.mutate()}>
            Sign out
          </Button>
        </div>
      </div>
    </section>
  );
}
