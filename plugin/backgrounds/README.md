# backgrounds/

Optional backdrop images for the topic views. Drop any `.png` (or `.jpg`/`.webp`)
here and it appears in the in-app **backdrop** picker (top-right); the server lists
this folder at `GET /api/backgrounds` and serves each file at `/backgrounds/<name>`.

- **Empty folder = the generated canvas scene** (nebula + ringed planet + starfield)
  stays the default. Nothing here is required.
- Filenames become the picker labels (`violet-nebula.png` -> "violet nebula").
- Images should be **mostly transparent** so topic nodes stay legible over them -
  the shipped set is dark space art with luminance-keyed alpha (only the bright
  nebula/stars register; black space is nearly clear).

## The shipped set

~38 backdrops rendered locally with FLUX, in two moods to pick favorites from:

- **Deep-space** (24): nebulae, galaxies, a ringed planet, deep fields, a
  supernova remnant, a comet, ...
- **Anime / light-novel** (14): pastel nebulae, a great glowing moon, aurora, a
  cherry-blossom cosmos, ink-wash sumi-e space, a celestial rift, a cosmic whale,
  a torii gate against the galaxy, floating lanterns, ...

All post-processed to brighter-but-low-alpha RGBA (colors pop, dark space fades
to clear). They are candidates, not commitments - delete any you dislike, or add
your own (any image type: png / jpg / webp / ...).

## Regenerating / adding your own

The render + transparency script lives with the build notes; the transparency
recipe is: darken to ~0.72 brightness, then set per-pixel alpha to
`clamp(30 + luminance*0.9, 0, 120)` of 255 so the file never blocks the nodes.
Any tool that produces a dark, mostly-transparent wide PNG works - the app only
cares that the file is here.
