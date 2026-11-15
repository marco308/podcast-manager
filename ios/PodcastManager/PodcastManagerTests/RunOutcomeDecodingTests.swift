import Foundation
import Testing
@testable import PodcastManager

// Run outcomes (issue #246): the job's last_run_status picks the Settings
// icon, and a playlist's last build result shows on its row.

@Test func jobLastRunStatusPicksTheIcon() async throws {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    func decode(_ extra: String) throws -> Job {
        let json = #"{"id": "daily_playlist_update", "name": "Daily", "next_run": null, "last_run": "2026-11-15T06:00:00+00:00", "type": "cron", "is_configurable": true, "schedule": null, "interval_minutes": null\#(extra)}"#
        return try decoder.decode(Job.self, from: json.data(using: .utf8)!)
    }

    let succeeded = try decode(#", "last_run_status": "success""#)
    #expect(succeeded.lastRunSymbol == "checkmark.circle")
    #expect(succeeded.lastRunFailed == false)

    // A failed run, and an interrupted one (reported as failed), must not get a checkmark.
    let failed = try decode(#", "last_run_status": "failed", "last_run_failed_steps": ["library_sync"]"#)
    #expect(failed.lastRunFailed)
    #expect(failed.lastRunSymbol != "checkmark.circle")

    #expect(try decode(#", "last_run_status": "running""#).lastRunSymbol != "checkmark.circle")

    // Older servers send no status, and interval jobs send null: unknown, not success.
    #expect(try decode("").lastRunStatus == nil)
    #expect(try decode("").lastRunSymbol != "checkmark.circle")
    #expect(try decode(#", "last_run_status": null"#).lastRunSymbol != "checkmark.circle")
    // A value this build doesn't know decodes rather than failing the whole list.
    #expect(try decode(#", "last_run_status": "queued""#).lastRunSymbol != "checkmark.circle")
}

@Test func playlistLastRunDecodesAndIsOptional() async throws {
    let base = """
    "id": 1, "name": "Commute", "is_enabled": true, "default_episode_limit": 0,
    "default_pick_from": "newest", "arrangement": "by_position", "date_direction": "oldest_first",
    "spotify_playlist_id": "sp1", "last_updated_at": null, "created_at": "2026-11-15T00:00:00",
    "podcast_count": 2
    """
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    func decode(_ extra: String) throws -> Playlist {
        try decoder.decode(Playlist.self, from: "{\(base)\(extra)}".data(using: .utf8)!)
    }

    let old = try decode("")
    #expect(old.lastRunStatus == nil)
    #expect(old.lastRunProblem == nil)

    let partial = try decode("""
    , "last_run_status": "partial", "last_run_error": "Episodes could not be fetched for: Show B",
    "last_run_at": "2026-11-15T06:00:00.123456Z"
    """)
    #expect(partial.lastRunProblem == "Incomplete")
    #expect(partial.lastRunError == "Episodes could not be fetched for: Show B")

    #expect(try decode(#", "last_run_status": "failed""#).lastRunProblem == "Last update failed")
    #expect(try decode(#", "last_run_status": "success""#).lastRunProblem == nil)
}
