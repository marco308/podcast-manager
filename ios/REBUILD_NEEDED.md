# iOS Rebuild Needed — Mobile OAuth Exchange Code

## Problem

After deploying `security-hardening` branch to prod, iOS login fails with:

> Failed to get session from login

## Root cause

Client/server version mismatch — not a backend bug.

- Backend commit **8a0fb0e** (`security(auth): move mobile OAuth to a single-use exchange code`) changed the mobile OAuth callback from:
  - **Old:** `podcastmanager://auth/callback?session_id=…&csrf_token=…`
  - **New:** `podcastmanager://auth/callback?code=…` (single-use, 2-min TTL, redeemed via `POST /api/auth/mobile-exchange`)
- `ios/PodcastManager/PodcastManager/Services/AuthService.swift` was updated in the same commit to consume the new flow.
- The iOS binary currently on the phone is **pre-8a0fb0e** — it still parses `session_id` / `csrf_token` from the callback URL, and its error-branch string was literally "Failed to get session from login" (since renamed to "Failed to get exchange code from login" at line 51 of the new file).

Backend logs confirm the server side is fine — session `SWnsGq9G…` was issued for user 1 and the 302 to `podcastmanager://auth/callback?code=…` went out at 2026-04-17 07:15:30.

## Fix — rebuild + upload iOS app to TestFlight

Run from a Mac (needs Xcode + signing creds). Build machine needs more RAM than the homelab host.

```bash
cd ios/PodcastManager

# Regenerate the Xcode project if project.yml or file tree changed
xcodegen generate

# Archive
xcodebuild archive \
  -project PodcastManager.xcodeproj \
  -scheme PodcastManager \
  -archivePath ./build/PodcastManager.xcarchive \
  -destination 'generic/platform=iOS'

# Export IPA
xcodebuild -exportArchive \
  -archivePath ./build/PodcastManager.xcarchive \
  -exportPath ./build/export \
  -exportOptionsPlist ExportOptions.plist \
  -allowProvisioningUpdates

# Upload to TestFlight
xcrun altool --upload-app \
  -f ./build/export/PodcastManager.ipa \
  -t ios \
  --apiKey JANTUJ6C57 \
  --apiIssuer 45bb81ca-41c2-4ebb-ae88-b1a493488af6
```

Bundle ID: `com.marcuslab.podcastmanager` · Team ID: `Z62E7MGREE`

## After upload

1. Wait for TestFlight processing (usually a few minutes).
2. Update the app on the phone from TestFlight.
3. Log in — should succeed. Backend-side success indicators:
   - `POST /api/auth/mobile-exchange` returns 200 (rate-limited 10/min).
   - Logs show `Redirecting to mobile app with exchange code` followed by a `mobile-exchange` hit (not the old behavior of redirecting with `session_id` in the URL).

## Files touched in 8a0fb0e (for reference)

- `backend/app/routers/auth.py` — mobile branch now calls `issue_exchange_code()` and redirects with `?code=…`; new `POST /api/auth/mobile-exchange` endpoint added.
- `backend/app/services/mobile_auth.py` — in-memory pending-exchange map with TTL.
- `ios/PodcastManager/PodcastManager/Services/AuthService.swift` — parses `code` from callback URL and calls `APIClient.shared.exchangeMobileAuthCode(code)`.
- `ios/PodcastManager/PodcastManager/Services/APIClient.swift` — new `exchangeMobileAuthCode` method.

## Not a fix — don't do this

Do **not** add a backwards-compat branch to the backend that keeps emitting `session_id` / `csrf_token` in the URL. That would undo the whole point of the security change (URL-scheme hijacking / log exposure). Just ship the iOS update.
