import Foundation

struct Podcast: Codable, Identifiable, Hashable {
    let id: Int
    let spotifyId: String
    let name: String
    let description: String?
    let imageUrl: String?
    let publisher: String?
    let totalEpisodes: Int
    let unplayedEpisodes: Int
    let isSequential: Bool
    let playlistIds: [Int]
    let lastSyncedAt: String?
    let createdAt: String
    let updatedAt: String
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
