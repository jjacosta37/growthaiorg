/**
 * Settings → GitHub: connect a repository for blog pull requests, choose where posts go
 * and how their frontmatter fields are named, with a live preview of the header a post
 * gets. The install happens on GitHub; it sends the browser back here with ?github=.
 */

import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ConfirmDialog, useToast } from "../../components/feedback";
import { Button, Field, IconButton, Select, TextInput } from "../../components/primitives";
import { ApiError, summarise } from "../../lib/api";
import {
  useConnectGitHub,
  useDisconnectGitHub,
  useFrontmatterPreview,
  useGitHub,
  useGitHubRepos,
  useSaveGitHubSettings,
} from "../../lib/queries";
import type { ConstantField, FrontmatterField, GitHubConnection } from "../../lib/types";

const FIELD_LABEL: Record<FrontmatterField, string> = {
  title: "Title",
  description: "Meta description",
  slug: "Slug",
  keywords: "Keywords",
  date: "Date",
};

type ConstantType = "text" | "number" | "boolean";

interface ConstantRow {
  key: string;
  type: ConstantType;
  value: string;
}

function toRow(c: ConstantField): ConstantRow {
  if (typeof c.value === "boolean") return { key: c.key, type: "boolean", value: String(c.value) };
  if (typeof c.value === "number") return { key: c.key, type: "number", value: String(c.value) };
  return { key: c.key, type: "text", value: c.value };
}

function fromRow(row: ConstantRow): ConstantField {
  if (row.type === "boolean") return { key: row.key.trim(), value: row.value === "true" };
  if (row.type === "number") return { key: row.key.trim(), value: Number(row.value) || 0 };
  return { key: row.key.trim(), value: row.value };
}

export function GitHubCard() {
  const github = useGitHub();
  const connect = useConnectGitHub();
  const toast = useToast();
  const location = useLocation();
  const navigate = useNavigate();

  // The result of the GitHub round trip rides back in the query string; show it once.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const result = params.get("github");
    if (!result) return;
    if (result === "connected") toast.show("GitHub connected. Choose a repository below.");
    else if (result === "requested")
      toast.show("Install requested. An organisation owner has to approve it on GitHub.");
    else toast.error(params.get("github_error") || "Couldn't connect GitHub");
    navigate(location.pathname, { replace: true });
  }, [location.pathname, location.search, navigate, toast]);

  const startConnect = () =>
    connect.mutate(undefined, {
      onError: (error) => toast.error(error instanceof ApiError ? error.detail : "Couldn't start connecting"),
    });

  const data = github.data;
  const conn = data?.connection ?? null;

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">GitHub pull requests</span>
        {conn && <span className="subtle">{conn.account}</span>}
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
        {data && !data.available ? (
          <span className="subtle">
            GitHub isn't set up on this Luka server yet. Whoever runs it needs to register the GitHub
            App first.
          </span>
        ) : !conn ? (
          <>
            <span className="subtle">
              Connect the repository your blog lives in, and Luka can open each blog post as a pull
              request. You pick which repositories Luka can see on GitHub's own screen. Luka never
              merges: you review and merge on GitHub.
            </span>
            <div>
              <Button variant="primary" loading={connect.isPending} onClick={startConnect}>
                Connect GitHub
              </Button>
            </div>
          </>
        ) : (
          <>
            {conn.status === "needs_reconnect" && (
              <div className="banner banner--danger" role="status">
                Luka lost access to this repository on GitHub (the app was removed, suspended or its
                access changed).{" "}
                <Button size="sm" loading={connect.isPending} onClick={startConnect}>
                  Reconnect
                </Button>
              </div>
            )}
            <GitHubSettingsForm key={JSON.stringify(conn)} conn={conn} fields={data?.standard_fields ?? []} />
          </>
        )}
      </div>
    </section>
  );
}

function GitHubSettingsForm({ conn, fields }: { conn: GitHubConnection; fields: FrontmatterField[] }) {
  const repos = useGitHubRepos(conn.status !== "needs_reconnect");
  const save = useSaveGitHubSettings();
  const disconnect = useDisconnectGitHub();
  const preview = useFrontmatterPreview();
  const toast = useToast();

  const [repo, setRepo] = useState(conn.repo);
  const [branch, setBranch] = useState(conn.base_branch);
  const [folder, setFolder] = useState(conn.folder);
  const [names, setNames] = useState<Record<string, string>>({ ...conn.field_names });
  const [constants, setConstants] = useState<ConstantRow[]>(conn.constant_fields.map(toRow));
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [error, setError] = useState("");

  const body = useMemo(
    () => ({
      folder,
      field_names: names,
      constant_fields: constants.filter((c) => c.key.trim()).map(fromRow),
    }),
    [folder, names, constants],
  );

  // Live preview of the header a post would get, debounced while typing.
  const { mutate: runPreview } = preview;
  useEffect(() => {
    const timer = window.setTimeout(() => runPreview(body), 400);
    return () => window.clearTimeout(timer);
  }, [body, runPreview]);

  const previewError =
    preview.error instanceof ApiError ? summarise(preview.error.fieldErrors) || preview.error.detail : "";

  const chooseRepo = (name: string) => {
    setRepo(name);
    const found = repos.data?.find((r) => r.full_name === name);
    if (found) setBranch(found.default_branch);
  };

  const onSave = () => {
    setError("");
    save.mutate(
      { repo, base_branch: branch, ...body },
      {
        onSuccess: () => toast.show("GitHub settings saved"),
        onError: (e) =>
          setError(e instanceof ApiError ? summarise(e.fieldErrors) || e.detail : "Couldn't save"),
      },
    );
  };

  const unprotected = conn.status === "ready" && !conn.base_branch_protected;

  return (
    <>
      {conn.status === "incomplete" && (
        <div className="banner banner--info">Choose a repository and branch, then save to finish connecting.</div>
      )}

      <Field label="Repository" error={repos.isError && repos.error instanceof ApiError ? repos.error.detail : undefined}>
        <Select value={repo} onChange={(e) => chooseRepo(e.target.value)} disabled={!repos.data}>
          <option value="">{repos.isLoading ? "Loading…" : "Choose a repository"}</option>
          {repos.data?.map((r) => (
            <option key={r.full_name} value={r.full_name}>
              {r.full_name}
            </option>
          ))}
          {repo && !repos.data?.some((r) => r.full_name === repo) && <option value={repo}>{repo}</option>}
        </Select>
      </Field>

      <div className="row-flex" style={{ gap: "var(--space-3)", alignItems: "flex-start" }}>
        <Field label="Base branch" hint="The branch your site deploys from. PRs target it.">
          <TextInput mono value={branch} onChange={(e) => setBranch(e.target.value)} />
        </Field>
        <Field label="Folder" hint="Where posts go, e.g. content/blog. Empty means the repository root.">
          <TextInput mono value={folder} onChange={(e) => setFolder(e.target.value)} />
        </Field>
      </div>

      {unprotected && (
        <div className="banner banner--warning" role="status">
          {conn.base_branch} isn't protected on GitHub. Luka only writes to its own luka/ branches, but
          GitHub can't limit an app to that. Protect {conn.base_branch} (Settings → Branches on GitHub,
          require a pull request) so nothing, Luka included, can push to it or merge without review.
        </div>
      )}

      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <strong>Frontmatter field names</strong>
        <span className="subtle">Rename a field if your site expects a different name.</span>
        <div className="row-flex" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
          {fields.map((f) => (
            <Field key={f} label={FIELD_LABEL[f]}>
              <TextInput
                mono
                value={names[f] ?? f}
                onChange={(e) => setNames({ ...names, [f]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </div>

      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <strong>Fields added to every post</strong>
        <span className="subtle">For example an author, a layout, or a featured flag set to false.</span>
        {constants.map((c, i) => (
          <div key={i} className="row-flex" style={{ gap: "var(--space-2)", alignItems: "center" }}>
            <TextInput
              mono
              placeholder="name"
              value={c.key}
              onChange={(e) => setConstants(constants.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
            />
            <Select
              value={c.type}
              onChange={(e) =>
                setConstants(
                  constants.map((x, j) =>
                    j === i
                      ? { ...x, type: e.target.value as ConstantType, value: e.target.value === "boolean" ? "false" : "" }
                      : x,
                  ),
                )
              }
            >
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="boolean">True/false</option>
            </Select>
            {c.type === "boolean" ? (
              <Select
                value={c.value}
                onChange={(e) =>
                  setConstants(constants.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </Select>
            ) : (
              <TextInput
                placeholder="value"
                inputMode={c.type === "number" ? "decimal" : undefined}
                value={c.value}
                onChange={(e) =>
                  setConstants(constants.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
              />
            )}
            <IconButton label="Remove field" onClick={() => setConstants(constants.filter((_, j) => j !== i))}>
              ×
            </IconButton>
          </div>
        ))}
        {constants.length < 10 && (
          <div>
            <Button size="sm" onClick={() => setConstants([...constants, { key: "", type: "text", value: "" }])}>
              Add a field
            </Button>
          </div>
        )}
      </div>

      <Field label="Preview" hint={preview.data?.from_draft ? "From your latest blog draft" : "With a sample post"}>
        {previewError ? (
          <div className="banner banner--danger">{previewError}</div>
        ) : (
          <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
            {preview.data ? `${preview.data.path}\n---\n${preview.data.frontmatter}---` : "…"}
          </pre>
        )}
      </Field>

      {error && <div className="banner banner--danger">{error}</div>}

      <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "space-between" }}>
        <Button variant="ghost" onClick={() => setConfirmDisconnect(true)}>
          Disconnect
        </Button>
        <Button variant="primary" loading={save.isPending} disabled={!repo || !branch.trim()} onClick={onSave}>
          Save
        </Button>
      </div>

      <ConfirmDialog
        open={confirmDisconnect}
        title="Disconnect GitHub?"
        confirmLabel="Disconnect"
        danger
        busy={disconnect.isPending}
        onCancel={() => setConfirmDisconnect(false)}
        onConfirm={() =>
          disconnect.mutate(undefined, {
            onSuccess: () => {
              setConfirmDisconnect(false);
              toast.show("GitHub disconnected");
            },
            onError: () => toast.error("Couldn't disconnect"),
          })
        }
      >
        <p className="dialog__text">
          Luka stops opening pull requests and the Content Agent goes back to manual. Pull requests and
          branches already on GitHub stay as they are. To remove Luka's access entirely, uninstall the app
          on GitHub too.
        </p>
      </ConfirmDialog>
    </>
  );
}
