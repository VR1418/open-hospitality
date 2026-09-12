// The product's mark and wordmark, from the supplied logo kit.
//
// The mark is six equal circles on a ring — the kit's own geometry, kept in
// `lib/brand` so this component, the browser tab and the desktop tray icon are
// drawn from one set of numbers.
//
// The WORDMARK is HTML text, not SVG text. Two reasons, and the second is the
// kit's own lesson: an SVG <text> needs the font to exist wherever it renders,
// and the kit's lockup SVGs set no font-family at all — which is why the PNGs
// shipped with them came out in a serif rather than the Space Grotesk their
// brand-colors.json names. Text in the app's own typeface cannot go wrong that
// way, and stays selectable, translatable and crisp at any size.

import { BRAND, MARK_DOTS, MARK_RADIUS, MARK_VIEWBOX } from '../lib/brand'

export function LogoMark({ size = 28, title }: { size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      xmlns="http://www.w3.org/2000/svg"
      role={title === undefined ? 'presentation' : 'img'}
      aria-hidden={title === undefined ? true : undefined}
      aria-label={title}
      className="shrink-0"
    >
      {title !== undefined && <title>{title}</title>}
      {MARK_DOTS.map((dot) => (
        <circle
          key={`${dot.cx}-${dot.cy}`}
          cx={dot.cx}
          cy={dot.cy}
          r={MARK_RADIUS}
          fill={dot.fill}
        />
      ))}
    </svg>
  )
}

/** Mark and wordmark together. `compact` drops the wordmark, for a collapsed
 *  sidebar — the name then lives in the caller's screen-reader text. */
export function Logo({ size = 28, compact = false }: { size?: number; compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <LogoMark size={size} />
      {!compact && (
        <span
          className="text-lg font-bold leading-none"
          // The kit's wordmark tracking. Tight, so the two words read as one.
          style={{ letterSpacing: '-0.03em' }}
        >
          <span style={{ color: BRAND.red }}>Open</span>{' '}
          <span style={{ color: BRAND.teal }}>Hospitality</span>
        </span>
      )}
    </span>
  )
}
