import SwiftUI

struct PodcastsScreen: View {
    @State private var podcasts: [Podcast] = []
    @State private var isLoading = true
    @State private var isSyncing = false
    @State private var error: String?
    @State private var syncResult: String?
    @State private var searchText = ""

    private var filteredPodcasts: [Podcast] {
        if searchText.isEmpty { return podcasts }
        return podcasts.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            ($0.publisher?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView("Loading podcasts...")
                } else if let error {
                    errorView(error)
                } else if podcasts.isEmpty {
                    emptyView
                } else {
                    podcastList
                }
            }
            .navigationTitle("Podcasts")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        Task { await syncPodcasts() }
                    } label: {
                        if isSyncing {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                    }
                    .disabled(isSyncing)
                }
            }
            .task {
                await loadPodcasts()
            }
            .refreshable {
                await loadPodcasts()
            }
            .overlay(alignment: .bottom) {
                if let syncResult {
                    Text(syncResult)
                        .font(.footnote.bold())
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .padding(.bottom, 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .task(id: syncResult) {
                            // Keyed on the message so a replacement toast
                            // restarts the timer instead of inheriting the
                            // dying one (issue #181).
                            try? await Task.sleep(for: .seconds(3))
                            if !Task.isCancelled {
                                withAnimation { self.syncResult = nil }
                            }
                        }
                }
            }
        }
    }

    private var podcastList: some View {
        List(filteredPodcasts) { podcast in
            NavigationLink(value: podcast) {
                PodcastRow(podcast: podcast)
            }
        }
        .listStyle(.plain)
        .searchable(text: $searchText, prompt: "Search podcasts")
        .navigationDestination(for: Podcast.self) { podcast in
            PodcastDetailScreen(podcast: podcast) { updated in
                // Reflect detail-screen edits (e.g. the Sequential toggle)
                // in the list behind (issue #184).
                if let index = podcasts.firstIndex(where: { $0.id == updated.id }) {
                    podcasts[index] = updated
                }
            }
        }
    }

    private var emptyView: some View {
        ContentUnavailableView(
            "No Podcasts",
            systemImage: "mic.slash",
            description: Text("Tap sync to import your Spotify podcasts")
        )
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
            podcasts = try await APIClient.shared.fetchAllPodcasts()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func syncPodcasts() async {
        isSyncing = true
        do {
            let response = try await APIClient.shared.syncPodcasts()
            var message = "Synced \(response.synced) podcasts (\(response.new) new)"
            if let removed = response.removed, removed > 0 {
                message += ", removed \(removed) unsubscribed"
            }
            withAnimation {
                syncResult = message
            }
            NotificationService.shared.sendIfBackgrounded(
                title: "Podcast Sync Complete",
                body: message,
                identifier: "podcast-sync"
            )
            await loadPodcasts()
        } catch {
            withAnimation {
                syncResult = "Sync failed: \(error.localizedDescription)"
            }
        }
        isSyncing = false
    }
}
