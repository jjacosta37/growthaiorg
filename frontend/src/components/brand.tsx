/**
 * The Helmly mark: a ship's helm — circle, eight spokes, centre hub.
 * Drawn with currentColor so it works on light, dark and accent backgrounds.
 */

export function HelmMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden focusable="false">
      <circle cx="14" cy="14" r="9" stroke="currentColor" strokeWidth="2" />
      <path
        d="M14 3V7M14 21V25M3 14H7M21 14H25M6.5 6.5L9.3 9.3M21.5 6.5L18.7 9.3M6.5 21.5L9.3 18.7M21.5 21.5L18.7 18.7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="14" cy="14" r="2.5" fill="currentColor" />
    </svg>
  );
}

/** The mark in its rounded accent tile, as used in the sidebar and on login. */
export function HelmTile({ size = 20 }: { size?: number }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.25),
        background: "var(--color-accent)",
        color: "var(--color-on-accent)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <HelmMark size={Math.round(size * 0.55)} />
    </span>
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
      }}
    >
      Helmly
    </span>
  );
}

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <span className="row-flex" style={{ gap: "var(--space-2)" }}>
      <HelmTile size={size} />
      <Wordmark size={Math.round(size * 0.8)} />
    </span>
  );
}
