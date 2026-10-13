# Sleep playlists

Status: built, 2026-10-13 (backend, web and iOS build 11).
Tracking: #331

## Why

Falling asleep to a podcast wants the opposite of every other playlist: episodes
you have **already heard**, so nothing is missed and nothing new keeps you
awake. Every build today keeps only unplayed episodes (`_is_unplayed`), and the
cleanup job removes anything fully played every 30 minutes. A Sleep playlist
is a second kind of playlist that inverts the first and is exempt from the
second.

## Model

One new column on `playlists`:

| Field | Values | Default |
|---|---|---|
| `kind` | `standard` / `sleep` | `standard` |

A plain string column, like `arrangement`, plus a migration (next in the single
chain). "Sleep" is the UI's name for the kind; the playlist's own name is free,
so several sleep playlists can coexist. `kind` can be changed after creation:
every rebuild is a full replace, so the next run simply builds the other kind.

Everything else carries over unchanged: assignments, `position`,
`episode_limit`, `arrangement`, `is_enabled`, the Spotify link rules, and the
refusal to write an empty list when every show failed to fetch (#145).

### Defaults for a new sleep playlist

- `arrangement`: `shuffle`
- `default_pick_from`: `random` (new, see below)
- `default_episode_limit`: `10` (at most 10 per show; overridable per assignment)

## What a sleep build picks

**Eligible:** a playable, unrestricted episode that is either `fully_played`
on Spotify now, **or** in the sleep ledger.

Partially played episodes are not eligible unless the ledger has them: you
haven't heard the ending, which is not what you want at bedtime.

### `pick_from = random`

A third `PickFrom` value. The build reads the whole catalogue (up to
`MAX_EPISODES_PER_SHOW`) and takes a fresh random sample of `episode_limit`
eligible episodes on every rebuild, so the playlist rotates nightly. For a
sleep playlist the `is_sequential` hint is ignored when resolving `pick_from`
(order is irrelevant when you are asleep): override, else playlist default.

`random` is only offered on sleep playlists in v1. Both UIs only offer it there,
and the API rejects it on a standard playlist with a 422.

## The sleep ledger

**Problem (verified 2026-10-13):** replaying a finished episode on Spotify moves
its resume point, and Spotify then shows it as partially played. So every
episode Sleep serves stops being `fully_played` the first night you fall asleep
to it. Without a ledger:

1. it drops out of the next sleep build, so the pool drains over time, and
2. standard playlists see it as *unplayed* again. A serial set to `oldest`
   would put episode 1 back at the top of the commute playlist.

**Table:** `sleep_episodes(episode_id PK, first_served_at, last_served_at)`.
A row is written for every episode a sleep build **successfully writes** to
Spotify (after `replace_playlist_items`, in the same commit as
`last_updated_at`).

**Rules:**

- Sleep builds treat ledger episodes as eligible, whatever Spotify says now.
- Standard builds **skip** ledger episodes, whatever Spotify says now.
- Only episodes Sleep has served are recorded. An episode you mark unplayed in
  Spotify yourself, to listen again, is untouched and comes back to standard
  playlists as usual.

Known trade-off: an episode Sleep has served can't return to a standard
playlist. If that matters later, add a "forget" action; not in v1.

Like `podcasts`, the table is global (single-user by construction). Account
deletion (`services/account.py`) deletes it alongside `podcasts` when no user
remains.

## Fetching

`_walk_from_head` / `_walk_from_tail` count *unplayed* episodes to decide when
to stop. They take an eligibility predicate instead, so a limited sleep rule
stops once it has enough eligible episodes. `random` always reads the whole
catalogue (it's `need=None`), which costs up to 10 page reads per show, once a day.

`podcast.unplayed_episodes` is written as a by-product of a complete walk. A
sleep build must still count *unplayed* episodes for it (not eligible ones), or
skip the write.

## Cleanup job

`remove_played_episodes_from_playlists` must skip `kind = sleep`, or it would
remove every episode within 30 minutes. Gate it as firmly as `is_enabled`: in
the Phase 1 select and in the locked re-check.

## API and clients

- `kind` on create, `PATCH` (absent leaves alone) and every playlist response.
- `pick_from` / `default_pick_from` accept `random` on sleep playlists only.
- **Web:** kind picker on create and edit, a Sleep tag on the card, hide
  `date_direction`, offer `random` only on sleep.
- **iOS:** `kind` decodes as optional (servers before #331 don't send it).
  `PlaylistFormSheet` has the Standard/Sleep picker with the same presets as
  the web form, `AssignmentRuleSheet` offers Random on sleep playlists only and
  ignores the sequential hint there, and a moon badge marks sleep playlists.
  Builds before 11 decode sleep playlists fine (`pickFrom` is a plain string)
  but show them as standard; their edit sheet sends `random` back unchanged
  unless the pick is edited.
- **Docs:** CLAUDE.md, README and `site/` describe playlists as "unplayed
  only"; add the sleep kind.

## Out of scope for v1

- A total-duration cap ("about 3 hours") instead of a per-show count.
- Avoiding last night's picks in today's random sample.
- A "forget" action on the ledger.

## Build order

1. Backend: `kind` column + migration, cleanup skip, predicate-based walks,
   ledger table and both ledger rules, `random` pick, sleep resolution.
2. Web UI.
3. iOS.
4. Docs and site.

Step 1 on its own is usable: create the playlist via the API and try it for a
week.
