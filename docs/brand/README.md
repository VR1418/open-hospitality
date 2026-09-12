# Brand assets

`logo/` is the supplied logo kit, copied here unchanged so the app's assets
have a source that travels with the code.

## What the app uses

| | From |
|---|---|
| Browser tab | `logo/vector/favicon.svg`, copied verbatim to `frontend/public/favicon.svg` |
| Sidebar | `frontend/src/components/Logo.tsx` — the mark's geometry and the palette come from `frontend/src/lib/brand.ts`, which mirrors `logo/vector/mark.svg` and `logo/vector/brand-colors.json` |
| Tray icon | `src/usali/desktop/app.py` `_icon_image`, drawn from `logo/vector/app-icon.svg`'s numbers |

The mark is six equal circles on a ring. The kit ships two palettes — one for
light backgrounds, a brighter one for dark — and the app remaps them as CSS
variables in `index.css`, so the mark follows the theme without the component
knowing which is on.

## Two things worth knowing about the kit

**The lockup SVGs carry no typeface.** `logo-primary.svg`, `logo-reversed.svg`,
`logo-black.svg` and `logo-white.svg` use `<text>` with `class="wm"` and
`class="tag"`, an empty `<defs>`, and no `font-family` anywhere. So they render
in whatever the viewer's default font is — which is why the PNGs beside them
came out in a serif rather than the **Space Grotesk Bold** that
`brand-colors.json` names. The app therefore does not use those SVGs: it draws
the mark from the geometry and sets the wordmark as HTML text in the app's own
typeface. To get Space Grotesk exactly, the font would have to be bundled with
the app (it cannot be fetched at runtime — the product works offline).

**The wordmark in the kit is "ophosp", with "Open Hospitality" as a
descriptor.** The product uses **Open Hospitality** alone, at the owner's
direction, so the `ophosp` lockups and the double-bar divider are not used.
