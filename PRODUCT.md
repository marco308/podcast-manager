# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

One product across three surfaces, each following its own platform's conventions:

- **Web app** (`frontend/`, React + Ant Design): the main place to set up and run playlists.
- **Project page** (`site/index.html`, static HTML/CSS on GitHub Pages): plain-language explanation of what the product does, for people deciding whether to run it.
- **iOS companion** (`ios/`, native SwiftUI, iPhone-only): matches the web app on playlists (create, edit, assign and order shows, per-show rules, runs), plus podcast browsing/sync and the job schedule. It is going through App Store review and isn't on the App Store yet.

## Users

Self-hosters who listen to a lot of podcasts on Spotify, with every person who runs their own copy treated as a first-class user (not just the original author). Each installation serves exactly one Spotify Premium account: the person who set it up.

Their job: turn one long chronological podcast feed into a few purpose-built playlists (the day's news for the commute, the next unheard episode of a serial, a sleep playlist) and then stop thinking about it. They set things up occasionally in the web or iOS app and listen every day in Spotify itself, on a phone, car or speaker.

Secondary audiences:
- **Prospective self-hosters**, reading the project page or README to decide whether it's worth running. They need to know what it does and what it takes (Spotify Premium, their own Spotify developer app, a machine that runs Docker, a public HTTPS URL).
- **App Store reviewers**, who reach the iOS app through its demo mode.

## Product Purpose

Spotify puts every followed podcast into one feed. Podcast Manager splits it into playlists the user designs and rebuilds the matching Spotify playlists automatically (1–3 times a day), removing played episodes every 30 minutes. It works well when the user opens Spotify and the top of each playlist is the right thing to listen to next, without them having opened Podcast Manager that day.

## Positioning

Rules apply per assignment (show × playlist): each show in each playlist contributes all unplayed episodes, only the latest, or up to *n*, taken from the newest or oldest end, so one show can behave differently in different playlists. Serials play in order even inside newest-first or shuffled playlists. Listening stays in the user's own Spotify account. Podcast Manager is a layer that keeps playlists right, not another player.

## Operating Context

- Setup is occasional and deliberate: create playlists, assign shows, adjust rules, check the next rebuild's per-row rule. Day to day is hands-off; the user returns to check run results or fix something.
- Background jobs: daily library sync + rebuild, played-episode cleanup, token refresh, session cleanup. The Settings page shows last-run status, failed steps and Run History. Playlists carry a red/orange tag when their last update failed or was partial.
- Self-hosted with Docker on the user's own machine (home server, NAS, small cloud server). The one user is also the operator.

## Capabilities and Constraints

- Terms the UI uses: managed playlist, assignment, episode rule ("Episodes per podcast", "Take from"), sequential/serial, arrangement (podcast order / by release date / shuffled), enabled/disabled, archived, "Not on Spotify", sleep playlist.
- A disabled playlist is never written to on Spotify. Unfollowed shows stop contributing immediately and are removed after a 7-day grace period. Archiving hides a show without unfollowing.
- Single user per installation by construction. To serve another person, run another instance.
- Spotify API limits apply (Premium only, Dev Mode endpoint restrictions, rate limits). See the `spotify-api` skill.
- iOS builds already installed constrain the API. Backwards-compatible fields are documented in `CLAUDE.md`.
- Licence: PolyForm Noncommercial 1.0.0. Free for personal and other non-commercial use. It isn't a commercial product, so there's no pricing.

## Brand Commitments

- **Part of the Marcus Lab family** (marcuslab.uk). Load the `marcuslab-brand` skill before visual work and take the family link from it (logo, type, voice). The bench **colour palette is not binding** for this product, and its warm brown grounds (`#17110d` / `#221812`) are ruled out: the app chooses its own colours.
- **Not affiliated with Spotify.** Say so where relevant, and never look or read like an official Spotify product.
- Existing assets (not declared binding): the name "Podcast Manager" and the microphone mark in `brand/` (`logo.svg`, `logo-rounded.svg`, `logo-1024.png`), from which the iOS icon, web icons and site marks are generated.

## Evidence on Hand

- Generated screenshots of every web page in light and dark: `docs/screenshots/` (regenerate with `npm run screenshots`).
- Design notes: `docs/design/assignment-rules.md`, `docs/design/sleep-playlists.md`.
- Project page copy and an in-page app mock-up: `site/index.html`. Privacy page: `site/privacy.html`.
- App Store listing text and screenshots: `ios/PodcastManager/AppStore/`.
- Release notes: `docs/releases/`.
- No testimonials, user counts, reviews or press. Never make them up. Show names on the project page are illustrative examples of real public podcasts. They don't come from any user's data.

## Product Principles

1. **Set it up once, then just press play.** The best session is one the user never needs. Configuration is there to support listening in Spotify, not to replace it.
2. **Show exactly what the next rebuild will do.** Every rule shown is the resolved rule, with its source (playlist default, sequential hint, override). No hidden behaviour.
3. **Never surprise the user's Spotify account.** Destructive or outward effects (unfollow, delete the Spotify playlist, rebuild a linked playlist) are explicit and separate. Disabled means untouched.
4. **Fail loud, degrade gently.** A partial sync still rebuilds. A failed or partial run is labelled where the user will see it, not hidden in logs.
5. **Every self-hoster is a first-class user.** Nothing should rely on knowledge only the original author has. Copy explains things in plain language.
