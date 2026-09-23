import Foundation

struct Playlist: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let isEnabled: Bool
    /// Default episodes per podcast: 0 = all unplayed, n >= 1 = at most n.
    let defaultEpisodeLimit: Int
    /// Which end of a show's unplayed episodes to take from: "newest" | "oldest".
    let defaultPickFrom: String
    /// How contributions are assembled: "by_position" | "by_date" | "shuffle".
    let arrangement: String
    /// Only used when arrangement is "by_date": "newest_first" | "oldest_first".
    let dateDirection: String
    let spotifyPlaylistId: String?
    let lastUpdatedAt: String?
    let createdAt: String
    let podcastCount: Int

    /// e.g. "All unplayed", "Latest only · newest", "Up to 3 · oldest".
    var ruleSummary: String {
        episodeRuleSummary(limit: defaultEpisodeLimit, pickFrom: defaultPickFrom)
    }

    /// Public Spotify URL, or nil until the first run has created the playlist.
    var spotifyURL: URL? {
        guard let id = spotifyPlaylistId, !id.isEmpty else { return nil }
        return URL(string: "https://open.spotify.com/playlist/\(id)")
    }

    var arrangementLabel: String {
        switch arrangement {
        case "by_date":
            return dateDirection == "oldest_first" ? "By date, oldest first" : "By date, newest first"
        case "shuffle":
            return "Shuffled"
        default:
            return "Podcast order"
        }
    }
}

/// Shared phrasing for playlist defaults and resolved assignment rules.
func episodeRuleSummary(limit: Int, pickFrom: String) -> String {
    let direction = pickFrom == "oldest" ? "oldest" : "newest"
    // The direction is shown even when unlimited: it still sets the order the
    // show's episodes are listened to within its group (matches the web UI).
    switch limit {
    case 0: return "All unplayed · \(direction)"
    case 1: return "Latest only · \(direction)"
    default: return "Up to \(limit) · \(direction)"
    }
}

struct PlaylistListResponse: Codable {
    let items: [Playlist]
    let total: Int
}

struct PlaylistRunResponse: Codable {
    let message: String
    let playlistId: Int
    let episodeCount: Int
    /// Disabled playlist left untouched.
    let skipped: Bool?
    /// Playlist was written, but from incomplete data.
    let partial: Bool?
}

struct MessageResponse: Codable {
    let message: String
}

struct PlaylistRunAllResponse: Codable {
    let message: String
    let results: [PlaylistRunResult]
}

struct PlaylistRunResult: Codable, Identifiable {
    let playlistId: Int
    let playlistName: String
    let success: Bool
    let episodeCount: Int?
    let error: String?
    let skipped: Bool?
    let partial: Bool?

    var id: Int { playlistId }
}
