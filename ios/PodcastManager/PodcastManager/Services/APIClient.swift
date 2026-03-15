import Foundation

actor APIClient {
    static let shared = APIClient()

    private let baseURL = "https://api-podcastmanager.marcuslab.uk"

    private let session: URLSession
    private let decoder: JSONDecoder

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        self.session = URLSession(configuration: config)

        self.decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    var loginURL: URL {
        URL(string: "\(baseURL)/api/auth/login?redirect_scheme=podcastmanager")!
    }

    // MARK: - Auth

    func fetchCurrentUser() async throws -> User {
        try await get("/api/auth/me")
    }

    // MARK: - Podcasts

    func fetchPodcasts(limit: Int = 50, offset: Int = 0, unassigned: Bool = false) async throws -> PodcastListResponse {
        var path = "/api/podcasts?limit=\(limit)&offset=\(offset)"
        if unassigned {
            path += "&unassigned=true"
        }
        return try await get(path)
    }

    func syncPodcasts() async throws -> SyncResponse {
        try await post("/api/podcasts/sync")
    }

    func updatePodcast(spotifyId: String, isSequential: Bool) async throws -> Podcast {
        try await patch("/api/podcasts/\(spotifyId)", body: ["is_sequential": isSequential])
    }

    // MARK: - Playlists

    func fetchPlaylists() async throws -> PlaylistListResponse {
        try await get("/api/playlists")
    }

    func runPlaylist(id: Int) async throws -> PlaylistRunResponse {
        try await post("/api/playlists/\(id)/run")
    }

    func runAllPlaylists() async throws -> PlaylistRunAllResponse {
        try await post("/api/playlists/run-all")
    }

    // MARK: - Playlist Podcasts

    func fetchPlaylistPodcasts(playlistId: Int) async throws -> PodcastListResponse {
        try await get("/api/playlists/\(playlistId)/podcasts")
    }


    func addPodcastsToPlaylist(playlistId: Int, podcastIds: [Int]) async throws -> MessageResponse {
        let body = ["podcast_ids": podcastIds]
        return try await post("/api/playlists/\(playlistId)/podcasts", body: body)
    }

    func removePodcastFromPlaylist(playlistId: Int, podcastId: Int) async throws -> MessageResponse {
        try await delete("/api/playlists/\(playlistId)/podcasts/\(podcastId)")
    }

    // MARK: - Jobs

    func fetchJobsStatus() async throws -> JobsStatusResponse {
        try await get("/api/jobs/status")
    }

    func updateJobSchedule(hour: Int, minute: Int) async throws -> UpdateScheduleResponse {
        try await put("/api/jobs/schedule", body: UpdateScheduleRequest(hour: hour, minute: minute))
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
        guard let url = URL(string: "\(baseURL)\(path)") else {
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

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard 200..<300 ~= httpResponse.statusCode else {
            let detail = try? decoder.decode(ErrorResponse.self, from: data)
            throw APIError.httpError(httpResponse.statusCode, detail?.detail ?? "Unknown error")
        }

        return try decoder.decode(T.self, from: data)
    }
}

enum APIError: LocalizedError {
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

private struct ErrorResponse: Codable {
    let detail: String
}
