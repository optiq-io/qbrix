// generated from asset/logo/svg/{mark,brick}.svg — keep the geometry in sync there.
// the bowl is a circle of radius r; the stem is tangent to it at x = cx + r.

type LogoProps = {
  size?: number;
  className?: string;
};

/**
 * The bare letterform. Inherits `currentColor`, so it takes the surrounding text
 * color. Use where the mark stands alone.
 */
export function QbrixMark({ size = 24, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <g stroke="currentColor" strokeWidth={4} strokeLinecap="round">
        <circle cx="16" cy="12.75" r="8" />
        <path d="M24 4.75V27.25" />
      </g>
    </svg>
  );
}

/**
 * The mark set into a brick — three rounded corners and one square corner at
 * bottom-right, where the descender exits. Use wherever the mark sits beside the
 * "qbrix" wordmark, or needs to fill a square.
 *
 * Both colors are fixed on purpose: the accent scores 1.25:1 against white, so
 * it can only ever be the ground, never the ink. Painting the counter rather than
 * knocking it out keeps the tile legible on any background.
 */
export function QbrixBrick({ size = 24, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M8 0H24A8 8 0 0 1 32 8V32H8A8 8 0 0 1 0 24V8A8 8 0 0 1 8 0Z"
        fill="#C4F82A"
      />
      <g fill="none" stroke="#0A0A0A" strokeWidth={3} strokeLinecap="round">
        <circle cx="16" cy="12.8" r="6" />
        <path d="M22 6.8V24.6" />
      </g>
    </svg>
  );
}
