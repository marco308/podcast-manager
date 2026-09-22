import SwiftUI

@Observable
@MainActor
class AppState {
    var selectedTab: Tab = .podcasts

    enum Tab: Hashable {
        case podcasts
        case playlists
        case settings
    }
}
