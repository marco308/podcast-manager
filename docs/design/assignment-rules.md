# Per-assignment episode rules

Status: accepted, 2026-09-22. Supersedes the `episode_mode` / `ordering_mode` model.
Tracking: #249 (umbrella), closes #236, #237, #244; reframes #243.

## Why

The old model put "what a show contributes" on the playlist (`episode_mode`) and
"which end of a show to take from" on the podcast (`is_sequential`), and then
mixed both into a four-way `ordering_mode`. That could not express the common
case: a Morning playlist of daily news shows (latest episode each, in a fixed
order) plus one story podcast that should contribute its *next unfinished*
episode. "Latest only" and "next unfinished" are the same rule, one episode per
show, with a different direction. The rule belongs on the assignment.

## Model

Three levels, each owning one thing.

| Level | Owns | Fields |
|---|---|---|
| Assignment (`playlist_podcasts`) | what this show contributes to this playlist | `position`, `episode_limit` (nullable override), `pick_from` (nullable override) |
| Playlist | defaults for new rows, and how contributions are assembled | `default_episode_limit`, `default_pick_from`, `arrangement`, `date_direction`, `is_enabled`, `is_weekend_only` |
| Podcast | an intrinsic hint | `is_sequential` |

### Field semantics

- `episode_limit`: integer, `0` means *all unplayed*, `n >= 1` means *at most n*.
  On the assignment `NULL` means *inherit from the playlist*. Stored as the same
  encoding at both levels so there is no separate "all" sentinel.
- `pick_from`: `newest` or `oldest`. Which end of the show's unplayed episodes to
  take from when limited, and the order the show's episodes are listened to.
  `NULL` on the assignment means *inherit*.
- `arrangement`: `by_position` (groups in assignment order), `by_date`
  (all contributed episodes merged by release date) or `shuffle` (shows
  interleaved at random, each show's episodes kept in its rule's order).
- `date_direction`: `newest_first` or `oldest_first`. Only used by `by_date`.

### Resolution

One function, `resolve_rule(playlist, podcast, assignment)`, used by the builder
and by the API so the UI shows exactly what the build will do:

```
limit = assignment.episode_limit  if set   -> source "override"
      else playlist.default_episode_limit  -> source "playlist"

pick  = assignment.pick_from      if set   -> source "override"
      else "oldest" if podcast.is_sequential -> source "sequential"
      else playlist.default_pick_from      -> source "playlist"
```

The API returns both the resolved rule and the raw override on every assignment
row, so the UI can show "Latest, newest (playlist default)" versus "Oldest
(custom)" and offer "reset to default". Changing a playlist default moves every
unrefined row; refined rows stay put. No cascading is done at write time.

## Build algorithm

```
for each assignment in position order (NULL positions last, then by name):
    rule = resolve_rule(...)
    episodes = fetch_unplayed(show, need=rule.limit or all, from=rule.pick)
    order within show: oldest->newest if rule.pick == oldest else newest->oldest
    if rule.limit: episodes = episodes[:rule.limit]
    groups.append(episodes)

if arrangement == by_position:
    result = concat(groups)
elif arrangement == shuffle:
    tokens = shuffle([group index, once per episode])
    result = [next episode of groups[i] for i in tokens]  # random interleave, per-show order kept
else:  # by_date
    result = merge(groups) sorted by (release_date, show_id) in date_direction
    for each show resolved to pick == oldest with >= 2 slots:
        refill its slots oldest-first   # a serial is never played out of order
```

`oldest` is a hard within-show guarantee; `newest` is a preference that the
playlist's date direction may override. That asymmetry is deliberate: playing
a serial out of order is harmful, playing news out of order is not.

### Fetching

Spotify returns show episodes newest-first with a `total`. Fetch cost is kept
proportional to the rule:

- `pick_from = newest`, limit `n`: walk pages from offset 0, stop once `n`
  unplayed episodes are in hand.
- `pick_from = oldest`, limit `n`: read the first page for `total`, then walk
  pages backwards from the tail, stop once `n` unplayed are in hand.
- limit `0` (all): walk from offset 0 up to the 500-episode cap, as before.

`podcast.unplayed_episodes` is only written when the walk saw the whole
catalogue (issue #155); a short walk never overwrites it.

## Migration (014)

| Old | New |
|---|---|
| `episode_mode = latest_only` | `default_episode_limit = 1` |
| `episode_mode = all_unplayed` | `default_episode_limit = 0` |
| `ordering_mode = DEFAULT` | `arrangement = by_date`, direction `newest_first` if latest_only else `oldest_first` |
| `ordering_mode = CHRONOLOGICAL_ASC` | `by_date`, `oldest_first` |
| `ordering_mode = CHRONOLOGICAL_DESC` | `by_date`, `newest_first` |
| `ordering_mode = PODCAST_ORDER` | `by_position` |
| (all) | `default_pick_from = newest`; assignment overrides `NULL` |

Existing sequential shows keep oldest-first through the `is_sequential` hint,
so no assignment overrides are written by the migration. The old columns are
dropped. Downgrade recreates them from the new values with the reverse mapping.

## API

- `GET/POST/PATCH /api/playlists`: `episode_mode` and `ordering_mode` are
  replaced by `arrangement`, `date_direction`, `default_episode_limit`,
  `default_pick_from`.
- `GET /api/playlists/{id}/podcasts`: each row gains
  `rule: {episode_limit, pick_from, episode_limit_source, pick_from_source}`
  and `override: {episode_limit, pick_from}` (each nullable).
- `PATCH /api/playlists/{id}/podcasts/{podcast_id}`: body
  `{episode_limit?: int | null, pick_from?: "newest" | "oldest" | null}`.
  A field that is present and `null` clears that override; an absent field is
  left alone. Returns the updated row.
- `POST /api/playlists/{id}/podcasts` is unchanged: rows are added with no
  overrides, so they follow the playlist defaults.

## UI

Web:

- Playlist form: Arrangement (in podcast order / by release date), Direction
  (shown for by-date), Default episodes per podcast (all unplayed / latest only /
  up to N), Take from (newest / oldest).
- New `/playlists/:id` detail page: settings summary with edit, membership list
  with drag-to-reorder always available (with a note when the arrangement is by
  date), a per-row rule tag with an inline editor and "reset to default", add and
  remove. The "Playlist Custom Ordering" card on the list page goes away.
- Podcasts page multi-select stays and adds with defaults.
- Settings → About loses the stale Features block (#244).

iOS stays read-mostly (see `ios/CLAUDE.md`): the models and labels move to the
new fields and each playlist row shows its resolved rule. Rule editing is
web-only for now.

## Out of scope

- Reconcile-style rebuilds. Cleanup stays a pure "remove played" job; a
  one-episode row empties once finished and refills at the next rebuild.
- Weekend and enabled semantics (#238, #239) stay playlist-level schedule
  rules and are unchanged by this design.
