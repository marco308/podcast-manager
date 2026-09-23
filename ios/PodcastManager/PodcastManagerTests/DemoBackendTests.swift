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

    @Test func apiClientRoutesToTheDemo() async throws {
        let client = APIClient()
        await client.setDemo(DemoBackend())
        let playlists = try await client.fetchPlaylists()
        #expect(playlists.items.map(\.name).contains("Morning Commute"))
    }
}
