import Foundation

struct User: Codable, Identifiable {
    let id: Int
    let spotifyId: String
    let displayName: String?
    let email: String?
    let createdAt: String
    let updatedAt: String
}
