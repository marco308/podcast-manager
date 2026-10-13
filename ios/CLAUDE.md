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

- Version and build number live only in `project.yml` (`MARKETING_VERSION`, `CURRENT_PROJECT_VERSION` on the app target); `Info.plist` references them, so a bump is one edit. Bump `CURRENT_PROJECT_VERSION` before every upload.
- Archive and upload to TestFlight: see the `ios-testflight` skill (`../.claude/skills/ios-testflight/SKILL.md`).
- App Store listing text, screenshots and the non-file answers (App Privacy, age rating…): `AppStore/README.md`. The app is **iPhone-only** (`TARGETED_DEVICE_FAMILY: "1"`) until someone checks the iPad layouts and adds an iPad screenshot set.

## Key Patterns

**API scope (parity with the web app):**

The app covers everything the web app does for playlists: creating, editing and deleting them (`PlaylistFormSheet`, including the Spotify-link picker from `GET /api/playlists/spotify-playlists`), adding/removing/reordering podcasts, each podcast's per-playlist rule (`AssignmentRuleSheet`) and running them. Plus browsing and syncing podcasts, toggling `is_sequential`, and viewing/changing the job schedule. The one backend endpoint it deliberately leaves out:

| Backend endpoint not wrapped by `APIClient` | Why |
|---|---|
| `DELETE /api/podcasts/{podcast_id}` (unfollow) | Unfollowing is a Spotify-side action; do it in the Spotify app or the web UI |

If one of these is ever wanted on iOS, it is a plain addition to `APIClient` (the backend needs no change) plus the corresponding screen. Update this table when that happens.

**Demo mode (issue #264):**

"Try the demo" on the login screen runs the whole app against `DemoBackend`, an in-memory actor with a fictional library (artwork generated into `Resources/DemoArtwork/`). It exists so App Review, and anyone without a server, can use the app: the real sign-in needs a self-hosted backend plus a Spotify account that the backend's Spotify app has allowlisted. `APIClient` checks `demo` at the top of every public call, so **a new `APIClient` method needs a matching `DemoBackend` method** or the demo will hit `makeRequest` and fail with "No server configured". `DemoBackend` mirrors backend rules that a reviewer can see (rule resolution, disabled playlists refusing a run). Demo state isn't persisted: a relaunch returns to login, and Exit Demo in Settings leaves it. Use the demo for App Store screenshots, since the shows are made up.

**Podcast Model:**
- Custom `init(from:)` decoder with defaults for missing fields
- Handles both `/api/podcasts` (full schema with `playlist_ids`, `created_at`) and `/api/playlists/{id}/podcasts` (subset with `position`, the resolved `rule` and the raw `override`, no `playlist_ids`)
- `PlaylistDraft` always encodes `spotify_playlist_id`, as `null` when unlinked, for the same reason: on `PATCH /api/playlists/{id}` an absent key keeps the old link
- `Playlist.kind` is optional (nil = standard, from servers before sleep playlists). Change a draft's kind with `PlaylistDraft.setKind(_:)`, which applies the sleep presets (shuffle / random / 10) or turns `random` back into `newest`, as the server and web form do. `random` is offered only on sleep playlists, and a sleep playlist ignores the sequential hint (`DemoBackend` mirrors both)
- The rule sheet always PATCHes both override keys, with `null` for "inherit": the backend treats present-and-null as clear and an absent key as leave alone

## Gotchas

- Use `Color.accentColor` not `.accent` for foreground styles (`.accent` doesn't exist as a ShapeStyle)
- XcodeGen auto-includes new `.swift` files in existing directories, but you must run `xcodegen generate` for the `.xcodeproj` to update
- After building, wipe DerivedData if the simulator runs stale code: `rm -rf ~/Library/Developer/Xcode/DerivedData/PodcastManager-*`
- App icon must have no alpha channel (App Store rejects it)
- `ITSAppUsesNonExemptEncryption: false` is set to skip the export compliance prompt
- `PrivacyInfo.xcprivacy` must declare every required-reason API the app itself calls (currently `UserDefaults`, reason `CA92.1`, for the server URL). Update it if you add another (file timestamps, disk space, boot time…)
- Notification permission is requested when the user starts a sync or run, not at launch — keep it that way so the prompt has context
- The App Store privacy policy lives at `site/privacy.html`; keep it in step if the app starts storing or sending anything new
