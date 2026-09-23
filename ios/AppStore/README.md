# App Store listing

Everything App Store Connect asks for, kept in the repo so it changes alongside the app (issue #267). `metadata/` and `screenshots/` follow [fastlane `deliver`](https://docs.fastlane.tools/actions/deliver/)'s folder layout, so `fastlane deliver` can upload them as they are. Nothing here needs fastlane, though: each file is the text to paste into the matching field.

Keep feature claims in step with the app, the README and `site/index.html`.

## Text fields (`metadata/`)

| File | App Store Connect field | Limit |
|---|---|---|
| `en-GB/name.txt` | Name | 30 |
| `en-GB/subtitle.txt` | Subtitle | 30 |
| `en-GB/promotional_text.txt` | Promotional Text | 170 |
| `en-GB/description.txt` | Description | 4000 |
| `en-GB/keywords.txt` | Keywords (comma-separated, no spaces) | 100 |
| `en-GB/support_url.txt`, `marketing_url.txt` | Support URL, Marketing URL | |
| `en-GB/privacy_url.txt` | Privacy Policy URL | |
| `copyright.txt` | Copyright | |
| `primary_category.txt`, `secondary_category.txt` | Category | |
| `review_information/notes.txt` | App Review Information → Notes | 4000 |

Keep "Spotify" out of the name, subtitle and keywords. Spotify's branding rules and Apple's Guideline 2.3.7 both object to another company's trademark there. The description can say factually that the app works with Spotify.

The privacy policy URL only resolves once GitHub Pages is enabled for the repo (Settings → Pages → Source: GitHub Actions).

## Screenshots (`screenshots/en-GB/`)

Four 6.9" iPhone screenshots (1320 × 2868, RGB, no alpha), taken from the demo so they show only made-up shows. The app is iPhone-only for v1, so no iPad set is needed.

To retake them:

```bash
xcrun simctl create "iPhone 17 Pro Max (App Store)" \
  com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max com.apple.CoreSimulator.SimRuntime.iOS-26-0
xcrun simctl boot <udid>
xcrun simctl ui <udid> appearance light
xcrun simctl status_bar <udid> override --time "9:41" --batteryState discharging \
  --batteryLevel 100 --cellularMode active --cellularBars 4 --wifiBars 3 --operatorName ""
```

Install a build, tap **Try the demo**, go to each screen and run `xcrun simctl io <udid> screenshot screenshots/en-GB/<n>-<name>.png`. Then strip the alpha channel, which App Store Connect rejects:

```bash
python3 -c "from PIL import Image; import glob; [Image.open(f).convert('RGB').save(f) for f in glob.glob('screenshots/en-GB/*.png')]"
```

## Answers that aren't files

| Question | Answer | Why |
|---|---|---|
| App Privacy | **Data Not Collected** | The developer receives nothing. The app talks only to the server the user enters, with no analytics, ads or crash reporting. Revisit this if any of those are added. |
| Age rating | Answer **None/No** to every content question; no unrestricted web access | The app shows podcast titles and artwork from the user's own library, and only opens links in Safari. Comes out at the lowest rating. |
| Price and availability | Free (base territory UK); every territory except mainland China, plus new territories as Apple adds them | The PolyForm Noncommercial licence. Mainland China needs an ICP filing number for apps that connect to a server, which a self-hosted companion can't provide. |
| Export compliance | Already answered | `ITSAppUsesNonExemptEncryption = false` in `project.yml`; the app uses only HTTPS. |
| Content rights | Doesn't contain third-party content it lacks rights to | Artwork and titles come from the user's own Spotify library at runtime. The screenshots use made-up shows. |
| Sign-in required | Yes, with no demo account; point to the demo in the notes | See `review_information/notes.txt`. |
| Account deletion | Settings → Delete Account | Guideline 5.1.1(v), issue #266. |

## Submitting

1. Create the app record in App Store Connect with bundle ID `com.marcuslab.podcastmanager`, the name from `name.txt`, and English (U.K.) as the primary language. This is where you find out whether the name is free.
2. Upload a build with the `ios-testflight` skill, bumping `CURRENT_PROJECT_VERSION` in `project.yml` first.
3. Fill in the fields above, upload the screenshots, answer the questions, attach the build and submit for review.
4. After approval, replace "The app isn't distributed on the App Store" in `ios/README.md`, and add the App Store link to the main README and `site/index.html`.
