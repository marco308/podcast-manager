import Foundation

actor APIClient {
    static let shared = APIClient()

    private let session: URLSession
    private let decoder: JSONDecoder

    /// Called whenever any request comes back 401, so auth state can be
    /// cleared centrally instead of every screen handling it (issue #171).
    private var onUnauthorized: (@Sendable () -> Void)?

    /// When set, every call is answered by the in-memory demo instead of the
    /// network (issue #264). Check it first in each public call so no demo
    /// request can reach `makeRequest`.
    private var demo: DemoBackend?

    /// `session` is injectable so tests can stub the network with a
    /// `URLProtocol`; production uses the default configuration.
    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 30
            self.session = URLSession(configuration: config)
        }

        self.decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    /// Register the handler invoked on any 401 response.
    func setUnauthorizedHandler(_ handler: @escaping @Sendable () -> Void) {
        onUnauthorized = handler
    }

    /// Turn demo mode on (with a fresh sample library) or off.
    func setDemo(_ backend: DemoBackend?) {
        demo = backend
    }

    // MARK: - Auth

    func fetchCurrentUser() async throws -> User {
        if let demo { return await demo.currentUser() }
        return try await get("/api/auth/me")
    }

    /// Trade a one-time mobile-flow `code` for real session credentials.
    ///
    /// The OAuth callback no longer returns `session_id`/`csrf_token` in the
    /// URL — it returns an opaque `code` that we POST here. The backend
    /// responds with the real credentials in the JSON body, which never
    /// travel through any URL or device log.
    func exchangeMobileAuthCode(_ code: String) async throws -> MobileExchangeResponse {
        try await post("/api/auth/mobile-exchange", body: ["code": code])
    }

    /// Invalidate the session server-side.
    ///
    /// Clearing the Keychain alone left the `Session` row valid for its full
    /// 24-hour lifetime, so a captured `session_id` kept working after the
    /// user signed out (issue #148).
    func logout() async throws {
        let _: MessageResponse = try await post("/api/auth/logout")
    }

    /// Delete the account and everything the server stores for it (issue
    /// #266, App Store Guideline 5.1.1(v)). Spotify playlists are left alone.
    func deleteAccount() async throws {
        if let demo { return await demo.deleteAccount() }
        let _: MessageResponse = try await delete("/api/auth/me")
    }

    /// Ask the server for the CSRF token bound to the current session and
    /// persist it. Used to recover from a 403 CSRF rejection without
    /// forcing a re-login (the web client does the same via
    /// `/api/auth/csrf-token`).
    private func refreshCsrfToken() async throws -> String {
        let response: CsrfTokenResponse = try await get("/api/auth/csrf-token")
        // A failed Keychain write is already logged by `save`; the fresh
        // token is still usable for this retry, so don't fail here.
        KeychainService.save(response.csrfToken, for: .csrfToken)
        return response.csrfToken
    }

    // MARK: - Podcasts

    func fetchPodcasts(limit: Int = 50, offset: Int = 0) async throws -> PodcastListResponse {
        if let demo { return await demo.fetchPodcasts(limit: limit, offset: offset) }
        return try await get("/api/podcasts?limit=\(limit)&offset=\(offset)")
    }

    /// Fetch every podcast, paging past the backend's 100-item cap.
    ///
    /// A single page silently dropped everything beyond the first 50/100
    /// shows (issue #170). Loops until we've collected `total` items,
    /// bailing out early if the server returns a short or empty page so a
    /// stale `total` can't spin us forever.
    func fetchAllPodcasts() async throws -> [Podcast] {
        let pageSize = 100  // backend maximum (le=100)
        var items: [Podcast] = []
        var offset = 0

        while true {
            let page = try await fetchPodcasts(limit: pageSize, offset: offset)
            items.append(contentsOf: page.items)
            if items.count >= page.total || page.items.count < pageSize {
                break
            }
            offset += pageSize
        }

        return items
    }

    func syncPodcasts() async throws -> SyncResponse {
        if let demo { return await demo.syncPodcasts() }
        return try await post("/api/podcasts/sync")
    }

    func updatePodcast(id: Int, isSequential: Bool) async throws -> Podcast {
        if let demo { return try await demo.updatePodcast(id: id, isSequential: isSequential) }
        return try await patch("/api/podcasts/\(id)", body: ["is_sequential": isSequential])
    }

    // MARK: - Playlists

    func fetchPlaylists() async throws -> PlaylistListResponse {
        if let demo { return await demo.fetchPlaylists() }
        return try await get("/api/playlists")
    }

    func runPlaylist(id: Int) async throws -> PlaylistRunResponse {
        if let demo { return try await demo.runPlaylist(id: id) }
        return try await post("/api/playlists/\(id)/run")
    }

    func runAllPlaylists() async throws -> PlaylistRunAllResponse {
        if let demo { return await demo.runAllPlaylists() }
        return try await post("/api/playlists/run-all")
    }

    // MARK: - Playlist Podcasts

    func fetchPlaylistPodcasts(playlistId: Int) async throws -> PodcastListResponse {
        if let demo { return try await demo.fetchPlaylistPodcasts(playlistId: playlistId) }
        return try await get("/api/playlists/\(playlistId)/podcasts")
    }


    func addPodcastsToPlaylist(playlistId: Int, podcastIds: [Int]) async throws -> MessageResponse {
        if let demo { return try await demo.addPodcasts(playlistId: playlistId, podcastIds: podcastIds) }
        let body = ["podcast_ids": podcastIds]
        return try await post("/api/playlists/\(playlistId)/podcasts", body: body)
    }

    func removePodcastFromPlaylist(playlistId: Int, podcastId: Int) async throws -> MessageResponse {
        if let demo { return try await demo.removePodcast(playlistId: playlistId, podcastId: podcastId) }
        return try await delete("/api/playlists/\(playlistId)/podcasts/\(podcastId)")
    }

    // MARK: - Jobs

    func fetchJobsStatus() async throws -> JobsStatusResponse {
        if let demo { return await demo.jobsStatus() }
        return try await get("/api/jobs/status")
    }

    func updateJobSchedule(hour: Int, minute: Int) async throws -> UpdateScheduleResponse {
        if let demo { return await demo.updateSchedule(hour: hour, minute: minute) }
        return try await put("/api/jobs/schedule", body: UpdateScheduleRequest(hour: hour, minute: minute))
    }

    // MARK: - HTTP Methods

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let request = try makeRequest(path: path, method: "GET")
        return try await execute(request)
    }

    private func post<T: Decodable>(_ path: String) async throws -> T {
        let request = try makeRequest(path: path, method: "POST")
        return try await execute(request)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        var request = try makeRequest(path: path, method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await execute(request)
    }

    private func put<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        var request = try makeRequest(path: path, method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await execute(request)
    }

    private func patch<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        var request = try makeRequest(path: path, method: "PATCH")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await execute(request)
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        let request = try makeRequest(path: path, method: "DELETE")
        return try await execute(request)
    }

    private func makeRequest(path: String, method: String) throws -> URLRequest {
        guard let base = ServerConfig.baseURL else {
            throw APIError.serverNotConfigured
        }
        guard let url = URL(string: "\(base.absoluteString)\(path)") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        // Add session cookie
        if let sessionId = KeychainService.get(.sessionId) {
            request.setValue("session_id=\(sessionId)", forHTTPHeaderField: "Cookie")
        }

        // Add CSRF token for state-changing requests
        if method != "GET", let csrfToken = KeychainService.get(.csrfToken) {
            request.setValue(csrfToken, forHTTPHeaderField: "X-CSRF-Token")
        }

        return request
    }

    private func execute<T: Decodable>(_ request: URLRequest, isCsrfRetry: Bool = false) async throws -> T {
        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            onUnauthorized?()
            throw APIError.unauthorized
        }

        guard 200..<300 ~= httpResponse.statusCode else {
            if httpResponse.statusCode == 429 {
                throw APIError.httpError(429, "Rate limited — try again in a few minutes")
            }
            let detail = try? decoder.decode(ErrorResponse.self, from: data)
            let message = detail?.message ?? "Unknown error"

            // A 403 whose detail mentions CSRF means the session is alive but
            // our stored token doesn't match it (lost or stale Keychain
            // entry, header stripped in transit). Mirror the web client:
            // fetch the session's current token and retry exactly once
            // (issue #163). GETs never carry a token, so only mutations
            // qualify, and the recovery GET itself can't loop back here.
            if httpResponse.statusCode == 403,
               !isCsrfRetry,
               request.httpMethod != "GET",
               message.localizedCaseInsensitiveContains("csrf"),
               let freshToken = try? await refreshCsrfToken()
            {
                var retry = request
                retry.setValue(freshToken, forHTTPHeaderField: "X-CSRF-Token")
                return try await execute(retry, isCsrfRetry: true)
            }

            throw APIError.httpError(httpResponse.statusCode, message)
        }

        return try decoder.decode(T.self, from: data)
    }
}

enum APIError: LocalizedError {
    case serverNotConfigured
    case invalidURL
    case invalidResponse
    case unauthorized
    case httpError(Int, String)

    var isUnauthorized: Bool {
        if case .unauthorized = self { return true }
        return false
    }

    var errorDescription: String? {
        switch self {
        case .serverNotConfigured:
            return "No server configured. Enter your server URL on the login screen."
        case .invalidURL:
            return "Invalid URL"
        case .invalidResponse:
            return "Invalid server response"
        case .unauthorized:
            return "Session expired. Please log in again."
        case .httpError(let code, let message):
            return "Error \(code): \(message)"
        }
    }
}

/// FastAPI's error envelope.
///
/// `detail` is a plain string for `HTTPException`, but an **array** of
/// `{loc, msg, type}` objects for 422 validation errors. Decoding it as a
/// bare `String` meant every validation error decoded to nil and surfaced as
/// "Unknown error" (issue #163). slowapi rate-limit responses use an
/// `{"error": ...}` envelope instead, so that key is the fallback.
private struct ErrorResponse: Decodable {
    let message: String

    private struct ValidationError: Decodable {
        let msg: String
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        if let text = try? container.decode(String.self, forKey: .detail) {
            message = text
            return
        }

        if let errors = try? container.decode([ValidationError].self, forKey: .detail) {
            message = errors.map(\.msg).joined(separator: "; ")
            return
        }

        message = try container.decode(String.self, forKey: .error)
    }

    private enum CodingKeys: String, CodingKey {
        case detail
        case error
    }
}
