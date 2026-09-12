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
      <circle cx="12.5" cy="12" r="4.3" fill={BRAND.coral} />
      <circle cx="24.5" cy="9.5" r="3.1" fill={BRAND.salmon} />
      <circle cx="35" cy="13" r="3.5" fill={BRAND.teal} />
      <circle cx="9.5" cy="24" r="3.1" fill={BRAND.salmon} />
      <circle cx="22" cy="23.5" r="5.2" fill={BRAND.coral} />
      <circle cx="35.5" cy="25.5" r="4.2" fill={BRAND.teal} />
      <circle cx="13.5" cy="35.5" r="3.6" fill={BRAND.teal} />
      <circle cx="26.5" cy="36.5" r="3.1" fill={BRAND.salmon} />
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
