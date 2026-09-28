/**
 * The Luka mark: a rocket tilted 45° on a rounded tile, from the Luka brand guide.
 * The window, fins and flame echo the X, Content and Reddit channel colors. The tile
 * switches with the theme through the --brand-* tokens; the rocket never changes.
 * Always drawn on its tile, never bare.
 */

export function RocketMark({ size = 20, withWindow = size > 16 }: { size?: number; withWindow?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden
      focusable="false"
      style={{ flexShrink: 0, display: "block" }}
    >
      <rect width="32" height="32" rx="8" fill="var(--brand-tile)" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" stroke="var(--brand-tile-border)" />
      <g transform="translate(16 16) scale(0.7) rotate(45) translate(-16 -16)">
        <path d="M12.5 23.5H19.5L16 30Z" fill="var(--brand-rocket-flame)" />
        <path d="M10 16.5L6 20.5V25L10 22Z M22 16.5L26 20.5V25L22 22Z" fill="var(--brand-rocket-fins)" />
        <path d="M16 3C20.5 6.5 22 11.5 22 17V22H10V17C10 11.5 11.5 6.5 16 3Z" fill="var(--brand-rocket-body)" />
        {/* At 16px and below the window is dropped so the mark stays legible. */}
        {withWindow && <circle cx="16" cy="13" r="2.6" fill="var(--brand-rocket-window)" />}
      </g>
    </svg>
  );
}

/** Wordmark: Archivo 700, tight tracking, per the brand guide. */
export function Wordmark({ size = 20 }: { size?: number }) {
  return (
    <span
      style={{
        fontSize: size,
        fontWeight: 700,
        letterSpacing: "-0.02em",
        lineHeight: 1,
        color: "var(--color-text)",
      }}
    >
      Luka
    </span>
  );
}

/** The lockup: icon and wordmark, spaced at 0.35× the icon size. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <span className="row-flex" style={{ gap: Math.round(size * 0.35) }}>
      <RocketMark size={size} />
      <Wordmark size={Math.round(size * 0.8)} />
    </span>
  );
}
