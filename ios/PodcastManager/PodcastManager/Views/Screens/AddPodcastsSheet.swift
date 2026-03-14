import SwiftUI

struct AddPodcastsSheet: View {
    let playlistId: Int
    let existingPodcastIds: Set<Int>
    let onAdded: () async -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var availablePodcasts: [Podcast] = []
    @State private var selectedIds: Set<Int> = []
    @State private var isLoading = true
    @State private var isAdding = false
    @State private var error: String?
    @State private var searchText = ""

    private var filteredPodcasts: [Podcast] {
        if searchText.isEmpty { return availablePodcasts }
        return availablePodcasts.filter {
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
                } else if availablePodcasts.isEmpty {
                    ContentUnavailableView(
                        "No Podcasts Available",
                        systemImage: "mic.slash",
                        description: Text("All podcasts are already in this playlist")
                    )
                } else {
                    podcastList
                }
            }
            .navigationTitle("Add Podcasts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        Task { await addSelected() }
                    }
                    .disabled(selectedIds.isEmpty || isAdding)
                }
            }
            .task {
                await loadAvailablePodcasts()
            }
        }
    }

    private var podcastList: some View {
        List(filteredPodcasts) { podcast in
            Button {
                toggleSelection(podcast.id)
            } label: {
                HStack {
                    PodcastRow(podcast: podcast)

                    Spacer()

                    Image(systemName: selectedIds.contains(podcast.id) ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(selectedIds.contains(podcast.id) ? Color.accentColor : .secondary)
                }
            }
            .buttonStyle(.plain)
        }
        .listStyle(.plain)
        .searchable(text: $searchText, prompt: "Search podcasts")
    }

    private func errorView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Error", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Retry") {
                Task { await loadAvailablePodcasts() }
            }
        }
    }

    private func toggleSelection(_ id: Int) {
        if selectedIds.contains(id) {
            selectedIds.remove(id)
        } else {
            selectedIds.insert(id)
        }
    }

    private func loadAvailablePodcasts() async {
        do {
            let response = try await APIClient.shared.fetchPodcasts(limit: 100)
            availablePodcasts = response.items.filter { !existingPodcastIds.contains($0.id) }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func addSelected() async {
        isAdding = true
        do {
            _ = try await APIClient.shared.addPodcastsToPlaylist(
                playlistId: playlistId,
                podcastIds: Array(selectedIds)
            )
            await onAdded()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
        isAdding = false
    }
}
