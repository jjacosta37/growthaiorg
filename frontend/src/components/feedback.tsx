/** Empty, error and loading states; toasts; dialogs; menus; the progress timeline. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { RunEventLevel } from "../lib/types";
import { Button, cx } from "./primitives";

/* ----------------------------------------------------------------- states */

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <div className="state">
      <div className="state__title">{title}</div>
      {body && <div className="state__body">{body}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Couldn't load this",
  body,
  onRetry,
}: {
  title?: string;
  body?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state state--error">
      <div className="state__title">{title}</div>
      {body && <div className="state__body">{body}</div>}
      {onRetry && (
        <Button onClick={onRetry} size="sm">
          Retry
        </Button>
      )}
    </div>
  );
}

export function Skeleton({
  width = "100%",
  height = 12,
  radius,
}: {
  width?: number | string;
  height?: number | string;
  radius?: string;
}) {
  return (
    <div
      className="skeleton"
      style={{ width, height, borderRadius: radius ?? "var(--radius-sm)" }}
      aria-hidden
    />
  );
}

/** The inbox list placeholder from "Global States". */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="rows" aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="row"
          style={{ cursor: "default", gap: "var(--space-3)", alignItems: "center" }}
        >
          <div className="row__main">
            <Skeleton width={72} height={14} radius="var(--radius-full)" />
            <Skeleton width={`${70 + ((i * 7) % 25)}%`} height={12} />
          </div>
          <Skeleton width={24} height={10} />
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div
      className="stack"
      style={{ gap: "var(--space-4)", padding: "var(--space-6)" }}
      aria-busy
    >
      <Skeleton width={110} height={16} radius="var(--radius-full)" />
      <Skeleton width="80%" height={20} />
      <Skeleton width="100%" height={80} radius="var(--radius-md)" />
      <Skeleton width="92%" height={12} />
      <Skeleton width="86%" height={12} />
      <Skeleton width="70%" height={12} />
    </div>
  );
}

/* ----------------------------------------------------------------- toasts */

interface Toast {
  id: number;
  message: string;
  tone: "default" | "error";
  action?: { label: string; onClick: () => void };
}

interface ToastApi {
  show: (message: string, options?: { tone?: Toast["tone"]; action?: Toast["action"] }) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback<ToastApi["show"]>(
    (message, options) => {
      const id = nextId.current++;
      setToasts((current) => [
        ...current,
        { id, message, tone: options?.tone ?? "default", action: options?.action },
      ]);
      window.setTimeout(() => dismiss(id), options?.action ? 8000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({ show, error: (message) => show(message, { tone: "error" }) }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={cx("toast", toast.tone === "error" && "toast--error")}>
            <span>{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                className="toast__action"
                onClick={() => {
                  toast.action?.onClick();
                  dismiss(toast.id);
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

/* ----------------------------------------------------------------- dialog */

export function Dialog({
  open,
  title,
  children,
  onClose,
  actions,
  wide,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  onClose: () => void;
  actions: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className={cx("dialog", wide && "dialog--wide")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog__body">
          <div className="dialog__title">{title}</div>
          {children}
        </div>
        <div className="dialog__actions">{actions}</div>
      </div>
    </div>
  );
}

/** The plain "are you sure" case, used by re-crawl and pack switching. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  danger,
  onConfirm,
  onCancel,
  children,
  busy,
}: {
  open: boolean;
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  busy?: boolean;
}) {
  return (
    <Dialog
      open={open}
      title={title}
      onClose={onCancel}
      actions={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {body && <p className="dialog__text">{body}</p>}
      {children}
    </Dialog>
  );
}

/* ------------------------------------------------------------------- menu */

export interface MenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  hint?: string;
}

/** A dropdown anchored to its trigger. Closes on outside click and Escape. */
export function DropdownMenu({
  trigger,
  items,
  align = "left",
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  items: (MenuItem | "separator")[];
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!hostRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={hostRef} style={{ position: "relative", display: "inline-flex" }}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div
          className="menu"
          role="menu"
          style={{ top: "calc(100% + 4px)", [align]: 0 }}
        >
          {items.map((item, index) =>
            item === "separator" ? (
              <div className="menu__separator" key={`sep-${index}`} />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={cx("menu__item", item.danger && "menu__item--danger")}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                <span>{item.label}</span>
                {item.hint && <span className="subtle mono">{item.hint}</span>}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------- progress timeline */

export interface TimelineStep {
  id: string | number;
  level: RunEventLevel;
  message: string;
  /** The step currently in progress: shows a spinner rather than an icon. */
  active?: boolean;
  /** Not started yet: dimmed, from the onboarding design's "pending" state. */
  pending?: boolean;
}

const LEVEL_ICON: Record<RunEventLevel, string> = {
  info: "·",
  success: "✓",
  warning: "⚠",
  error: "✕",
};

export function ProgressTimeline({ steps }: { steps: TimelineStep[] }) {
  return (
    <div className="timeline">
      {steps.map((step) => (
        <div
          key={step.id}
          className={cx(
            "timeline__step",
            `timeline__step--${step.level}`,
            step.active && "timeline__step--active",
            step.pending && "timeline__step--pending",
          )}
        >
          <span className="timeline__icon" aria-hidden>
            {step.active ? <span className="timeline__spinner" /> : LEVEL_ICON[step.level]}
          </span>
          <span className="timeline__message">{step.message}</span>
        </div>
      ))}
    </div>
  );
}
