// The brand's colours, in their own module rather than beside the Logo
// component — a module that exports components cannot also export a plain
// object without breaking Fast Refresh for every component in it
// (`react/only-export-components`), which is the same reason badgeTones lives
// apart from ui.tsx.
//
// Fixed values, not theme tokens: a logo that changed colour with the theme
// would stop being the logo. Kept in step with frontend/public/favicon.svg.

export const BRAND = {
  coral: '#F04E37',
  salmon: '#F4897A',
  teal: '#16A6A0',
} as const
