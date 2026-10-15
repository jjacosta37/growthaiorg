/**
 * A blog draft's pull request: Create PR, the open PR's link, Update PR after an edit,
 * and why a PR was held or failed (with Retry). Only rendered once GitHub is connected
 * or a PR exists (`draft.pull_request` is null otherwise).
 */

import { useToast } from "../../components/feedback";
import { Button } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { usePullRequestAction } from "../../lib/queries";
import type { DraftDetail } from "../../lib/types";

export function PullRequestCard({ draft }: { draft: DraftDetail }) {
  const pr = draft.pull_request;
  const toast = useToast();
  const create = usePullRequestAction(draft.id, "create");
  const update = usePullRequestAction(draft.id, "update");
  if (!pr) return null;

  const run = (action: typeof create, started: string) =>
    action.mutate(undefined, {
      onSuccess: () => toast.show(started),
      onError: (error) => toast.error(error instanceof ApiError ? error.detail : "Couldn't reach Luka"),
    });

  const hasPr = pr.number !== null;
  const failed = pr.state === "failed";

  return (
    <div className="card">
      <div className="card__header">
        <span className="card__title">Pull request</span>
        {hasPr && pr.url && (
          <a href={pr.url} target="_blank" rel="noopener noreferrer">
            #{pr.number} on GitHub
          </a>
        )}
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-3)" }}>
        {pr.busy ? (
          <span className="subtle">{hasPr ? "Updating the pull request…" : "Opening a pull request…"}</span>
        ) : hasPr ? (
          <span className="subtle">
            PR open in {pr.repo}. Merge it on GitHub, then mark this draft posted.
          </span>
        ) : (
          <span className="subtle">
            {pr.repo ? `Opens a pull request in ${pr.repo}.` : "Opens a pull request in your repository."}
          </span>
        )}

        {pr.note && (
          <div className={failed ? "banner banner--danger" : "banner banner--warning"} role="status">
            {pr.note}
          </div>
        )}

        {!hasPr && (
          <Button
            variant="primary"
            disabled={!pr.can_create}
            loading={create.isPending || (pr.busy && !hasPr)}
            onClick={() => run(create, "Opening a pull request")}
          >
            {failed ? "Retry" : "Create PR"}
          </Button>
        )}

        {hasPr && (pr.needs_update || failed) && (
          <>
            {pr.needs_update && <span className="subtle">This draft changed since it was pushed.</span>}
            <Button
              disabled={!pr.can_update}
              loading={update.isPending || pr.busy}
              onClick={() => run(update, "Updating the pull request")}
            >
              {failed ? "Retry update" : "Update PR"}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
