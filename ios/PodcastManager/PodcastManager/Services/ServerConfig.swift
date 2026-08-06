import Foundation

/// Resolves which backend the app talks to.
///
/// Priority: a URL the user entered on the login screen (UserDefaults),
/// falling back to the build's `DefaultServerURL` Info.plist value — set via
/// `SERVER_URL_DEFAULT` in `Local.yml`, empty in stock builds.
enum ServerConfig {
    private static let defaultsKey = "server_url"

    static var baseURL: URL? {
        if let stored = UserDefaults.standard.string(forKey: defaultsKey),
           let url = normalize(stored) {
            return url
        }
        if let bundled = Bundle.main.object(forInfoDictionaryKey: "DefaultServerURL") as? String,
           let url = normalize(bundled) {
            return url
        }
        return nil
    }

    static func save(_ url: URL) {
        UserDefaults.standard.set(url.absoluteString, forKey: defaultsKey)
    }

    /// Accepts "host", "host:port", or a full URL; returns a normalized URL
    /// with no trailing slash, or nil if unusable. Scheme defaults to https.
    static func normalize(_ raw: String) -> URL? {
        var trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if !trimmed.contains("://") {
            trimmed = "https://" + trimmed
        }
        while trimmed.hasSuffix("/") {
            trimmed = String(trimmed.dropLast())
        }
        guard let components = URLComponents(string: trimmed),
              let scheme = components.scheme?.lowercased(),
              scheme == "https" || scheme == "http",
              let host = components.host, !host.isEmpty
        else { return nil }
        return components.url
    }
}
