import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var appState
    @Environment(AuthService.self) private var authService

    var body: some View {
        if authService.isAuthenticated {
            mainTabView
                .task {
                    await authService.fetchUser()
                }
        } else {
            LoginScreen()
        }
    }

    private var mainTabView: some View {
        @Bindable var appState = appState

        return TabView(selection: $appState.selectedTab) {
            Tab("Podcasts", systemImage: "mic.fill", value: .podcasts) {
                PodcastsScreen()
            }

            Tab("Playlists", systemImage: "list.bullet", value: .playlists) {
                PlaylistsScreen()
            }

            Tab("Settings", systemImage: "gear", value: .settings) {
                SettingsScreen()
            }
        }
    }
}
