import Foundation
import Testing
@testable import PodcastManager

/// Demo mode is what App Review sees (issue #264), so it must behave like
/// the backend on the paths a reviewer is likely to tap.
struct DemoBackendTests {
    @Test func libraryHasArtworkAndMembership() async throws {
        let demo = DemoBackend()
        let page = await demo.fetchPodcasts(limit: 100, offset: 0)
        #expect(page.total == page.items.count)
        #expect(page.items.allSatisfy { $0.imageUrl != nil })
        let longHaul = try #require(page.items.first { $0.name == "Long Haul" })
        #expect(Set(longHaul.playlistIds) == [2, 3])
    }

    @Test func rulesResolveLikeTheBackend() async throws {
        let demo = DemoBackend()
        let rows = try await demo.fetchPlaylistPodcasts(playlistId: 2).items
        let sequential = try #require(rows.first { $0.isSequential }?.rule)
        #expect(sequential.pickFrom == "oldest")
        #expect(sequential.pickFromSource == "sequential")
        #expect(rows.contains { $0.rule?.isCustom == true })
    }

    @Test func addAndRemoveChangeMembership() async throws {
        let demo = DemoBackend()
        _ = try await demo.addPodcasts(playlistId: 1, podcastIds: [4])
        #expect(try await demo.fetchPlaylistPodcasts(playlistId: 1).items.last?.id == 4)
        _ = try await demo.removePodcast(playlistId: 1, podcastId: 4)
        #expect(try await demo.fetchPlaylistPodcasts(playlistId: 1).items.contains { $0.id == 4 } == false)
    }

    @Test func reorderSetsPositionsAndRefusesPartialLists() async throws {
        let demo = DemoBackend()
        _ = try await demo.reorderPodcasts(playlistId: 2, podcastIds: [10, 2, 3])
        let rows = try await demo.fetchPlaylistPodcasts(playlistId: 2).items
        #expect(rows.map(\.id) == [10, 2, 3])
        // Partial, repeated or foreign lists change nothing, like the backend.
        for bad in [[10, 2], [10, 2, 2], [10, 2, 4]] {
            await #expect(throws: APIError.self) {
                _ = try await demo.reorderPodcasts(playlistId: 2, podcastIds: bad)
            }
        }
        #expect(try await demo.fetchPlaylistPodcasts(playlistId: 2).items.map(\.id) == [10, 2, 3])
    }

    @Test func overridesResolveAndClearLikeTheBackend() async throws {
        let demo = DemoBackend()
        // Long Haul (2) is sequential in Deep Dives (2): oldest by the hint.
        var row = try await demo.updateAssignment(
            playlistId: 2, podcastId: 2,
            override: AssignmentOverride(episodeLimit: 5, pickFrom: "newest")
        )
        #expect(row.rule == AssignmentRule(
            episodeLimit: 5, pickFrom: "newest",
            episodeLimitSource: "override", pickFromSource: "override"
        ))
        #expect(row.override == AssignmentOverride(episodeLimit: 5, pickFrom: "newest"))

        // Clearing both goes back to the playlist default and the hint.
        row = try await demo.updateAssignment(playlistId: 2, podcastId: 2, override: AssignmentOverride())
        #expect(row.rule?.episodeLimitSource == "playlist")
        #expect(row.rule?.pickFromSource == "sequential")
        #expect(row.rule?.isCustom == false)

        await #expect(throws: APIError.self) {
            _ = try await demo.updateAssignment(
                playlistId: 2, podcastId: 2, override: AssignmentOverride(episodeLimit: 501)
            )
        }
        await #expect(throws: APIError.self) {
            _ = try await demo.updateAssignment(playlistId: 1, podcastId: 2, override: AssignmentOverride())
        }
    }

    @Test func playlistLifecycleChecksLinksLikeTheBackend() async throws {
        let demo = DemoBackend()
        var draft = PlaylistDraft.new
        draft.name = "Evening Walk"
        draft.spotifyPlaylistId = "demoKitchenRadio000002"
        let created = try await demo.createPlaylist(draft)
        #expect(created.podcastCount == 0)
        #expect(try await demo.fetchPlaylistPodcasts(playlistId: created.id).items.isEmpty)

        // The picker marks it taken, and a second link to it is refused.
        let options = await demo.spotifyPlaylists().items
        #expect(options.first { $0.id == "demoKitchenRadio000002" }?.linkedPlaylistId == created.id)
        var other = PlaylistDraft(try #require(await demo.fetchPlaylists().items.first { $0.id == 1 }))
        other.spotifyPlaylistId = "demoKitchenRadio000002"
        await #expect(throws: APIError.self) { _ = try await demo.updatePlaylist(id: 1, draft: other) }
        // Only playlists the user owns can be linked.
        other.spotifyPlaylistId = "notMine"
        await #expect(throws: APIError.self) { _ = try await demo.updatePlaylist(id: 1, draft: other) }

        // Saving it unchanged keeps its own link; editing applies.
        draft.arrangement = "shuffle"
        draft.defaultEpisodeLimit = 3
        let updated = try await demo.updatePlaylist(id: created.id, draft: draft)
        #expect(updated.arrangement == "shuffle")
        #expect(updated.defaultEpisodeLimit == 3)
        #expect(updated.spotifyPlaylistId == "demoKitchenRadio000002")

        // Deleting with Spotify removes it from the picker too.
        _ = try await demo.deletePlaylist(id: created.id, removeFromSpotify: true)
        #expect(await demo.fetchPlaylists().items.contains { $0.id == created.id } == false)
        #expect(await demo.spotifyPlaylists().items.contains { $0.id == "demoKitchenRadio000002" } == false)
    }

    @Test func playlistDraftSendsNullToUnlink() throws {
        var draft = PlaylistDraft.new
        draft.name = "X"
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft)) as? [String: Any]
        // Present-and-null is what tells PATCH to unlink; absent would keep the link.
        #expect(json?.keys.contains("spotify_playlist_id") == true)
        #expect(json?["spotify_playlist_id"] is NSNull)
        #expect(json?["default_episode_limit"] as? Int == 0)
    }

    @Test func sleepPlaylistsFollowTheBackendRules() async throws {
        let demo = DemoBackend()
        var draft = PlaylistDraft.new
        draft.name = "Sleep"
        // Random is refused on a standard playlist.
        draft.defaultPickFrom = "random"
        await #expect(throws: APIError.self) { _ = try await demo.createPlaylist(draft) }

        draft.setKind(PlaylistKind.sleep)
        #expect(draft.arrangement == "shuffle")
        #expect(draft.defaultPickFrom == "random")
        #expect(draft.defaultEpisodeLimit == 10)
        let sleep = try await demo.createPlaylist(draft)
        #expect(sleep.isSleep)

        // A sequential show doesn't get "oldest" on a sleep playlist.
        let sequential = try #require(await demo.fetchPodcasts(limit: 100, offset: 0).items.first { $0.isSequential })
        _ = try await demo.addPodcasts(playlistId: sleep.id, podcastIds: [sequential.id])
        var row = try #require(try await demo.fetchPlaylistPodcasts(playlistId: sleep.id).items.first)
        #expect(row.rule?.pickFrom == "random")
        #expect(row.rule?.pickFromSource == "playlist")

        // A random override is cleared when the playlist goes back to standard.
        _ = try await demo.updateAssignment(
            playlistId: sleep.id, podcastId: sequential.id,
            override: AssignmentOverride(episodeLimit: nil, pickFrom: "random")
        )
        draft.setKind(PlaylistKind.standard)
        #expect(draft.defaultPickFrom == "newest")
        _ = try await demo.updatePlaylist(id: sleep.id, draft: draft)
        row = try #require(try await demo.fetchPlaylistPodcasts(playlistId: sleep.id).items.first)
        #expect(row.override?.pickFrom == nil)
        await #expect(throws: APIError.self) {
            _ = try await demo.updateAssignment(
                playlistId: sleep.id, podcastId: sequential.id,
                override: AssignmentOverride(episodeLimit: nil, pickFrom: "random")
            )
        }
    }

    @Test func playlistDraftSendsKind() throws {
        var draft = PlaylistDraft.new
        draft.name = "X"
        draft.setKind(PlaylistKind.sleep)
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft)) as? [String: Any]
        #expect(json?["kind"] as? String == "sleep")
        #expect(json?["default_pick_from"] as? String == "random")
    }

    @Test func disabledPlaylistRefusesARun() async throws {
        let demo = DemoBackend()
        await #expect(throws: APIError.self) {
            _ = try await demo.runPlaylist(id: 3)
        }
        let all = await demo.runAllPlaylists()
        // The backend filters disabled playlists out of run-all entirely.
        #expect(all.results.contains { $0.playlistId == 3 } == false)
        #expect(all.message == "Updated 2 playlists, 0 failed")
    }

    @Test func demoAccountDeletionSucceedsWithoutAServer() async throws {
        // Reviewers go through the delete flow in the demo (issue #266).
        let client = APIClient()
        await client.setDemo(DemoBackend())
        try await client.deleteAccount()
    }

    @Test func apiClientRoutesToTheDemo() async throws {
        let client = APIClient()
        await client.setDemo(DemoBackend())
        let playlists = try await client.fetchPlaylists()
        #expect(playlists.items.map(\.name).contains("Morning Commute"))
    }
}
