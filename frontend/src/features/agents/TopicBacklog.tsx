/** Content's topic backlog, plus the "Request a topic" form. */

import { useState } from "react";

import { EmptyState, useToast } from "../../components/feedback";
import { Button, ChipInput, Field, Segmented, TextInput, Textarea } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { useDraftTopic, useRejectTopic, useRequestTopic, useTopics } from "../../lib/queries";
import type { BlogTopicStatus } from "../../lib/types";

export function TopicBacklog() {
  const [status, setStatus] = useState<BlogTopicStatus>("proposed");
  const topics = useTopics(status);
  const draftTopic = useDraftTopic();
  const rejectTopic = useRejectTopic();
  const toast = useToast();

  const items = topics.data?.results ?? [];

  return (
    <>
      <section className="card">
        <div className="card__header">
          <span className="card__title">Topic backlog</span>
          <Segmented<BlogTopicStatus>
            value={status}
            onChange={setStatus}
            ariaLabel="Topic status"
            options={[
              { value: "proposed", label: "Proposed" },
              { value: "drafted", label: "Drafted" },
              { value: "rejected", label: "Rejected" },
            ]}
          />
        </div>

        <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
          {items.length ? (
            items.map((topic) => (
              <div key={topic.id} className="topic">
                <div className="stack" style={{ gap: "var(--space-2)", flex: 1 }}>
                  <div className="row-flex" style={{ gap: "var(--space-2)" }}>
                    <strong>{topic.title}</strong>
                    {topic.requested_by_user && (
                      <span className="badge badge--neutral">You asked for this</span>
                    )}
                  </div>
                  {topic.angle && <span className="muted">{topic.angle}</span>}
                  {topic.why && <span className="subtle">{topic.why}</span>}
                  {!!topic.target_keywords.length && (
                    <div className="row-flex" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
                      {topic.target_keywords.map((keyword) => (
                        <span className="chip" key={keyword}>
                          {keyword}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {status === "proposed" && (
                  <div className="row-flex" style={{ gap: "var(--space-2)" }}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        rejectTopic.mutate(topic.id, {
                          onSuccess: () => toast.show("Topic rejected"),
                        })
                      }
                    >
                      Reject
                    </Button>
                    <Button
                      size="sm"
                      onClick={() =>
                        draftTopic.mutate(topic.id, {
                          onSuccess: () => toast.show("Drafting started"),
                          onError: (error) =>
                            toast.error(
                              error instanceof ApiError ? error.detail : "Couldn't start",
                            ),
                        })
                      }
                    >
                      Draft
                    </Button>
                  </div>
                )}
              </div>
            ))
          ) : (
            <EmptyState
              title={`No ${status} topics`}
              body={
                status === "proposed"
                  ? "The agent proposes topics on its next run, or you can request one below."
                  : undefined
              }
            />
          )}
        </div>
      </section>

      <RequestTopicForm />
    </>
  );
}

function RequestTopicForm() {
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const request = useRequestTopic();
  const toast = useToast();

  const submit = (draftNow: boolean) => {
    if (!title.trim()) return;
    request.mutate(
      {
        title: title.trim(),
        angle: angle.trim(),
        target_keywords: keywords,
        draft_now: draftNow,
      },
      {
        onSuccess: (result) => {
          setTitle("");
          setAngle("");
          setKeywords([]);
          toast.show(result.run ? "Drafting started" : "Added to the backlog");
        },
        onError: (error) => {
          // A 409 still saves the topic — the run is what couldn't start.
          if (error instanceof ApiError && error.isConflict) {
            setTitle("");
            setAngle("");
            setKeywords([]);
            toast.show(error.detail);
          } else {
            toast.error(error instanceof ApiError ? error.detail : "Couldn't save the topic");
          }
        },
      },
    );
  };

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Request a topic</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
        <Field label="Title">
          <TextInput
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Running retrospectives, step by step"
          />
        </Field>

        <Field label="Angle" hint="Optional — how you want it approached.">
          <Textarea rows={2} value={angle} onChange={(e) => setAngle(e.target.value)} />
        </Field>

        <Field label="Keywords">
          <ChipInput values={keywords} onChange={setKeywords} placeholder="Add a keyword" />
        </Field>

        <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
          <Button disabled={!title.trim()} loading={request.isPending} onClick={() => submit(false)}>
            Add to backlog
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim()}
            loading={request.isPending}
            onClick={() => submit(true)}
          >
            Draft now
          </Button>
        </div>
      </div>
    </section>
  );
}
