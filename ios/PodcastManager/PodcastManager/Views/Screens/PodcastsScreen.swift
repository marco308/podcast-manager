import SwiftUI

struct PodcastsScreen: View {
    @State private var podcasts: [Podcast] = []
    @State private var isLoading = true
    @State private var isSyncing = false
    @State private var error: String?
    @State private var syncResult: String?

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
                        .onAppear {
                            Task {
                                try? await Task.sleep(for: .seconds(3))
                                withAnimation { self.syncResult = nil }
                            }
                        }
                }
            }
        }
    }

    private var podcastList: some View {
        List(podcasts) { podcast in
            PodcastRow(podcast: podcast)
        }
        .listStyle(.plain)
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
            let response = try await APIClient.shared.fetchPodcasts()
            podcasts = response.items
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
            withAnimation {
                syncResult = "Synced \(response.synced) podcasts (\(response.new) new)"
            }
            await loadPodcasts()
        } catch {
            withAnimation {
                syncResult = "Sync failed: \(error.localizedDescription)"
            }
        }
        isSyncing = false
    }
}
