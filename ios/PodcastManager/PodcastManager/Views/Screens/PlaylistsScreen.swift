import SwiftUI

struct PlaylistsScreen: View {
    @State private var playlists: [Playlist] = []
    @State private var isLoading = true
    @State private var isRunningAll = false
    @State private var error: String?
    @State private var statusMessage: String?
    @State private var showingCreateSheet = false
    /// Bound so a newly created playlist can be opened straight away.
    @State private var path: [Playlist] = []

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if isLoading {
                    ProgressView("Loading playlists...")
                } else if let error {
                    errorView(error)
                } else if playlists.isEmpty {
                    emptyView
                } else {
                    playlistList
                }
            }
            .navigationTitle("Playlists")
            .navigationDestination(for: Playlist.self) { playlist in
                PlaylistDetailScreen(playlist: playlist) { message in
                    await loadPlaylists()
                    if let message {
                        withAnimation { statusMessage = message }
                    }
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showingCreateSheet = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("New Playlist")
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        Task { await runAllPlaylists() }
                    } label: {
                        if isRunningAll {
                            ProgressView()
                        } else {
                            Image(systemName: "play.fill")
                        }
                    }
                    .disabled(isRunningAll)
                }
            }
            .sheet(isPresented: $showingCreateSheet) {
                PlaylistFormSheet(playlist: nil) { created in
                    await loadPlaylists()
                    // Open it, so the next step (adding podcasts) is one tap.
                    path.append(created)
                }
            }
            .task {
                await loadPlaylists()
            }
            .refreshable {
                await loadPlaylists()
            }
            .overlay(alignment: .bottom) {
                if let statusMessage {
                    Text(statusMessage)
                        .font(.footnote.bold())
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .padding(.bottom, 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .task(id: statusMessage) {
                            // Keyed on the message so a replacement toast
                            // restarts the timer instead of inheriting the
                            // dying one (issue #181).
                            try? await Task.sleep(for: .seconds(3))
                            if !Task.isCancelled {
                                withAnimation { self.statusMessage = nil }
                            }
                        }
                }
            }
        }
    }

    private var playlistList: some View {
        List(playlists) { playlist in
            NavigationLink(value: playlist) {
                PlaylistRow(playlist: playlist) {
                    await runPlaylist(playlist)
                }
            }
        }
        .listStyle(.plain)
    }

    private var emptyView: some View {
        ContentUnavailableView(
            "No Playlists",
            systemImage: "list.bullet",
            description: Text("Tap + to create your first playlist")
        )
    }

    private func errorView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Error", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Retry") {
                Task { await loadPlaylists() }
            }
        }
    }

    private func loadPlaylists() async {
        do {
            let response = try await APIClient.shared.fetchPlaylists()
            playlists = response.items
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func runPlaylist(_ playlist: Playlist) async {
        await NotificationService.shared.requestAuthorization()
        do {
            let response = try await APIClient.shared.runPlaylist(id: playlist.id)
            // Use the server's message: it distinguishes skips
            // and partial updates, where a fabricated "0 episodes" read as
            // the playlist having been emptied (issue #181).
            withAnimation {
                statusMessage = response.message
            }
            let title = if response.skipped == true {
                "Playlist Skipped"
            } else if response.partial == true {
                "Playlist Updated with Warnings"
            } else {
                "Playlist Updated"
            }
            NotificationService.shared.sendIfBackgrounded(
                title: title,
                body: response.message,
                identifier: "playlist-run-\(playlist.id)"
            )
        } catch {
            withAnimation {
                statusMessage = "Failed: \(error.localizedDescription)"
            }
        }
    }

    private func runAllPlaylists() async {
        isRunningAll = true
        await NotificationService.shared.requestAuthorization()
        do {
            let response = try await APIClient.shared.runAllPlaylists()
            withAnimation {
                statusMessage = response.message
            }
            // The server message already breaks down updated/failed/skipped;
            // don't recount skipped playlists as plain successes here.
            NotificationService.shared.sendIfBackgrounded(
                title: "Playlist Update Complete",
                body: response.message,
                identifier: "playlist-run-all"
            )
        } catch {
            withAnimation {
                statusMessage = "Failed: \(error.localizedDescription)"
            }
        }
        isRunningAll = false
    }
}
