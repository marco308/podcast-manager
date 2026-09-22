# iOS App - CLAUDE.md

## Overview

Native iOS companion app for Podcast Manager. Connects to any Podcast Manager backend — the server URL is entered on the login screen at runtime, with an optional build-time default via `SERVER_URL_DEFAULT` in `Local.yml` (see below).

## Local Setup (one-time)

The `.xcodeproj` is generated, not committed. After cloning:

```bash
cd ios/PodcastManager
cp Local.yml.example Local.yml                        # set DEVELOPMENT_TEAM (+ optional SERVER_URL_DEFAULT)
cp ExportOptions.plist.example ExportOptions.plist    # set teamID (TestFlight/App Store only)
xcodegen generate
```

Both files are gitignored — signing team, default server URL and export team ID never go in committed files. Simulator builds work without a team ID.

## Commands

```bash
cd ios/PodcastManager

# Regenerate Xcode project (after adding/removing files or changing project.yml/Local.yml)
xcodegen generate

```

- Archive and upload to TestFlight: see the `ios-testflight` skill (`../.claude/skills/ios-testflight/SKILL.md`).

## Key Patterns

**API scope (intentionally read-mostly):**

The app is a day-to-day companion, not a second admin UI. It covers browsing and syncing podcasts, toggling `is_sequential`, adding/removing podcasts in an existing playlist, running playlists, and viewing/changing the job schedule. Everything that shapes a playlist is deliberately web-only:

| Backend endpoint not wrapped by `APIClient` | Why |
|---|---|
| `POST /api/playlists` (create) | One-off setup; the web form already validates the defaults/arrangement |
| `PATCH /api/playlists/{id}` (rename, default episode limit / pick-from, arrangement, date direction, enabled) | Same |
| `DELETE /api/playlists/{id}` | Destructive and rare; keep it behind the web confirm dialog |
| `PATCH /api/playlists/{id}/podcasts/{podcast_id}` (per-assignment `episode_limit` / `pick_from` override) | Rule editing is web-only for now; iOS shows the resolved `rule` on each row (see `docs/design/assignment-rules.md`) |
| `PUT /api/playlists/{id}/podcasts/reorder` | Depends on the dnd-kit drag UI; a list-reorder UX on iOS is real work for a rarely-used feature |
| `DELETE /api/podcasts/{podcast_id}` (unfollow) | Unfollowing is a Spotify-side action; do it in the Spotify app or the web UI |

If one of these is ever wanted on iOS, it is a plain addition to `APIClient` (the backend needs no change) plus the corresponding screen. Update this table when that happens.

**Podcast Model:**
- Custom `init(from:)` decoder with defaults for missing fields
- Handles both `/api/podcasts` (full schema with `playlist_ids`, `created_at`) and `/api/playlists/{id}/podcasts` (subset with `position` and the resolved `rule`, no `playlist_ids`)

## Gotchas

- Use `Color.accentColor` not `.accent` for foreground styles (`.accent` doesn't exist as a ShapeStyle)
- XcodeGen auto-includes new `.swift` files in existing directories, but you must run `xcodegen generate` for the `.xcodeproj` to update
- After building, wipe DerivedData if the simulator runs stale code: `rm -rf ~/Library/Developer/Xcode/DerivedData/PodcastManager-*`
- App icon must have no alpha channel (App Store rejects it)
- `ITSAppUsesNonExemptEncryption: false` is set to skip the export compliance prompt
