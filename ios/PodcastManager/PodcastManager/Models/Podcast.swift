import Foundation

struct Podcast: Identifiable, Hashable {
    let id: Int
    let spotifyId: String
    let name: String
    let description: String?
    let imageUrl: String?
    let publisher: String?
    let totalEpisodes: Int
    let unplayedEpisodes: Int
    let isSequential: Bool
    var playlistIds: [Int]
    let position: Int?
    let lastSyncedAt: String?
    let createdAt: String?
    let updatedAt: String?
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
        unplayedEpisodes = try c.decodeIfPresent(Int.self, forKey: .unplayedEpisodes) ?? 0
        isSequential = try c.decodeIfPresent(Bool.self, forKey: .isSequential) ?? false
        playlistIds = try c.decodeIfPresent([Int].self, forKey: .playlistIds) ?? []
        position = try c.decodeIfPresent(Int.self, forKey: .position)
        lastSyncedAt = try c.decodeIfPresent(String.self, forKey: .lastSyncedAt)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
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
}
