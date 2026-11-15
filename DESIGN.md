---
name: Podcast Manager
description: A self-hosted playlist layer over Spotify, drawn as a parts list - each playlist an assembly, each show a numbered part with its resolved rule as the spec.
colors:
  # Dark theme
  graphite-ground: "#16191D"
  graphite-panel: "#1F2328"
  graphite-raised: "#272C33"
  off-white-ink: "#EEF0F2"
  off-white-ink-secondary: "rgba(238, 240, 242, 0.74)"
  off-white-rule: "rgba(238, 240, 242, 0.22)"
  signal-orange: "#E8590C"
  signal-orange-text: "#FF7A33"
  balloon-blue: "#62A3EA"
  serial-amber: "#F5C12E"
  lamp-green: "#4FE06A"
  lamp-red: "#FF5A4A"
  lamp-off: "#4A5059"
  # Light theme
  sheet-grey: "#F2F3F5"
  sheet-white: "#FFFFFF"
  sheet-raised: "#E8EAEE"
  graphite-ink: "#16191D"
  graphite-ink-secondary: "rgba(22, 25, 29, 0.70)"
  graphite-rule: "rgba(22, 25, 29, 0.22)"
  signal-orange-deep: "#C24A08"
  signal-orange-deep-text: "#B04306"
  balloon-blue-deep: "#2F6FC4"
  serial-amber-deep: "#B07F00"
  lamp-green-deep: "#1E9E4A"
  lamp-red-deep: "#D0312D"
  lamp-off-light: "#B4B9C1"
typography:
  display:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "clamp(34px, 4vw, 52px)"
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  title:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0.02em"
  body:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.5
  label:
    fontFamily: "'DM Mono', ui-monospace, Menlo, monospace"
    fontSize: "12px"
    fontWeight: 400
    letterSpacing: "0.08em"
  button:
    fontFamily: "Outfit, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "13px"
    fontWeight: 600
    letterSpacing: "0.06em"
rounded:
  none: "0px"
  pill: "999px"
  round: "50%"
spacing:
  xs: "8px"
  sm: "12px"
  md: "18px"
  lg: "24px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.graphite-ground}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    height: "36px"
  button-primary-light:
    backgroundColor: "{colors.signal-orange-deep}"
    textColor: "{colors.sheet-white}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    height: "36px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.off-white-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    height: "36px"
  sheet:
    backgroundColor: "{colors.graphite-panel}"
    textColor: "{colors.off-white-ink}"
    rounded: "{rounded.none}"
  sheet-head:
    typography: "{typography.headline}"
    padding: "12px 18px"
  part-row:
    typography: "{typography.title}"
    padding: "11px 18px"
  part-row-open:
    backgroundColor: "{colors.graphite-raised}"
    padding: "4px 18px 16px 62px"
  balloon:
    textColor: "{colors.off-white-ink}"
    rounded: "{rounded.round}"
    size: "28px"
  lamp:
    backgroundColor: "{colors.lamp-green}"
    rounded: "{rounded.round}"
    size: "10px"
  run-sheet-cell:
    backgroundColor: "{colors.graphite-panel}"
    typography: "{typography.figure}"
    padding: "12px 16px"
  problem-line:
    backgroundColor: "{colors.graphite-raised}"
    padding: "10px 18px"
  tag:
    backgroundColor: "transparent"
    rounded: "{rounded.pill}"
    typography: "{typography.label}"
  nav-item-selected:
    backgroundColor: "{colors.graphite-panel}"
    textColor: "{colors.off-white-ink}"
    rounded: "{rounded.none}"
---

# Design System: Podcast Manager

## Overview

**Creative North Star: "The Parts List"**

Every managed playlist is an assembly drawing and every show in it is a numbered part. The part's spec is its resolved rule ("Latest only · newest", "Up to 2 · oldest · sequential"), set in the same mono a drawing uses for callouts, so the screen states exactly what the next rebuild will do. The interface is a bill of materials, not a dashboard: square-cornered sheets with a heavy edge, ballooned numbers, status lamps that always carry their word, and one orange signal.

It is calm, cool and dense. Grounds are graphite (dark) or drawing-sheet grey (light), never warm. Outfit in heavy uppercase names things; DM Mono in tracked uppercase labels and specifies them. Ant Design stays underneath and is restyled entirely through theme tokens and a thin layer of overrides, so every Ant control speaks the same language as the custom part rows. The app belongs to the Marcus Lab family through its mark, its two typefaces and its voice, not through the family's brown palette, and it never looks like an official Spotify product.

The opening view, the Run sheet, answers "did last night work?" from a strip of facts before anything is clicked, then lays out every playlist as an assembly so a wrong rule or an unreachable show is visible in its own row.

**Key Characteristics:**
- Square sheets with a 3px full-ink edge; 1.5px rules between sections; 1px dotted dividers between rows.
- Numbered balloons (blue ring; amber ring for sequential shows; dashed ring when order is not used).
- Status as lamp plus word, never colour alone.
- One orange signal: primary action, current nav, custom and sequential specs, focus.
- Pills for everything you press; squares for everything you read.
- Light and dark themes are equals and both ship.

## Colors

A cool graphite-and-sheet palette with one hot orange signal, a blue drafting accent for balloons, and a three-lamp status set. Each role has a dark value and a light value; the light values are deepened so text and rings hold contrast on white.

### Primary
- **Signal Orange** (dark `signal-orange`, light `signal-orange-deep`): the one signal. Fills the primary pill button (Update all, Make a playlist), draws the 3px inset bar on the current nav item, colours focus outlines, text selection, the caret and switches.
- **Signal Orange Text** (dark `signal-orange-text`, light `signal-orange-deep-text`): orange as legible text: custom and sequential specs in a part row, link hover, the "Sort them" link on the run sheet.

### Secondary
- **Balloon Blue** (dark `balloon-blue`, light `balloon-blue-deep`): the 2px ring of every part balloon, and Ant's info colour. A drafting accent, not a second brand colour; it appears nowhere else.
- **Serial Amber** (dark `serial-amber`, light `serial-amber-deep`): the ring of a sequential show's balloon. The same value is the partial lamp, so amber always means "handled with care", never "go".

### Tertiary (status lamps)
- **Lamp Green** (dark `lamp-green`, light `lamp-green-deep`): OK, contributing.
- **Lamp Red** (dark `lamp-red`, light `lamp-red-deep`): failed; also the run sheet's last-run time when the nightly run failed, and Ant's error colour for destructive actions.
- **Lamp Off** (dark `lamp-off`, light `lamp-off-light`): playlist turned off, or not run yet.

### Neutral
- **Graphite Ground / Sheet Grey** (`graphite-ground` / `sheet-grey`): page, header and sidebar background. Header and sidebar share the ground and are separated from content by a 1.5px rule, not a tone change.
- **Graphite Panel / Sheet White** (`graphite-panel` / `sheet-white`): sheets, cards, tables, modals, the run sheet strip, the selected nav item.
- **Graphite Raised / Sheet Raised** (`graphite-raised` / `sheet-raised`): hover and open state of a part row, the open row's detail panel, the problem line, table row hover.
- **Ink** (`off-white-ink` / `graphite-ink`): all primary text, the 3px sheet edge (as full-strength ink, not a tinted border), outline-button borders.
- **Ink Secondary** (`off-white-ink-secondary` / `graphite-ink-secondary`): labels, publishers, table headers, explanatory copy.
- **Rule** (`off-white-rule` / `graphite-rule`): 1.5px section rules, dotted row dividers, Ant borders, scrollbar thumbs.

### Named Rules
**The One Signal Rule.** Orange marks only what you press next, where you are, and a spec that differs from the default. If two orange fills are on screen, one of them is wrong.

**The Lamp-and-Word Rule.** A status lamp never appears without its word (OK, Partial, Failed, Off, Not run yet) or an accessible label; colour is the second channel, not the only one.

**The Cool Ground Rule.** Grounds are cool graphite or cool grey. The Marcus Lab warm brown grounds are ruled out, and so is Spotify green.

## Typography

**Display Font:** Outfit (variable, self-hosted), with system-ui fallback
**Label/Mono Font:** DM Mono 400 and 500 (self-hosted), with ui-monospace fallback

**Character:** Outfit in heavy uppercase gives each assembly and part a stamped nameplate; DM Mono in wide-tracked uppercase reads as drawing callouts. Body copy stays in Outfit 500 sentence case so explanations remain plain language.

### Hierarchy
- **Display** (700, clamp(34px, 4vw, 52px), line-height 0.95, uppercase, -0.02em): one page title per page (Run sheet, Podcasts, a playlist's name). Balanced wrapping.
- **Headline** (700, 22px, uppercase): an assembly's name in its sheet head; Ant card titles take the same uppercase treatment.
- **Figure** (700, 24px, tabular numerals): the value in each run sheet cell.
- **Title** (700, 15px, uppercase, +0.02em): part and show names in rows, tables and cards, with the publisher beneath in 13px 500 sentence case, secondary ink.
- **Body** (500, 15px, line-height 1.5): explanations, empty states (capped near 52ch), the problem line (14px).
- **Label** (DM Mono 400, 12px, uppercase, +0.08em): field labels, arrangement lines, specs, table headers, statistic titles, the date under the page title. Tags use the same face at 11.5px, +0.06em.
- **Button** (Outfit 600, 13px, uppercase, +0.06em): every button.

### Named Rules
**The Two Voices Rule.** Outfit names, DM Mono specifies. A rule, a state word or a measurement is set in mono; a thing the user owns (a show, a playlist) is set in Outfit uppercase.

**The Tabular Rule.** Numbers that line up (tables, statistics, run sheet figures) use tabular numerals.

## Layout

A fixed-width sidebar (200px) beside a fluid content column. The header spans the top on the ground colour with the Marcus Lab mark (28px, cream on dark, ink on light) and the "Podcast Manager" nameplate in Outfit 700 uppercase. Below the md breakpoint the sidebar is removed and the same nav opens in a 260px left drawer from a header menu button.

Each page opens with its display title; on the Run sheet the title row ends in a 3px full-ink rule with the page's actions (outline Sync library, orange Update all) aligned right to its baseline. Page sections stack with a 24px gap. Assemblies sit in an auto-fill grid with a 460px minimum column and a 28px gap, so two columns on a wide screen and one on a narrow one.

Inside a sheet the rhythm is 18px horizontal padding; heads take 12px vertical, rows 11px, the problem line 10px. Part rows are a four-column grid: balloon (30px), name, spec, and an end cluster of lamp plus chevron, with a 14px gap. Below 768px the spec drops to a second line under the name and the run sheet strip folds from four cells to two by two. Page padding steps 24px to 12px (768px) to 8px (480px), and sheet padding to 12px at 480px. Coarse pointers keep switches at 44px and small buttons at 32px minimum.

## Elevation & Depth

Flat. There are no resting or hover shadows, gradients or glows anywhere in the app. Depth is drawn, not lit: a sheet is separated from the ground by its 3px ink edge, a section by a 1.5px rule, a row by a 1px dotted line, and an active or expanded thing by stepping up one tone to Raised. The one box-shadow in the system is the 3px inset orange bar on the selected nav item, which is a line, not elevation.

### Named Rules
**The Drawn Edge Rule.** If something needs to stand apart, give it an edge or a tone step, never a shadow.

## Shapes

Two shape families, kept strictly apart. Things you read are square: sheets, cards, tables, inputs, menus, modals and nav items all have 0 radius (Ant's base radius is 0). Show artwork is not yet consistent (square in the podcast table, softly rounded on cards and in the drawer and editor) and is not part of this rule until one treatment is chosen. Things you press, and the small markers inside rows, are round: buttons, segmented controls and tags are full pills (999px); balloons and lamps are circles. Line weights carry hierarchy: 3px for an object's outline, 1.5px for a structural rule, 1px dotted for a list divider, 2px for a balloon ring.

### Named Rules
**The Press-Round, Read-Square Rule.** Round corners belong only to pills, balloons and lamps. A panel with a radius is out of system.

## Components

### Buttons
- **Shape:** full pill (999px), 36px default height, uppercase Outfit 600 13px with +0.06em tracking. No shadows.
- **Primary:** Signal Orange fill with ground-coloured text (graphite on dark, white on light). One per view: Update all, Make a playlist.
- **Outline (default):** transparent with a 1px full-ink border and ink text: Sync library, Run, Edit, Open in Spotify.
- **Text / icon:** borderless Ant text buttons for the theme toggle, account menu and mobile nav trigger.
- **Disabled:** Ant's disabled treatment; Run on a turned-off playlist is disabled with a title explaining why.

### Tags
- **Style:** pill, transparent background, DM Mono 11.5px uppercase tracked. Used for show states and counts on podcast cards ("Unassigned", "281 eps").

### Sheets and Cards
- **Corner Style:** square (0).
- **Background:** Panel.
- **Border:** 3px solid full-strength ink. Ant cards and stand-alone tables take the same edge; a table nested in a card drops its own edge so edges never double.
- **Head:** 12px 18px padding, 1.5px rule below, headline type; actions and the status lamp align right.
- **Internal Padding:** 18px horizontal (12px under 480px). A parts list inside a card bleeds edge to edge.

### Inputs / Fields
- **Style:** Ant inputs and selects at 0 radius, 1px Rule border, Panel fill, 36px height, caret in Signal Orange.
- **Focus:** a 2px Signal Orange outline at 3px offset on every focus-visible element (inset to -2px on part rows).

### Navigation
- **Style:** Ant inline menu on the ground colour, Outfit 500 with Ant outline icons. Items: Run sheet, Podcasts, Playlists, Settings.
- **Hover:** Raised tone. **Selected:** Panel tone plus a 3px inset Signal Orange bar on the left edge; nested routes keep their section selected.
- **Mobile:** the same menu in a 260px left drawer.

### Part Row (signature)
The defining component. An ordered list of shows, each a native details/summary row: balloon, name with publisher beneath, spec in mono (orange when the rule is custom or sequential, "Not on Spotify" when the show has left the library), and an end cluster of lamp and a small chevron. Rows divide with 1px dotted rules. Hover and open states step to Raised; opening rotates the chevron 90 degrees and reveals a definition list, indented to align under the name, that says where each half of the rule comes from (playlist default, sequential hint, set on this show) and, for a missing show, what will happen to it.

### Balloon
A 28px circle with a 2px Balloon Blue ring and the part number in DM Mono 500 12px. Amber ring for a sequential show; dashed ring when the playlist's arrangement ignores position (the number stays for reference).

### Lamp
A 10px filled circle: green OK or contributing, amber partial or not on Spotify, red failed, grey off or not run yet. Always beside its word or with an aria-label; the reason sits in a tooltip.

### Run Sheet Strip
One bordered strip (1.5px Rule, Panel fill) of four cells divided by dotted rules: Last run, Next run, Need a look, Unsorted shows. Each cell is a mono label over a 24px figure with an optional mono caption or link beneath. The figure turns red when the nightly run failed and amber when playlists need a look. Folds to two by two under 768px.

### Problem Line
A single Raised-tone line under an assembly's head, between 1.5px rules: a lamp and one sentence saying why the last build did not go cleanly and when. Shown only for an enabled playlist whose last run was partial or failed.

### Motion
Assemblies wipe in left to right with a clip (900ms, sine in-out, staggered 120ms per panel to a 360ms cap) on load; an opened part row's details wipe in over 450ms (ease-out cubic). Row hover and the chevron move in 200ms. All of it is off under reduced motion, where everything renders static.

## Project Page (site/)

The public project page (`site/index.html`) is a separate visual world that predates this redesign and has not been brought into the Parts List system. Don't mix it with the app until it is deliberately redone.

- **Palette:** paper `#EEF1F6`, white surfaces, deep navy ink `#1B2340`, slate muted text `#56607F`, line `#CBD2E1`, marigold `#F2B705` as its one accent, and focus blue `#2F6FEB`. Its dark version moves to navy (`#121831` paper, `#1B2342` surface, marigold `#F5C433`), under `prefers-color-scheme` and `[data-theme]`.
- **Type:** Familjen Grotesk from Google Fonts at 400 to 700; tight display headings (-0.035em, line-height 0.98) and 18px body at 1.55.
- **Shapes:** pill buttons with a 2px ink border; panels with 6 to 12px corners; focus as a 3px outline at 3px offset.
- **App mock-ups** on the page still copy the replaced app look (light Ant styling with Spotify green) and are now out of date.

## Do's and Don'ts

### Do:
- **Do** restyle Ant Design through `themeConfig.ts` tokens and the `.pm-*` vocabulary in `index.css`, keeping the CSS custom properties and the theme palette in step.
- **Do** draw every playlist as a sheet of numbered parts with the resolved rule as each part's spec (The Two Voices Rule).
- **Do** show status as lamp plus word, with the reason in a tooltip or problem line (The Lamp-and-Word Rule).
- **Do** keep orange to the primary action, the current nav item, custom or sequential specs and focus (The One Signal Rule).
- **Do** use a 3px full-ink edge for objects, 1.5px rules for structure and 1px dotted lines between rows.
- **Do** design and check light and dark together; they are equals. iOS takes only these colours and Outfit/DM Mono, through native SwiftUI components.
- **Do** keep every motion behind `prefers-reduced-motion: no-preference`.

### Don't:
- **Don't** round panels, cards, tables or inputs; round is for pills, balloons and lamps only (The Press-Round, Read-Square Rule).
- **Don't** add resting or hover shadows, gradients or glows (The Drawn Edge Rule).
- **Don't** reintroduce the Marcus Lab brown grounds or Spotify green, and never use the Spotify logo, Circular or a Spotify-style layout.
- **Don't** add a second accent: Balloon Blue rings balloons and nothing else.
- **Don't** put a mono kicker or eyebrow above a page title; the date or context line goes beneath it.
- **Don't** bring the project page's navy, marigold or Familjen Grotesk into the app.
