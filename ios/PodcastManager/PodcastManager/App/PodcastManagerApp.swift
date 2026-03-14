import SwiftUI

@main
struct PodcastManagerApp: App {
    @State private var appState = AppState()
    @State private var authService = AuthService()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .environment(authService)
                .task {
                    await NotificationService.shared.requestAuthorization()
                }
        }
    }
}
