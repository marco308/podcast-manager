# iOS App - CLAUDE.md

## Overview

Native iOS companion app for Podcast Manager. Connects to any Podcast Manager backend — the server URL is entered on the login screen at runtime, with an optional build-time default via `SERVER_URL_DEFAULT` in `Local.yml` (see below).

## Stack

- **SwiftUI**, iOS 18+, Swift 6 (strict concurrency)
- **XcodeGen** for project generation (`project.yml` → `.xcodeproj`)
- **No third-party dependencies** — URLSession, Keychain, UNUserNotificationCenter

## Local Setup (one-time)

The `.xcodeproj` is generated, not committed. After cloning:

```bash
brew install xcodegen   # if needed
cd ios/PodcastManager
cp Local.yml.example Local.yml   # then set DEVELOPMENT_TEAM (+ optional SERVER_URL_DEFAULT)
cp ExportOptions.plist.example ExportOptions.plist   # then set teamID (TestFlight/App Store only)
xcodegen generate
```

`Local.yml` is a gitignored optional include of `project.yml` — signing team and the baked-in default server URL live there, never in committed files. Simulator builds work without a team ID.

`ExportOptions.plist` is likewise gitignored and holds your `teamID` for `xcodebuild -exportArchive`; you only need it when archiving for TestFlight or the App Store.

## Commands

```bash
cd ios/PodcastManager

# Regenerate Xcode project (after adding/removing files or changing project.yml/Local.yml)
xcodegen generate

# Build
xcodebuild -project PodcastManager.xcodeproj -scheme PodcastManager \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build

# Run tests
xcodebuild test -project PodcastManager.xcodeproj -scheme PodcastManager \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'

# Launch in simulator
xcrun simctl install booted <path-to-.app> && xcrun simctl launch booted com.marcuslab.podcastmanager

# Archive + upload to TestFlight
xcodebuild archive -project PodcastManager.xcodeproj -scheme PodcastManager \
  -archivePath ./build/PodcastManager.xcarchive -destination 'generic/platform=iOS'
xcodebuild -exportArchive -archivePath ./build/PodcastManager.xcarchive \
  -exportPath ./build/export -exportOptionsPlist ExportOptions.plist -allowProvisioningUpdates
xcrun altool --upload-app -f ./build/export/PodcastManager.ipa -t ios \
  --apiKey <YOUR_ASC_KEY_ID> --apiIssuer <YOUR_ASC_ISSUER_ID>
```

## Architecture

```
PodcastManager/
├── App/
│   ├── PodcastManagerApp.swift    # @main entry, environment setup
│   └── AppState.swift             # Tab selection state
├── Models/
│   ├── Podcast.swift              # Custom Codable init (handles full + partial schemas)
│   ├── Playlist.swift             # Also contains MessageResponse
│   └── User.swift
├── Services/
│   ├── APIClient.swift            # Actor-based, URLSession, all API calls
│   ├── AuthService.swift          # Spotify OAuth via ASWebAuthenticationSession
│   ├── ServerConfig.swift         # Backend URL resolution (UserDefaults → Info.plist default)
│   ├── KeychainService.swift      # Session/CSRF token storage
│   └── NotificationService.swift  # Local notifications (background only)
├── Views/
│   ├── ContentView.swift          # Auth gate → TabView
│   ├── Components/
│   │   ├── PodcastRow.swift
│   │   └── PlaylistRow.swift
│   └── Screens/
│       ├── LoginScreen.swift
│       ├── PodcastsScreen.swift   # List + sync
│       ├── PodcastDetailScreen.swift  # Detail + sequential toggle
│       ├── PlaylistsScreen.swift  # List + run all
│       ├── PlaylistDetailScreen.swift # Podcasts in playlist + add/remove
│       ├── AddPodcastsSheet.swift # Multi-select unassigned podcasts
│       └── SettingsScreen.swift   # Account info + sign out
└── Resources/
    ├── Assets.xcassets/           # App icon (1024x1024, no alpha), accent color
    └── PrivacyInfo.xcprivacy
```

## Key Patterns

**Authentication:**
- Spotify OAuth via ASWebAuthenticationSession
- Backend `/api/auth/login?redirect_scheme=podcastmanager` triggers mobile flow
- Callback redirects to `podcastmanager://auth/callback?code=...` with a single-use exchange code
- App trades the code via `POST /api/auth/mobile-exchange`; credentials arrive in the JSON body
- Tokens stored in Keychain, sent as Cookie header + X-CSRF-Token header

**Server URL:**
- `ServerConfig.baseURL`: user-entered URL (UserDefaults) → `DefaultServerURL` Info.plist value → nil
- Login screen has the URL field; `APIClient` throws `.serverNotConfigured` when unset

**API Client:**
- Actor-based singleton (`APIClient.shared`); `init(session:)` accepts an injected `URLSession` so tests can stub the network with a `URLProtocol` (see `PodcastManagerTests/APIClientCsrfRetryTests.swift`)
- Session cookie set manually via `Cookie` header (not URLSession cookie jar)
- CSRF token sent on all non-GET requests
- A 403 whose `detail` mentions CSRF triggers a one-shot recovery: `GET /api/auth/csrf-token`, store the result in the Keychain, retry the original request once. Mirrors the web client's interceptor; a non-CSRF 403, or a second CSRF 403, surfaces as `APIError.httpError`
- Any 401 fires the handler registered by `AuthService`, which clears the Keychain and routes back to the login screen
- Decoder uses `convertFromSnakeCase` key strategy

**API scope (intentionally read-mostly):**

The app is a day-to-day companion, not a second admin UI. It covers browsing and syncing podcasts, toggling `is_sequential`, adding/removing podcasts in an existing playlist, running playlists, and viewing/changing the job schedule. Everything that shapes a playlist is deliberately web-only:

| Backend endpoint not wrapped by `APIClient` | Why |
|---|---|
| `POST /api/playlists` (create) | One-off setup; the web form already validates modes/ordering |
| `PATCH /api/playlists/{id}` (rename, mode, ordering, enabled, weekend-only) | Same |
| `DELETE /api/playlists/{id}` | Destructive and rare; keep it behind the web confirm dialog |
| `PUT /api/playlists/{id}/podcasts/reorder` | Depends on the dnd-kit drag UI; a list-reorder UX on iOS is real work for a rarely-used feature |
| `DELETE /api/podcasts/{spotify_id}` (unfollow) | Unfollowing is a Spotify-side action; do it in the Spotify app or the web UI |

If one of these is ever wanted on iOS, it is a plain addition to `APIClient` (the backend needs no change) plus the corresponding screen. Update this table when that happens.

**Podcast Model:**
- Custom `init(from:)` decoder with defaults for missing fields
- Handles both `/api/podcasts` (full schema with `playlist_ids`, `created_at`) and `/api/playlists/{id}/podcasts` (subset with `position`, no `playlist_ids`)

## Gotchas

- Use `Color.accentColor` not `.accent` for foreground styles (`.accent` doesn't exist as a ShapeStyle)
- XcodeGen auto-includes new `.swift` files in existing directories, but you must run `xcodegen generate` for the `.xcodeproj` to update
- After building, wipe DerivedData if the simulator runs stale code: `rm -rf ~/Library/Developer/Xcode/DerivedData/PodcastManager-*`
- App icon must have no alpha channel (App Store rejects it)
- `ITSAppUsesNonExemptEncryption: false` is set to skip the export compliance prompt

## Bundle & Signing

- Bundle ID defaults to `com.marcuslab.podcastmanager` — forks should change `bundleIdPrefix` and `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml` (the Keychain service name follows the bundle ID automatically)
- `DEVELOPMENT_TEAM` comes from the gitignored `Local.yml` (copy `Local.yml.example`); required for device/TestFlight builds only
- `teamID` for `-exportArchive` comes from the gitignored `ExportOptions.plist` (copy `ExportOptions.plist.example`); required for TestFlight/App Store export only
- Code signing: Automatic
