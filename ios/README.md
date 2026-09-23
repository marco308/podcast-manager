# Podcast Manager for iOS

A native SwiftUI companion to the Podcast Manager web app. It connects to your own Podcast Manager backend and covers day-to-day use:

- browse and sync your podcasts, and mark shows as sequential
- add shows to a playlist or remove them, and see the rule each one follows
- run a playlist now
- view the background jobs and change the daily schedule

Creating playlists, editing their settings and overriding per-show rules happen in the web app.

The app isn't distributed on the App Store, so you build it yourself.

## Requirements

- A running Podcast Manager backend at a public HTTPS URL (see the [main README](../README.md#setup))
- macOS with Xcode 16 or later; the app targets iOS 18 on iPhone
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`)
- An Apple Developer account to install on a device (the simulator works without one)

## Build

The Xcode project is generated from `project.yml` and isn't committed.

```bash
cd ios/PodcastManager
cp Local.yml.example Local.yml    # set DEVELOPMENT_TEAM, and optionally SERVER_URL_DEFAULT
xcodegen generate
open PodcastManager.xcodeproj
```

`Local.yml` is gitignored and holds anything specific to you:

- `DEVELOPMENT_TEAM`: your Apple Team ID, needed for device builds.
- `SERVER_URL_DEFAULT`: an optional backend URL to prefill on the login screen.
- `APP_BUNDLE_ID`: your own bundle ID (for example `com.yourname.podcastmanager`), needed to sign for a device because the default belongs to the project owner's team. Set it on both targets; the example file shows how.

`xcodegen` needs `Local.yml` to exist even for simulator-only builds. Rerun `xcodegen generate` after changing `Local.yml` or adding files.

## Signing in

Enter your backend URL on the login screen and sign in with Spotify. The app signs in through the system browser and returns via the `podcastmanager://` URL scheme. The session is stored in the Keychain.

No server yet? Tap **Try the demo** on the login screen to use the app with a made-up library. Nothing in the demo touches Spotify. Exit it from Settings.

## Tests

```bash
cd ios/PodcastManager
xcodebuild test -scheme PodcastManager -destination 'platform=iOS Simulator,name=iPhone 16'
```

These cover model decoding, CSRF retry and the demo backend, and aren't run in CI.

## For contributors

[CLAUDE.md](CLAUDE.md) in this folder has the detailed notes: which backend endpoints the app deliberately doesn't wrap, the custom `Podcast` decoding, and common XcodeGen gotchas.
