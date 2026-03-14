import Foundation
import Testing
@testable import PodcastManager

@Test func podcastDecoding() async throws {
    let json = """
    {
        "id": 1,
        "spotify_id": "abc123",
        "name": "Test Podcast",
        "description": "A test podcast",
        "image_url": "https://example.com/image.jpg",
        "publisher": "Test Publisher",
        "total_episodes": 100,
        "unplayed_episodes": 5,
        "is_sequential": false,
        "playlist_ids": [1, 2],
        "last_synced_at": "2025-01-25T00:00:00",
        "created_at": "2025-01-25T00:00:00",
        "updated_at": "2025-01-25T00:00:00"
    }
    """.data(using: .utf8)!

    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let podcast = try decoder.decode(Podcast.self, from: json)

    #expect(podcast.id == 1)
    #expect(podcast.spotifyId == "abc123")
    #expect(podcast.name == "Test Podcast")
    #expect(podcast.unplayedEpisodes == 5)
    #expect(podcast.isSequential == false)
    #expect(podcast.playlistIds == [1, 2])
}

@Test func playlistDecoding() async throws {
    let json = """
    {
        "id": 1,
        "name": "Morning Playlist",
        "episode_mode": "all_unplayed",
        "is_enabled": true,
        "is_weekend_only": false,
        "ordering_mode": "default",
        "spotify_playlist_id": "sp123",
        "last_updated_at": null,
        "created_at": "2025-01-25T00:00:00",
        "podcast_count": 5
    }
    """.data(using: .utf8)!

    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let playlist = try decoder.decode(Playlist.self, from: json)

    #expect(playlist.id == 1)
    #expect(playlist.name == "Morning Playlist")
    #expect(playlist.episodeMode == "all_unplayed")
    #expect(playlist.isEnabled == true)
    #expect(playlist.podcastCount == 5)
}
