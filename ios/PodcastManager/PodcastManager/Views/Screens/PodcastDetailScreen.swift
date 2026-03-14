import SwiftUI

struct PodcastDetailScreen: View {
    @State var podcast: Podcast
    @State private var playlists: [Playlist] = []
    @State private var isUpdating = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                artworkSection
                infoSection
                statsSection
                sequentialToggleSection
                playlistsSection
            }
            .padding()
        }
        .navigationTitle(podcast.name)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await loadPlaylists()
        }
        .alert("Error", isPresented: .init(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            if let error {
                Text(error)
            }
        }
    }

    // MARK: - Artwork

    private var artworkSection: some View {
        AsyncImage(url: podcast.imageUrl.flatMap(URL.init)) { image in
            image
                .resizable()
                .aspectRatio(contentMode: .fit)
        } placeholder: {
            Image(systemName: "mic.fill")
                .font(.system(size: 60))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(.systemGray5))
        }
        .frame(width: 200, height: 200)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .shadow(radius: 8, y: 4)
    }

    // MARK: - Info

    private var infoSection: some View {
        VStack(spacing: 8) {
            Text(podcast.name)
                .font(.title2.bold())
                .multilineTextAlignment(.center)

            if let publisher = podcast.publisher {
                Text(publisher)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if let description = podcast.description {
                Text(description)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineLimit(6)
                    .padding(.top, 4)
            }
        }
    }

    // MARK: - Stats

    private var statsSection: some View {
        HStack(spacing: 16) {
            statCard(
                title: "Total",
                value: "\(podcast.totalEpisodes)",
                icon: "number",
                color: .blue
            )

            statCard(
                title: "Unplayed",
                value: "\(podcast.unplayedEpisodes)",
                icon: "play.circle",
                color: Color.accentColor
            )

            if podcast.isSequential {
                statCard(
                    title: "Sequential",
                    value: "Yes",
                    icon: "arrow.right",
                    color: .orange
                )
            }
        }
    }

    private func statCard(title: String, value: String, icon: String, color: Color) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(color)

            Text(value)
                .font(.title3.bold())

            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    // MARK: - Sequential Toggle

    private var sequentialToggleSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Settings")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack {
                Label("Sequential Playback", systemImage: "arrow.right")
                Spacer()
                if isUpdating {
                    ProgressView()
                } else {
                    Toggle("", isOn: Binding(
                        get: { podcast.isSequential },
                        set: { newValue in
                            Task { await toggleSequential(newValue) }
                        }
                    ))
                    .labelsHidden()
                }
            }
            .padding()
            .background(Color(.systemGray6))
            .clipShape(RoundedRectangle(cornerRadius: 12))

            Text("Sequential podcasts are played oldest-to-newest")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Playlists

    private var playlistsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Playlists")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)

            if podcast.playlistIds.isEmpty {
                Text("Not assigned to any playlists")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                let matchingPlaylists = playlists.filter { podcast.playlistIds.contains($0.id) }
                if matchingPlaylists.isEmpty && !playlists.isEmpty {
                    // Playlists loaded but none match - show IDs as fallback
                    ForEach(podcast.playlistIds, id: \.self) { playlistId in
                        playlistCard(name: "Playlist #\(playlistId)")
                    }
                } else if matchingPlaylists.isEmpty {
                    // Still loading playlists
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding()
                } else {
                    ForEach(matchingPlaylists) { playlist in
                        playlistCard(name: playlist.name)
                    }
                }
            }
        }
    }

    private func playlistCard(name: String) -> some View {
        HStack {
            Image(systemName: "music.note.list")
                .foregroundStyle(Color.accentColor)
            Text(name)
                .font(.subheadline)
            Spacer()
        }
        .padding()
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    // MARK: - Actions

    private func toggleSequential(_ newValue: Bool) async {
        isUpdating = true
        do {
            let updated = try await APIClient.shared.updatePodcast(
                spotifyId: podcast.spotifyId,
                isSequential: newValue
            )
            podcast = updated
        } catch {
            self.error = error.localizedDescription
        }
        isUpdating = false
    }

    private func loadPlaylists() async {
        guard !podcast.playlistIds.isEmpty else { return }
        do {
            let response = try await APIClient.shared.fetchPlaylists()
            playlists = response.items
        } catch {
            // Non-critical - playlists section will show IDs as fallback
        }
    }
}
