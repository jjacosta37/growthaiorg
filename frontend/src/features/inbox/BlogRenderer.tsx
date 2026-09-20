/** Blog post: the article as formatted reading, with an SEO side panel. */

import { Markdown } from "../../components/markdown";
import { useToast } from "../../components/feedback";
import {
  Button,
  CharCounter,
  ChipInput,
  Field,
  TextInput,
  Textarea,
} from "../../components/primitives";
import type { BlogPostContent, DraftDetail } from "../../lib/types";

const TITLE_GUIDE = 60;
const META_LIMIT = 160;

export function BlogRenderer({
  draft,
  content,
  editing,
  onChange,
}: {
  draft: DraftDetail;
  content: BlogPostContent;
  editing: boolean;
  onChange: (next: BlogPostContent) => void;
}) {
  const toast = useToast();
  const set = <K extends keyof BlogPostContent>(key: K, value: BlogPostContent[K]) =>
    onChange({ ...content, [key]: value });

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(content.body_md);
      toast.show("Copied as markdown");
    } catch {
      toast.error("Couldn't copy");
    }
  };

  return (
    <div className="blog">
      <article className="blog__article">
        {editing ? (
          <Field label="Body (markdown)">
            <Textarea
              rows={24}
              className="md-editor__area"
              value={content.body_md}
              onChange={(e) => set("body_md", e.target.value)}
            />
          </Field>
        ) : (
          <>
            <h1 style={{ fontSize: "var(--text-2xl)", lineHeight: "var(--leading-tight)" }}>
              {content.title}
            </h1>
            <Markdown>{content.body_md}</Markdown>
          </>
        )}
      </article>

      <aside className="blog__panel">
        <div className="card">
          <div className="card__header">
            <span className="card__title">SEO</span>
            <Button size="sm" onClick={() => void copyMarkdown()}>
              Copy as markdown
            </Button>
          </div>
          <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
            <Field
              label="Title"
              hint={`${content.title.length} characters — ${TITLE_GUIDE} is the guide`}
            >
              {editing ? (
                <TextInput value={content.title} onChange={(e) => set("title", e.target.value)} />
              ) : (
                <div className="muted">{content.title}</div>
              )}
            </Field>

            <Field label="Meta description">
              {editing ? (
                <Textarea
                  rows={3}
                  value={content.meta_description}
                  onChange={(e) => set("meta_description", e.target.value)}
                />
              ) : (
                <div className="muted">{content.meta_description}</div>
              )}
              <CharCounter count={content.meta_description.length} limit={META_LIMIT} />
            </Field>

            <Field label="Slug">
              {editing ? (
                <TextInput mono value={content.slug} onChange={(e) => set("slug", e.target.value)} />
              ) : (
                <div className="mono subtle">{content.slug}</div>
              )}
            </Field>

            <Field label="Keywords">
              {editing ? (
                <ChipInput
                  values={content.keywords}
                  onChange={(next) => set("keywords", next)}
                  placeholder="Add a keyword"
                />
              ) : (
                <div className="row-flex" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
                  {content.keywords.length ? (
                    content.keywords.map((keyword) => (
                      <span className="chip" key={keyword}>
                        {keyword}
                      </span>
                    ))
                  ) : (
                    <span className="subtle">None</span>
                  )}
                </div>
              )}
            </Field>

            {draft.blog_topic?.angle && (
              <Field label="Angle">
                <div className="muted">{draft.blog_topic.angle}</div>
              </Field>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
