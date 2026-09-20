/** Markdown rendering and the edit/preview editor from the components sheet. */

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button, Segmented } from "./primitives";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

type Mode = "edit" | "preview";

/**
 * Textarea plus a react-markdown preview, as specified in the plan. `dirty` is
 * computed against `value` so the Save button only lights up on a real change.
 */
export function MarkdownEditor({
  value,
  onSave,
  saving,
  readOnlyNote,
}: {
  value: string;
  onSave: (next: string) => void;
  saving?: boolean;
  readOnlyNote?: string;
}) {
  const [mode, setMode] = useState<Mode>("preview");
  const [draft, setDraft] = useState(value);
  const [editingOf, setEditingOf] = useState(value);

  // The document changed underneath us (regenerated, or another tab): follow it,
  // unless there are unsaved edits, which would be lost.
  if (value !== editingOf && draft === editingOf) {
    setDraft(value);
    setEditingOf(value);
  }

  const dirty = draft !== value;

  return (
    <div className="md-editor">
      <div className="md-editor__toolbar">
        <Segmented<Mode>
          value={mode}
          onChange={setMode}
          ariaLabel="Editor mode"
          options={[
            { value: "edit", label: "Edit" },
            { value: "preview", label: "Preview" },
          ]}
        />
        <div className="row-flex" style={{ gap: "var(--space-3)" }}>
          {readOnlyNote && <span className="subtle">{readOnlyNote}</span>}
          {dirty && (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft(value);
                  setEditingOf(value);
                }}
              >
                Discard
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={saving}
                onClick={() => {
                  onSave(draft);
                  setEditingOf(draft);
                }}
              >
                Save
              </Button>
            </>
          )}
        </div>
      </div>

      {mode === "edit" ? (
        <textarea
          className="md-editor__area"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck
        />
      ) : (
        <div style={{ minHeight: 320 }}>
          {draft.trim() ? (
            <Markdown>{draft}</Markdown>
          ) : (
            <p className="subtle">Nothing here yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
