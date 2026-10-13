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

/// Everything the playlist form edits; the body of both create (`POST
/// /api/playlists`) and update (`PATCH /api/playlists/{id}`).
struct PlaylistDraft: Encodable, Equatable {
    var name: String
    /// nil = no link: a new Spotify playlist is created on the first run.
    var spotifyPlaylistId: String?
    var isEnabled: Bool
    var defaultEpisodeLimit: Int
    var defaultPickFrom: String
    var arrangement: String
    var dateDirection: String

    /// Same starting values as the web form's new-playlist defaults.
    static let new = PlaylistDraft(
        name: "",
        spotifyPlaylistId: nil,
        isEnabled: true,
        defaultEpisodeLimit: 0,
        defaultPickFrom: "newest",
        arrangement: "by_position",
        dateDirection: "oldest_first"
    )

    init(
        name: String, spotifyPlaylistId: String?, isEnabled: Bool, defaultEpisodeLimit: Int,
        defaultPickFrom: String, arrangement: String, dateDirection: String
    ) {
        self.name = name
        self.spotifyPlaylistId = spotifyPlaylistId
        self.isEnabled = isEnabled
        self.defaultEpisodeLimit = defaultEpisodeLimit
        self.defaultPickFrom = defaultPickFrom
        self.arrangement = arrangement
        self.dateDirection = dateDirection
    }

    init(_ playlist: Playlist) {
        self.init(
            name: playlist.name,
            spotifyPlaylistId: playlist.spotifyPlaylistId.flatMap { $0.isEmpty ? nil : $0 },
            isEnabled: playlist.isEnabled,
            defaultEpisodeLimit: playlist.defaultEpisodeLimit,
            defaultPickFrom: playlist.defaultPickFrom,
            arrangement: playlist.arrangement,
            dateDirection: playlist.dateDirection
        )
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case spotifyPlaylistId = "spotify_playlist_id"
        case isEnabled = "is_enabled"
        case defaultEpisodeLimit = "default_episode_limit"
        case defaultPickFrom = "default_pick_from"
        case arrangement
        case dateDirection = "date_direction"
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        // Always present: on PATCH, null unlinks and an absent key would
        // leave the old link in place.
        if let spotifyPlaylistId {
            try c.encode(spotifyPlaylistId, forKey: .spotifyPlaylistId)
        } else {
            try c.encodeNil(forKey: .spotifyPlaylistId)
        }
        try c.encode(isEnabled, forKey: .isEnabled)
        try c.encode(defaultEpisodeLimit, forKey: .defaultEpisodeLimit)
        try c.encode(defaultPickFrom, forKey: .defaultPickFrom)
        try c.encode(arrangement, forKey: .arrangement)
        try c.encode(dateDirection, forKey: .dateDirection)
    }
}

/// A Spotify playlist the user owns, offered as a link target (issue #245).
struct SpotifyPlaylistOption: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let imageUrl: String?
    let itemCount: Int
    /// The managed playlist already linked to it, if any.
    let linkedPlaylistId: Int?
}

struct SpotifyPlaylistListResponse: Codable {
    let items: [SpotifyPlaylistOption]
    let total: Int
    /// The listing stopped at the server's page cap with more left on Spotify.
    let truncated: Bool?
}
