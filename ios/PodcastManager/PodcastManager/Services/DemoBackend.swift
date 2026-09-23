import Foundation

/// In-memory stand-in for the backend, used by demo mode (issue #264).
///
/// App Review (and anyone without a server) can't sign in: the app needs a
/// self-hosted backend, and Spotify's Development Mode only admits allowlisted
/// accounts. Demo mode swaps this in behind `APIClient`, so every screen runs
/// its real code against sample data. Nothing touches the network or Spotify,
/// and the state resets on each launch.
///
/// The shows are fictional, with generated artwork, so the demo can be used
/// for App Store screenshots without borrowing anyone's podcast.
actor DemoBackend {
    private var podcasts: [Podcast]
    private var playlists: [Playlist]
    /// Playlist id → podcast ids in position order.
    private var assignments: [Int: [Int]]
    /// Per-assignment episode-limit overrides, to show the "Custom" badge.
    private var limitOverrides: [AssignmentKey: Int]
    private var schedule = JobSchedule(hour: 6, minute: 0)
    private var lastDailyRun: Date

    private struct AssignmentKey: Hashable {
        let playlistId: Int
        let podcastId: Int
    }

    init(now: Date = Date()) {
        let seed = DemoData(now: now)
        podcasts = seed.podcasts
        playlists = seed.playlists
        assignments = seed.assignments
        limitOverrides = [AssignmentKey(playlistId: 2, podcastId: 3): 3]
        lastDailyRun = seed.lastDailyRun
    }

    // MARK: - Auth

    func currentUser() -> User {
        User(
            id: 1,
            spotifyId: "",
            displayName: "Demo Listener",
            email: nil,
            createdAt: iso(Date()),
            updatedAt: iso(Date())
        )
    }

    // MARK: - Podcasts

    func fetchPodcasts(limit: Int, offset: Int) -> PodcastListResponse {
        let all = podcastsWithMembership()
        let page = Array(all.dropFirst(offset).prefix(limit))
        return PodcastListResponse(items: page, total: all.count)
    }

    func syncPodcasts() async -> SyncResponse {
        await pause(1.2)
        return SyncResponse(
            message: "Sync completed",
            synced: podcasts.count,
            new: 0,
            missing: 0,
            removed: 0
        )
    }

    func updatePodcast(id: Int, isSequential: Bool) async throws -> Podcast {
        await pause(0.3)
        guard let index = podcasts.firstIndex(where: { $0.id == id }) else {
            throw APIError.httpError(404, "Podcast not found")
        }
        let old = podcasts[index]
        podcasts[index] = Podcast(
            id: old.id, spotifyId: old.spotifyId, name: old.name,
            description: old.description, imageUrl: old.imageUrl,
            publisher: old.publisher, totalEpisodes: old.totalEpisodes,
            unplayedEpisodes: old.unplayedEpisodes,
            unplayedCountedAt: old.unplayedCountedAt,
            isSequential: isSequential, playlistIds: [], position: nil,
            lastSyncedAt: old.lastSyncedAt, createdAt: old.createdAt,
            updatedAt: iso(Date()), rule: nil
        )
        return podcastsWithMembership()[index]
    }

    // MARK: - Playlists

    func fetchPlaylists() -> PlaylistListResponse {
        let items = playlists.map { withCount($0) }
        return PlaylistListResponse(items: items, total: items.count)
    }

    func runPlaylist(id: Int) async throws -> PlaylistRunResponse {
        guard let playlist = playlists.first(where: { $0.id == id }) else {
            throw APIError.httpError(404, "Playlist not found")
        }
        // Same rule as the backend (issue #239): a disabled playlist is
        // never written to, and a manual run is refused.
        guard playlist.isEnabled else {
            throw APIError.httpError(409, "Playlist '\(playlist.name)' is disabled. Enable it to run it.")
        }
        await pause(1.5)
        let count = episodeCount(for: playlist)
        markUpdated(id)
        return PlaylistRunResponse(
            message: "Playlist '\(playlist.name)' updated successfully",
            playlistId: id,
            episodeCount: count,
            skipped: nil,
            partial: nil
        )
    }

    func runAllPlaylists() async -> PlaylistRunAllResponse {
        await pause(2)
        var results: [PlaylistRunResult] = []
        for playlist in playlists {
            if playlist.isEnabled {
                markUpdated(playlist.id)
                results.append(PlaylistRunResult(
                    playlistId: playlist.id, playlistName: playlist.name, success: true,
                    episodeCount: episodeCount(for: playlist), error: nil, skipped: false, partial: false
                ))
            } else {
                results.append(PlaylistRunResult(
                    playlistId: playlist.id, playlistName: playlist.name, success: true,
                    episodeCount: 0, error: nil, skipped: true, partial: false
                ))
            }
        }
        let updated = results.filter { $0.skipped != true }.count
        let skipped = results.count - updated
        var message = "Updated \(updated) playlists, 0 failed"
        if skipped > 0 {
            message += ", \(skipped) skipped (disabled)"
        }
        return PlaylistRunAllResponse(message: message, results: results)
    }

    // MARK: - Playlist podcasts

    func fetchPlaylistPodcasts(playlistId: Int) throws -> PodcastListResponse {
        guard let playlist = playlists.first(where: { $0.id == playlistId }) else {
            throw APIError.httpError(404, "Playlist not found")
        }
        let ids = assignments[playlistId] ?? []
        let items = ids.enumerated().compactMap { position, podcastId -> Podcast? in
            guard let p = podcasts.first(where: { $0.id == podcastId }) else { return nil }
            return Podcast(
                id: p.id, spotifyId: p.spotifyId, name: p.name,
                description: p.description, imageUrl: p.imageUrl,
                publisher: p.publisher, totalEpisodes: p.totalEpisodes,
                unplayedEpisodes: p.unplayedEpisodes,
                unplayedCountedAt: p.unplayedCountedAt,
                isSequential: p.isSequential, playlistIds: [], position: position,
                lastSyncedAt: p.lastSyncedAt, createdAt: nil, updatedAt: nil,
                rule: rule(for: p, in: playlist)
            )
        }
        return PodcastListResponse(items: items, total: items.count)
    }

    func addPodcasts(playlistId: Int, podcastIds: [Int]) async throws -> MessageResponse {
        guard playlists.contains(where: { $0.id == playlistId }) else {
            throw APIError.httpError(404, "Playlist not found")
        }
        await pause(0.4)
        var ids = assignments[playlistId] ?? []
        let new = podcastIds.filter { !ids.contains($0) }
        ids.append(contentsOf: new)
        assignments[playlistId] = ids
        return MessageResponse(message: "Added \(new.count) podcast(s) to playlist")
    }

    func removePodcast(playlistId: Int, podcastId: Int) async throws -> MessageResponse {
        guard var ids = assignments[playlistId], ids.contains(podcastId) else {
            throw APIError.httpError(404, "Podcast not in playlist")
        }
        await pause(0.3)
        ids.removeAll { $0 == podcastId }
        assignments[playlistId] = ids
        limitOverrides[AssignmentKey(playlistId: playlistId, podcastId: podcastId)] = nil
        return MessageResponse(message: "Podcast removed from playlist")
    }

    // MARK: - Jobs

    func jobsStatus() -> JobsStatusResponse {
        let now = Date()
        return JobsStatusResponse(jobs: [
            Job(
                id: "daily_playlist_update",
                name: "Daily Library Sync & Playlist Update",
                nextRun: iso(nextDailyRun(after: now)),
                lastRun: iso(lastDailyRun),
                type: "cron",
                isConfigurable: true,
                schedule: schedule,
                intervalMinutes: nil
            ),
            intervalJob("token_refresh", "Spotify Token Refresh", minutes: 45, now: now),
            intervalJob("remove_played_episodes", "Remove Played Episodes", minutes: 30, now: now),
            intervalJob("cleanup_sessions", "Cleanup Expired Sessions", minutes: 60, now: now),
        ])
    }

    func updateSchedule(hour: Int, minute: Int) async -> UpdateScheduleResponse {
        await pause(0.4)
        schedule = JobSchedule(hour: hour, minute: minute)
        return UpdateScheduleResponse(
            message: "Schedule updated",
            nextRun: iso(nextDailyRun(after: Date()))
        )
    }

    // MARK: - Helpers

    /// A short wait so spinners and toasts behave as they do against a server.
    private func pause(_ seconds: Double) async {
        try? await Task.sleep(for: .seconds(seconds))
    }

    private func podcastsWithMembership() -> [Podcast] {
        podcasts.map { podcast in
            var copy = podcast
            copy.playlistIds = playlists.map(\.id).filter { assignments[$0]?.contains(podcast.id) == true }
            return copy
        }
    }

    private func withCount(_ p: Playlist) -> Playlist {
        Playlist(
            id: p.id, name: p.name, isEnabled: p.isEnabled,
            defaultEpisodeLimit: p.defaultEpisodeLimit, defaultPickFrom: p.defaultPickFrom,
            arrangement: p.arrangement, dateDirection: p.dateDirection,
            spotifyPlaylistId: p.spotifyPlaylistId, lastUpdatedAt: p.lastUpdatedAt,
            createdAt: p.createdAt, podcastCount: assignments[p.id]?.count ?? 0
        )
    }

    private func markUpdated(_ id: Int) {
        guard let index = playlists.firstIndex(where: { $0.id == id }) else { return }
        let p = playlists[index]
        playlists[index] = Playlist(
            id: p.id, name: p.name, isEnabled: p.isEnabled,
            defaultEpisodeLimit: p.defaultEpisodeLimit, defaultPickFrom: p.defaultPickFrom,
            arrangement: p.arrangement, dateDirection: p.dateDirection,
            spotifyPlaylistId: p.spotifyPlaylistId, lastUpdatedAt: iso(Date()),
            createdAt: p.createdAt, podcastCount: p.podcastCount
        )
    }

    /// Mirrors `services/assignment_rules.py::resolve_rule`: override, then
    /// the sequential hint (pick-from only), then the playlist default.
    private func rule(for podcast: Podcast, in playlist: Playlist) -> AssignmentRule {
        let override = limitOverrides[AssignmentKey(playlistId: playlist.id, podcastId: podcast.id)]
        return AssignmentRule(
            episodeLimit: override ?? playlist.defaultEpisodeLimit,
            pickFrom: podcast.isSequential ? "oldest" : playlist.defaultPickFrom,
            episodeLimitSource: override == nil ? "playlist" : "override",
            pickFromSource: podcast.isSequential ? "sequential" : "playlist"
        )
    }

    private func episodeCount(for playlist: Playlist) -> Int {
        (assignments[playlist.id] ?? []).reduce(0) { total, podcastId in
            guard let p = podcasts.first(where: { $0.id == podcastId }) else { return total }
            let limit = rule(for: p, in: playlist).episodeLimit
            let unplayed = p.unplayedEpisodes ?? 4
            return total + (limit == 0 ? unplayed : min(limit, unplayed))
        }
    }

    private func nextDailyRun(after date: Date) -> Date {
        let components = DateComponents(hour: schedule.hour, minute: schedule.minute)
        return Calendar.current.nextDate(after: date, matching: components, matchingPolicy: .nextTime) ?? date
    }

    private func intervalJob(_ id: String, _ name: String, minutes: Int, now: Date) -> Job {
        // Stagger the runs so the list doesn't show identical times.
        let elapsed = Double((id.count * 7) % minutes) * 60
        return Job(
            id: id,
            name: name,
            nextRun: iso(now.addingTimeInterval(Double(minutes) * 60 - elapsed)),
            lastRun: iso(now.addingTimeInterval(-elapsed)),
            type: "interval",
            isConfigurable: false,
            schedule: nil,
            intervalMinutes: minutes
        )
    }
}

private func iso(_ date: Date) -> String {
    ISO8601DateFormatter().string(from: date)
}

/// The sample library. Every show is made up.
private struct DemoData {
    let podcasts: [Podcast]
    let playlists: [Playlist]
    let assignments: [Int: [Int]]
    let lastDailyRun: Date

    init(now: Date) {
        let day: TimeInterval = 24 * 60 * 60
        let created = iso(now.addingTimeInterval(-90 * day))

        // (name, publisher, description, total, unplayed, counted days ago, sequential)
        let shows: [(String, String, String, Int, Int?, Double?, Bool)] = [
            ("The Daily Dispatch", "Harbour Street Media",
             "Twenty minutes on the one story everyone will be talking about today.",
             1240, 3, 0.5, false),
            ("Long Haul", "Wayfarer Audio",
             "A ten-part investigation into a container ship that vanished in 1978.",
             10, 7, 1, true),
            ("Signal & Circuit", "Quiet Bench",
             "Two engineers take one piece of everyday technology apart each week.",
             212, 5, 2, false),
            ("Field Fork", "Allotment Radio",
             "Growing, cooking and arguing about vegetables.",
             156, nil, nil, false),
            ("Night Market", "Lantern Stories",
             "Fiction in weekly chapters, set in a market that opens only after dark.",
             48, 22, 10, true),
            ("Quarter Brief", "Ledger & Line",
             "The week in money, explained without the jargon.",
             388, 2, 0.5, false),
            ("Slow Lane", "Two Wheels Collective",
             "Unhurried conversations from long bike rides.",
             95, nil, nil, false),
            ("Common Sense Science", "Bright Lab",
             "One listener question, answered properly.",
             301, 4, 3, false),
            ("Weather Talk", "Front Line Audio",
             "What the sky is doing and why.",
             520, 1, 0.2, false),
            ("Paper Cuts", "Margin Notes",
             "Book reviews, author interviews and the occasional rant.",
             174, 9, 4, false),
        ]

        podcasts = shows.enumerated().map { index, show in
            let artwork = Bundle.main.url(forResource: "demo-\(index + 1)", withExtension: "png")
            return Podcast(
                id: index + 1,
                spotifyId: "",
                name: show.0,
                description: show.2,
                imageUrl: artwork?.absoluteString,
                publisher: show.1,
                totalEpisodes: show.3,
                unplayedEpisodes: show.4,
                unplayedCountedAt: show.5.map { iso(now.addingTimeInterval(-$0 * day)) },
                isSequential: show.6,
                playlistIds: [],
                position: nil,
                lastSyncedAt: iso(now.addingTimeInterval(-0.3 * day)),
                createdAt: created,
                updatedAt: created,
                rule: nil
            )
        }

        let lastRun = Calendar.current.date(bySettingHour: 6, minute: 0, second: 0, of: now) ?? now
        lastDailyRun = lastRun > now ? lastRun.addingTimeInterval(-day) : lastRun

        playlists = [
            Playlist(
                id: 1, name: "Morning Commute", isEnabled: true,
                defaultEpisodeLimit: 1, defaultPickFrom: "newest",
                arrangement: "by_date", dateDirection: "newest_first",
                spotifyPlaylistId: nil, lastUpdatedAt: iso(lastDailyRun),
                createdAt: created, podcastCount: 0
            ),
            Playlist(
                id: 2, name: "Deep Dives", isEnabled: true,
                defaultEpisodeLimit: 2, defaultPickFrom: "newest",
                arrangement: "by_position", dateDirection: "newest_first",
                spotifyPlaylistId: nil, lastUpdatedAt: iso(lastDailyRun),
                createdAt: created, podcastCount: 0
            ),
            Playlist(
                id: 3, name: "Weekend Stories", isEnabled: false,
                defaultEpisodeLimit: 0, defaultPickFrom: "oldest",
                arrangement: "by_position", dateDirection: "newest_first",
                spotifyPlaylistId: nil, lastUpdatedAt: nil,
                createdAt: created, podcastCount: 0
            ),
        ]

        assignments = [
            1: [1, 6, 9, 8],
            2: [2, 3, 10],
            3: [5, 2],
        ]
    }
}
