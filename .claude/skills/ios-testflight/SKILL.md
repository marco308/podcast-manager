---
name: ios-testflight
description: Archive the PodcastManager iOS app, export it with ExportOptions.plist, and upload the build to TestFlight with altool using the App Store Connect API key. Use when cutting an iOS build for TestFlight or the App Store.
---

Needs a gitignored `ios/PodcastManager/ExportOptions.plist` (copy `ExportOptions.plist.example`, set `teamID`) and an App Store Connect API key. The key ID and issuer ID are in App Store Connect → Users and Access → Integrations; the `.p8` goes in `~/.appstoreconnect/private_keys/`. Never commit the real values.

```bash
cd ios/PodcastManager
xcodegen generate

# Archive + upload to TestFlight
xcodebuild archive -project PodcastManager.xcodeproj -scheme PodcastManager \
  -archivePath ./build/PodcastManager.xcarchive -destination 'generic/platform=iOS'
xcodebuild -exportArchive -archivePath ./build/PodcastManager.xcarchive \
  -exportPath ./build/export -exportOptionsPlist ExportOptions.plist -allowProvisioningUpdates
xcrun altool --upload-app -f ./build/export/PodcastManager.ipa -t ios \
  --apiKey <YOUR_ASC_KEY_ID> --apiIssuer <YOUR_ASC_ISSUER_ID>
```
