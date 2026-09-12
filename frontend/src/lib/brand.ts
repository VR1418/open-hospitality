// The brand's colours, from the logo kit's own brand-colors.json.
//
// Exposed as CSS variables rather than literals (see index.css) because the
// kit ships TWO palettes: one for light backgrounds and a brighter one for
// dark, where the light reds and teals go muddy against near-black. Naming
// them here keeps the component from knowing which theme is on.
//
// In its own module rather than beside the Logo component: a module that
// exports components cannot also export a plain object without breaking Fast
// Refresh for every component in it (`react/only-export-components`), the
// same reason badgeTones lives apart from ui.tsx.

export const BRAND = {
  red: 'var(--brand-red)',
  orange: 'var(--brand-orange)',
  teal: 'var(--brand-teal)',
  tealSoft: 'var(--brand-teal-soft)',
  pink: 'var(--brand-pink)',
  pinkSoft: 'var(--brand-pink-soft)',
} as const

/** The mark: six equal circles on a 132-unit ring, clockwise from the top.
 *  Copied from the kit's mark.svg so the app, the browser tab and the tray
 *  icon cannot drift apart. */
export const MARK_DOTS = [
  { cx: 66, cy: 20, fill: BRAND.red },
  { cx: 106, cy: 43, fill: BRAND.orange },
  { cx: 106, cy: 89, fill: BRAND.teal },
  { cx: 66, cy: 112, fill: BRAND.tealSoft },
  { cx: 26, cy: 89, fill: BRAND.pink },
  { cx: 26, cy: 43, fill: BRAND.pinkSoft },
] as const

export const MARK_RADIUS = 14
export const MARK_VIEWBOX = 132
