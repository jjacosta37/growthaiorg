/** Buttons, keyboard hints, form controls. Ported from "Luka Components.dc.html". */

import {
  forwardRef,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/* --------------------------------------------------------------- button */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  block?: boolean;
  /** Keyboard hint rendered as a kbd chip inside the button, e.g. "C". */
  shortcut?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, block, shortcut, children, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cx(
        "btn",
        `btn--${variant}`,
        size !== "md" && `btn--${size}`,
        block && "btn--block",
        className,
      )}
      disabled={rest.disabled || loading}
      {...rest}
    >
      {loading && <span className="btn__spinner" aria-hidden />}
      {children}
      {shortcut && !loading && <Kbd>{shortcut}</Kbd>}
    </button>
  );
});

export const IconButton = forwardRef<HTMLButtonElement, ButtonProps & { label: string }>(
  function IconButton({ label, children, className, ...rest }, ref) {
    return (
      <button
        ref={ref}
        type="button"
        aria-label={label}
        title={label}
        className={cx("btn", "btn--icon", className)}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

/* ----------------------------------------------------------------- field */

export interface FieldProps {
  label?: string;
  hint?: string;
  error?: string | string[];
  children: ReactNode;
  htmlFor?: string;
}

export function Field({ label, hint, error, children, htmlFor }: FieldProps) {
  const messages = Array.isArray(error) ? error : error ? [error] : [];
  return (
    <div className="field">
      {label && (
        <label className="field__label" htmlFor={htmlFor}>
          {label}
        </label>
      )}
      {children}
      {hint && !messages.length && <span className="field__hint">{hint}</span>}
      {messages.map((message, i) => (
        <span className="field__error" key={i}>
          {message}
        </span>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- inputs */

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  mono?: boolean;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { invalid, mono, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cx("input", invalid && "input--invalid", mono && "input--mono", className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ invalid, className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={cx("textarea", invalid && "textarea--invalid", className)}
        aria-invalid={invalid || undefined}
        {...rest}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select ref={ref} className={cx("select", className)} {...rest}>
        {children}
      </select>
    );
  },
);

/** A number input sized for the small config fields in the agent pages. */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  disabled,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  disabled?: boolean;
}) {
  return (
    <TextInput
      type="number"
      className="input input--sm"
      value={String(value)}
      min={min}
      max={max}
      disabled={disabled}
      onChange={(e) => {
        const next = Number(e.target.value);
        if (!Number.isNaN(next)) onChange(next);
      }}
    />
  );
}

/* ---------------------------------------------------------------- toggle */

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="toggle__track">
        <span className="toggle__thumb" />
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}

/* ----------------------------------------------------- segmented control */

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel?: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className={cx(
            "segmented__option",
            option.value === value && "segmented__option--active",
          )}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- slider */

export function Slider({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  disabled,
}: {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <div className="slider">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="slider__value">{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------ chip input */

export function ChipInput({
  values,
  onChange,
  placeholder = "Add and press Enter",
  disabled,
  /** Normalises each entry as it is added, e.g. forcing an "r/" prefix. */
  transform,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  transform?: (raw: string) => string;
}) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const commit = () => {
    const raw = draft.trim();
    if (!raw) return;
    const value = transform ? transform(raw) : raw;
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div className="chips" onClick={() => inputRef.current?.focus()}>
      {values.map((value) => (
        <span className="chip" key={value}>
          {value}
          {!disabled && (
            <button
              type="button"
              className="chip__remove"
              aria-label={`Remove ${value}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(values.filter((v) => v !== value));
              }}
            >
              ×
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <input
          ref={inputRef}
          className="chips__input"
          value={draft}
          placeholder={values.length ? "" : placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
        />
      )}
    </div>
  );
}

/** Competitors are {name, url} pairs rather than plain strings. */
export function CompetitorChips({
  values,
  onChange,
}: {
  values: { name: string; url: string }[];
  onChange: (next: { name: string; url: string }[]) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  const add = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onChange([...values, { name: trimmed, url: url.trim() }]);
    setName("");
    setUrl("");
  };

  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      <div className="chips">
        {values.map((competitor, index) => (
          <span className="chip" key={`${competitor.name}-${index}`}>
            {competitor.name}
            {competitor.url && <span className="subtle">{competitor.url}</span>}
            <button
              type="button"
              className="chip__remove"
              aria-label={`Remove ${competitor.name}`}
              onClick={() => onChange(values.filter((_, i) => i !== index))}
            >
              ×
            </button>
          </span>
        ))}
        {!values.length && <span className="subtle">No competitors yet</span>}
      </div>
      <div className="row-flex" style={{ gap: "var(--space-2)" }}>
        <TextInput
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <TextInput
          placeholder="https://"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button onClick={add} disabled={!name.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- counter */

/**
 * "243 / 280", turning warning then danger as the limit approaches.
 * The X pane relies on this to show the over-limit state.
 */
export function CharCounter({ count, limit }: { count: number; limit: number }) {
  const ratio = limit > 0 ? count / limit : 0;
  const tone = count > limit ? "danger" : ratio >= 0.9 ? "warning" : null;
  return (
    <span className={cx("counter", tone && `counter--${tone}`)}>
      {count} / {limit}
    </span>
  );
}

/* ------------------------------------------------------------------ tabs */

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          className={cx("tab", tab.value === value && "tab--active")}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- tooltip */

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="tooltip-host"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && (
        <span className="tooltip" role="tooltip" id={id}>
          {label}
        </span>
      )}
    </span>
  );
}
