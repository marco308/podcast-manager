import Foundation

struct User: Codable, Identifiable {
    let id: Int
    let spotifyId: String
    let displayName: String?
    let email: String?
    let createdAt: String
    let updatedAt: String
}

/// Response body of `POST /api/auth/mobile-exchange`. The server returns the
/// real session_id and csrf_token here (rather than echoing them through the
/// OAuth callback URL), so credentials never appear in any URL or log.
struct MobileExchangeResponse: Codable {
    let sessionId: String
    let csrfToken: String
}

/// Response body of `GET /api/auth/csrf-token`: the CSRF token bound to the
/// current session, used to recover from a 403 CSRF rejection.
struct CsrfTokenResponse: Codable {
    let csrfToken: String
}
