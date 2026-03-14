# iOS App - CLAUDE.md

## Overview

Native iOS companion app for Podcast Manager. Connects to the FastAPI backend at `https://api-podcastmanager.marcuslab.uk`.

## Stack

- **SwiftUI**, iOS 18+, Swift 6 (strict concurrency)
- **XcodeGen** for project generation (`project.yml` → `.xcodeproj`)
- **No third-party dependencies** — URLSession, Keychain, UNUserNotificationCenter

## Commands

```bash
cd ios/PodcastManager

# Regenerate Xcode project (after adding/removing files or changing project.yml)
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
  --apiKey JANTUJ6C57 --apiIssuer 45bb81ca-41c2-4ebb-ae88-b1a493488af6
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
- Callback redirects to `podcastmanager://auth/callback?session_id=...&csrf_token=...`
- Tokens stored in Keychain, sent as Cookie header + X-CSRF-Token header

**API Client:**
- Actor-based singleton (`APIClient.shared`)
- Session cookie set manually via `Cookie` header (not URLSession cookie jar)
- CSRF token sent on all non-GET requests
- Decoder uses `convertFromSnakeCase` key strategy

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

- Bundle ID: `com.marcuslab.podcastmanager`
- Team ID: `Z62E7MGREE`
- Code signing: Automatic
