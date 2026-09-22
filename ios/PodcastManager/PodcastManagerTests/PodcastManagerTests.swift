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

@Test func unplayedCountNeedsItsTimestamp() async throws {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    func decode(_ extra: String) throws -> Podcast {
        let json = #"{"id": 1, "spotify_id": "a", "name": "P", "unplayed_episodes": 5\#(extra)}"#
        return try decoder.decode(Podcast.self, from: json.data(using: .utf8)!)
    }

    // Older backends send no timestamp: the count can't be dated, so it isn't shown.
    #expect(try decode("").countedUnplayed == nil)

    // Pydantic sends microseconds.
    let counted = try #require(try decode(#", "unplayed_counted_at": "2026-09-22T10:00:00.123456Z""#).countedUnplayed)
    #expect(counted.count == 5)
    #expect(counted.countedAt == ISO8601DateFormatter().date(from: "2026-09-22T10:00:00Z"))
    #expect(Podcast.isUnplayedStale(counted.countedAt, relativeTo: counted.countedAt.addingTimeInterval(6 * 86_400)) == false)
    #expect(Podcast.isUnplayedStale(counted.countedAt, relativeTo: counted.countedAt.addingTimeInterval(8 * 86_400)))
}

@Test func playlistDecoding() async throws {
    let json = """
    {
        "id": 1,
        "name": "Morning Playlist",
        "is_enabled": true,
        "default_episode_limit": 1,
        "default_pick_from": "newest",
        "arrangement": "by_date",
        "date_direction": "newest_first",
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
    #expect(playlist.defaultEpisodeLimit == 1)
    #expect(playlist.defaultPickFrom == "newest")
    #expect(playlist.arrangement == "by_date")
    #expect(playlist.dateDirection == "newest_first")
    #expect(playlist.ruleSummary == "Latest only · newest")
    #expect(playlist.arrangementLabel == "By date, newest first")
    #expect(playlist.isEnabled == true)
    #expect(playlist.podcastCount == 5)
}

@Test func playlistPodcastRowDecodesRule() async throws {
    // Shape of a row from GET /api/playlists/{id}/podcasts.
    let json = """
    {
        "id": 7,
        "spotify_id": "xyz789",
        "name": "Serial Show",
        "description": null,
        "image_url": null,
        "publisher": "Someone",
        "total_episodes": 40,
        "unplayed_episodes": 12,
        "is_sequential": true,
        "position": 2,
        "rule": {
            "episode_limit": 3,
            "pick_from": "oldest",
            "episode_limit_source": "override",
            "pick_from_source": "sequential"
        },
        "override": {
            "episode_limit": 3,
            "pick_from": null
        }
    }
    """.data(using: .utf8)!

    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let podcast = try decoder.decode(Podcast.self, from: json)

    let rule = try #require(podcast.rule)
    #expect(podcast.position == 2)
    #expect(podcast.playlistIds == [])
    #expect(rule.episodeLimit == 3)
    #expect(rule.pickFrom == "oldest")
    #expect(rule.episodeLimitSource == "override")
    #expect(rule.pickFromSource == "sequential")
    #expect(rule.isCustom == true)
    #expect(rule.summary == "Up to 3 · oldest")
}

@Test func plainPodcastRowHasNoRule() async throws {
    // Shape of a row from GET /api/podcasts: no rule/override keys.
    let json = """
    {
        "id": 2,
        "spotify_id": "def456",
        "name": "News Show",
        "total_episodes": 10,
        "unplayed_episodes": 1,
        "is_sequential": false,
        "playlist_ids": []
    }
    """.data(using: .utf8)!

    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let podcast = try decoder.decode(Podcast.self, from: json)

    #expect(podcast.rule == nil)
    #expect(podcast.position == nil)
}
