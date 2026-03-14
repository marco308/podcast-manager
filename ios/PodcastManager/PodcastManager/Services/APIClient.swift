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

    func fetchPodcasts(limit: Int = 50, offset: Int = 0) async throws -> PodcastListResponse {
        try await get("/api/podcasts?limit=\(limit)&offset=\(offset)")
    }

    func syncPodcasts() async throws -> SyncResponse {
        try await post("/api/podcasts/sync")
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

    // MARK: - HTTP Methods

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let request = try makeRequest(path: path, method: "GET")
        return try await execute(request)
    }

    private func post<T: Decodable>(_ path: String) async throws -> T {
        let request = try makeRequest(path: path, method: "POST")
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
