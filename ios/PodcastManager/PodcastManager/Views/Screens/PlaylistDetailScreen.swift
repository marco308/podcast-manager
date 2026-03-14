import SwiftUI

struct PlaylistDetailScreen: View {
    let playlist: Playlist

    @State private var podcasts: [Podcast] = []
    @State private var isLoading = true
    @State private var error: String?
    @State private var showingAddSheet = false
    @State private var statusMessage: String?

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Loading podcasts...")
            } else if let error {
                errorView(error)
            } else {
                contentView
            }
        }
        .navigationTitle(playlist.name)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showingAddSheet = true
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .sheet(isPresented: $showingAddSheet) {
            AddPodcastsSheet(playlistId: playlist.id) {
                await loadPodcasts()
            }
        }
        .task {
            await loadPodcasts()
        }
        .refreshable {
            await loadPodcasts()
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
                    .onAppear {
                        Task {
                            try? await Task.sleep(for: .seconds(3))
                            withAnimation { self.statusMessage = nil }
                        }
                    }
            }
        }
    }

    private var contentView: some View {
        Group {
            if podcasts.isEmpty {
                ContentUnavailableView(
                    "No Podcasts",
                    systemImage: "mic.slash",
                    description: Text("Tap + to add podcasts to this playlist")
                )
            } else {
                List {
                    settingsSection
                    podcastsSection
                }
                .listStyle(.insetGrouped)
            }
        }
    }

    private var settingsSection: some View {
        Section("Playlist Settings") {
            LabeledContent("Episode Mode", value: episodeModeLabel)
            if playlist.isWeekendOnly {
                LabeledContent("Weekend Only", value: "Yes")
            }
            LabeledContent("Ordering", value: orderingModeLabel)
            LabeledContent("Status", value: playlist.isEnabled ? "Enabled" : "Disabled")
        }
    }

    private var podcastsSection: some View {
        Section("Podcasts (\(podcasts.count))") {
            ForEach(podcasts) { podcast in
                PodcastRow(podcast: podcast)
            }
            .onDelete { indexSet in
                Task { await removePodcasts(at: indexSet) }
            }
        }
    }

    private var episodeModeLabel: String {
        switch playlist.episodeMode {
        case "latest_only": return "Latest only"
        default: return "All unplayed"
        }
    }

    private var orderingModeLabel: String {
        switch playlist.orderingMode {
        case "podcast_order": return "Podcast order"
        case "chronological_asc": return "Oldest first"
        case "chronological_desc": return "Newest first"
        default: return "Default"
        }
    }

    private func errorView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Error", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Retry") {
                Task { await loadPodcasts() }
            }
        }
    }

    private func loadPodcasts() async {
        do {
            let response = try await APIClient.shared.fetchPlaylistPodcasts(playlistId: playlist.id)
            podcasts = response.items
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func removePodcasts(at offsets: IndexSet) async {
        for index in offsets {
            let podcast = podcasts[index]
            do {
                let response = try await APIClient.shared.removePodcastFromPlaylist(
                    playlistId: playlist.id,
                    podcastId: podcast.id
                )
                withAnimation {
                    podcasts.remove(at: index)
                    statusMessage = response.message
                }
            } catch {
                withAnimation {
                    statusMessage = "Failed to remove: \(error.localizedDescription)"
                }
            }
        }
    }
}
