import Foundation

struct Podcast: Identifiable, Hashable {
    let id: Int
    let spotifyId: String
    let name: String
    let description: String?
    let imageUrl: String?
    let publisher: String?
    let totalEpisodes: Int
    /// nil = not counted yet; the backend fills it in when a playlist build
    /// reads the show's whole catalogue.
    let unplayedEpisodes: Int?
    let isSequential: Bool
    var playlistIds: [Int]
    let position: Int?
    let lastSyncedAt: String?
    let createdAt: String?
    let updatedAt: String?
    /// Resolved per-assignment rule; only present on rows from
    /// `/api/playlists/{id}/podcasts`.
    let rule: AssignmentRule?
}

/// What a build applies to one playlist assignment, and where each part came
/// from (`playlist`, `sequential` or `override`).
struct AssignmentRule: Codable, Hashable {
    let episodeLimit: Int
    let pickFrom: String
    let episodeLimitSource: String
    let pickFromSource: String

    /// Same phrasing as `Playlist.ruleSummary`.
    var summary: String {
        episodeRuleSummary(limit: episodeLimit, pickFrom: pickFrom)
    }

    /// True when either part was set on the assignment itself.
    var isCustom: Bool {
        episodeLimitSource == "override" || pickFromSource == "override"
    }
}

extension Podcast: Codable {
    // Uses convertFromSnakeCase on the decoder, so keys are camelCase here
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        spotifyId = try c.decode(String.self, forKey: .spotifyId)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        imageUrl = try c.decodeIfPresent(String.self, forKey: .imageUrl)
        publisher = try c.decodeIfPresent(String.self, forKey: .publisher)
        totalEpisodes = try c.decodeIfPresent(Int.self, forKey: .totalEpisodes) ?? 0
        unplayedEpisodes = try c.decodeIfPresent(Int.self, forKey: .unplayedEpisodes)
        isSequential = try c.decodeIfPresent(Bool.self, forKey: .isSequential) ?? false
        playlistIds = try c.decodeIfPresent([Int].self, forKey: .playlistIds) ?? []
        position = try c.decodeIfPresent(Int.self, forKey: .position)
        lastSyncedAt = try c.decodeIfPresent(String.self, forKey: .lastSyncedAt)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        rule = try c.decodeIfPresent(AssignmentRule.self, forKey: .rule)
    }
}

struct PodcastListResponse: Codable {
    let items: [Podcast]
    let total: Int
}

struct SyncResponse: Codable {
    let message: String
    let synced: Int
    let new: Int
    /// Absent on older backends.
    let removed: Int?
}
