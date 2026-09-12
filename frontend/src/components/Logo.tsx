// The product's mark and wordmark.
//
// The mark is a loose cluster of dots — rooms on a board, people in a
// building, whichever you like — in the two brand colours. It is drawn as SVG
// so it stays crisp at 16px in a browser tab and at 40px in the sidebar.
//
// The WORDMARK is deliberately HTML text, not SVG text: an SVG <text> needs
// the font to exist wherever it is rendered, and this one has to sit beside
// the app's own type at whatever size the shell gives it. Two spans coloured
// by brand tokens do that, and stay selectable and translatable.

import { BRAND } from '../lib/brand'

export function LogoMark({
  size = 28,
  title,
}: {
  size?: number
  title?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg"
      role={title === undefined ? 'presentation' : 'img'}
      aria-hidden={title === undefined ? true : undefined}
      aria-label={title}
      className="shrink-0"
    >
      {title !== undefined && <title>{title}</title>}
      <circle cx="13.9" cy="12.8" r="3.8" fill={BRAND.coral} />
      <circle cx="25.9" cy="10.3" r="3.8" fill={BRAND.salmon} />
      <circle cx="36.4" cy="13.8" r="3.8" fill={BRAND.teal} />
      <circle cx="10.9" cy="24.8" r="3.8" fill={BRAND.salmon} />
      <circle cx="23.4" cy="24.3" r="3.8" fill={BRAND.coral} />
      <circle cx="36.9" cy="26.3" r="3.8" fill={BRAND.teal} />
      <circle cx="14.9" cy="36.3" r="3.8" fill={BRAND.teal} />
      <circle cx="27.9" cy="37.3" r="3.8" fill={BRAND.salmon} />
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
        <span className="text-lg font-bold leading-none tracking-tight">
          <span style={{ color: BRAND.coral }}>Open</span>{' '}
          <span style={{ color: BRAND.teal }}>Hospitality</span>
        </span>
      )}
    </span>
  )
}
