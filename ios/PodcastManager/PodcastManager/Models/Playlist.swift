import Foundation

struct Playlist: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let episodeMode: String
    let isEnabled: Bool
    let isWeekendOnly: Bool
    let orderingMode: String
    let spotifyPlaylistId: String?
    let lastUpdatedAt: String?
    let createdAt: String
    let podcastCount: Int
}

struct PlaylistListResponse: Codable {
    let items: [Playlist]
    let total: Int
}

struct PlaylistRunResponse: Codable {
    let message: String
    let playlistId: Int
    let episodeCount: Int
    /// Weekend-only playlist left untouched on a non-qualifying day.
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
