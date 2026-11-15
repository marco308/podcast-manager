---
version: 1
slug: "frontend-src"
primary_target: "frontend/src"
related_targets: []
---

# Web app (frontend/)

Mode: Operate. Audience: the one self-hoster who runs this install. Jobs, in order: check last night's runs, sort newly followed shows into playlists, run a rebuild now. Constraints: Ant Design stays underneath (restyled through tokens and component overrides), light and dark themes both ship, iOS stays native and takes only colour and type. Colours are free except the Marcus Lab brown grounds, which are ruled out; Outfit + DM Mono are the family link.

Chosen direction: The Parts List (decision round, kind pick). Memorable moment: every playlist reads as a numbered bill of materials, each show a ballooned part with its resolved rule as the spec and a lamp for its state.

## Direction contract

THESIS: Each playlist is an assembly and its shows are numbered parts; the resolved rule is the part's spec. Refuses the stat-card dashboard with a generic table underneath.

OWN-WORLD: Dark: cool graphite ground #16191D, panels #1F2328, off-white ink #EEF0F2, Marcus Lab orange #E8590C as the one signal (primary action, current nav, serial/custom specs, focus). Light: cool sheet grey #F2F3F5, white panels, graphite ink, orange deepened to #C24A08 for text. Square-cornered panels with a 3px edge, 1.5px rules, 1px dotted row dividers; pill buttons; round balloons ringed blue (#62A3EA dark / #2F6FC4 light), amber ring for sequential. Outfit 700 uppercase for names and headings, DM Mono uppercase tracked labels and specs. Status as lamp + word: green OK, amber partial, red failed, dark lamp off.

STORY: Opening the app answers "did last night work?" from the run sheet before anything is clicked, then shows each playlist's parts so a wrong rule or unreachable show is visible in its row; Update all and Sync are one click away.

FIRST VIEWPORT: Left sidebar (nameplate with mark, Overview, Podcasts, Playlists, Settings; current item orange inset bar). Main: mono kicker "RUN SHEET · <date>", H1 "OVERVIEW" in Outfit uppercase with Sync library (outline pill) and Update all (orange pill) right-aligned, a 3px rule under it; a four-cell run sheet strip (last run, next run, partial/failed count, unsorted shows); then playlist assemblies in a two-column grid, each a 3px-edged panel headed by name + lamp + arrangement, rows of ballooned parts.

FORM: Parts list / bill of materials, position 1 of my ordered grounded list (IMPECCABLE'S PICK, chosen by the user over the roll). seed:4e7a44fe9cb6abf4

Signature interaction: a part row expands in place (native details/summary) to show where each half of its rule comes from and whether the show has left Spotify. Motion: each assembly panel is wiped in with a clip (sine in-out, 900ms, staggered) on load, the Marcus Lab "wipe a fill with a clip" draw-in, chosen over per-line strokes because the panels are Ant-rendered boxes, not SVG paths; reduced-motion shows them static.

Deviation (craft floor): no kicker above the H1. The date sits as a mono line under "Run sheet".

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
