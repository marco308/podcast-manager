import SwiftUI

struct PlaylistsScreen: View {
    @State private var playlists: [Playlist] = []
    @State private var isLoading = true
    @State private var isRunningAll = false
    @State private var error: String?
    @State private var statusMessage: String?

    var body: some View {
        NavigationStack {
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
            .toolbar {
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
        .navigationDestination(for: Playlist.self) { playlist in
            PlaylistDetailScreen(playlist: playlist)
        }
    }

    private var emptyView: some View {
        ContentUnavailableView(
            "No Playlists",
            systemImage: "list.bullet",
            description: Text("Create playlists in the web app to see them here")
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
        do {
            let response = try await APIClient.shared.runPlaylist(id: playlist.id)
            // Use the server's message: it distinguishes weekend-only skips
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
