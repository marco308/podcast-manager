import Foundation
import Testing
@testable import PodcastManager

/// Intercepts every request made through a `URLSession` configured with
/// `protocolClasses = [StubURLProtocol.self]`, records it, and answers from
/// a handler. State lives behind a lock because URLProtocol instances are
/// created on URLSession's private queues.
final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    typealias Handler = @Sendable (URLRequest) -> (Int, Data)

    private static let lock = NSLock()
    nonisolated(unsafe) private static var _handler: Handler?
    nonisolated(unsafe) private static var _requests: [URLRequest] = []

    static var handler: Handler? {
        get { lock.withLock { _handler } }
        set { lock.withLock { _handler = newValue } }
    }

    static var requests: [URLRequest] {
        lock.withLock { _requests }
    }

    static func reset() {
        lock.withLock {
            _handler = nil
            _requests = []
        }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let handler = Self.lock.withLock { () -> Handler? in
            Self._requests.append(request)
            return Self._handler
        }
        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let (status, body) = handler(request)
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

/// Serialized: the stub protocol and the Keychain/UserDefaults it relies on
/// are process-wide.
@Suite(.serialized)
struct APIClientCsrfRetryTests {
    private static let serverURL = URL(string: "https://example.test")!

    private func makeClient() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return APIClient(session: URLSession(configuration: config))
    }

    /// Point the client at a fake server with a live session and a CSRF
    /// token the server will reject. Restores everything afterwards.
    private func withStaleCsrfSession(_ body: () async throws -> Void) async throws {
        let previousURL = UserDefaults.standard.string(forKey: "server_url")
        ServerConfig.save(Self.serverURL)
        KeychainService.save("sess-1", for: .sessionId)
        KeychainService.save("stale-token", for: .csrfToken)
        defer {
            KeychainService.clearAll()
            StubURLProtocol.reset()
            if let previousURL {
                UserDefaults.standard.set(previousURL, forKey: "server_url")
            } else {
                UserDefaults.standard.removeObject(forKey: "server_url")
            }
        }
        try await body()
    }

    @Test func recoversFromCsrfRejectionByRefreshingTokenAndRetryingOnce() async throws {
        try await withStaleCsrfSession {
            StubURLProtocol.handler = { request in
                switch (request.httpMethod, request.url?.path) {
                case ("GET", "/api/auth/csrf-token"):
                    return (200, Data(#"{"csrf_token": "fresh-token"}"#.utf8))
                case ("POST", "/api/podcasts/sync"):
                    if request.value(forHTTPHeaderField: "X-CSRF-Token") == "fresh-token" {
                        return (200, Data(#"{"message": "ok", "synced": 3, "new": 1}"#.utf8))
                    }
                    return (403, Data(#"{"detail": "CSRF token invalid"}"#.utf8))
                default:
                    return (404, Data(#"{"detail": "Not found"}"#.utf8))
                }
            }

            let result = try await makeClient().syncPodcasts()

            #expect(result.synced == 3)
            let requests = StubURLProtocol.requests
            #expect(requests.map { "\($0.httpMethod!) \($0.url!.path)" } == [
                "POST /api/podcasts/sync",
                "GET /api/auth/csrf-token",
                "POST /api/podcasts/sync",
            ])
            #expect(requests[0].value(forHTTPHeaderField: "X-CSRF-Token") == "stale-token")
            #expect(requests[2].value(forHTTPHeaderField: "X-CSRF-Token") == "fresh-token")
            // Every request still carried the session cookie.
            #expect(requests.allSatisfy { $0.value(forHTTPHeaderField: "Cookie") == "session_id=sess-1" })
            // The refreshed token is persisted for subsequent requests.
            #expect(KeychainService.get(.csrfToken) == "fresh-token")
        }
    }

    @Test func givesUpAfterOneRetry() async throws {
        try await withStaleCsrfSession {
            StubURLProtocol.handler = { request in
                if request.url?.path == "/api/auth/csrf-token" {
                    return (200, Data(#"{"csrf_token": "fresh-token"}"#.utf8))
                }
                return (403, Data(#"{"detail": "CSRF token invalid"}"#.utf8))
            }

            await #expect(throws: APIError.self) {
                _ = try await makeClient().syncPodcasts()
            }
            #expect(StubURLProtocol.requests.count == 3)
        }
    }

    @Test func doesNotRetryNonCsrfForbidden() async throws {
        try await withStaleCsrfSession {
            StubURLProtocol.handler = { _ in
                (403, Data(#"{"detail": "Not allowed"}"#.utf8))
            }

            await #expect(throws: APIError.self) {
                _ = try await makeClient().syncPodcasts()
            }
            #expect(StubURLProtocol.requests.count == 1)
        }
    }
}
