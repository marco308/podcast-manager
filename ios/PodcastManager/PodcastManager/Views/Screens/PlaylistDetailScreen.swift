import SwiftUI

struct PlaylistDetailScreen: View {
    /// Kept as state so an edit shows here without a round trip to the list.
    @State var playlist: Playlist
    /// Tells the list to reload after the playlist was edited or deleted,
    /// with a message to show there (deletes only, since this screen closes).
    var onChanged: ((String?) async -> Void)? = nil

    @Environment(\.dismiss) private var dismiss

    @State private var podcasts: [Podcast] = []
    @State private var isLoading = true
    @State private var error: String?
    @State private var showingAddSheet = false
    @State private var statusMessage: String?
    /// One reorder in flight at a time: each PUT sends the whole order, so
    /// two racing requests could land out of order and keep the stale one.
    @State private var isSavingOrder = false
    /// The row whose rule sheet is open.
    @State private var editingPodcast: Podcast?
    @State private var showingSettings = false

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
            if podcasts.count > 1 {
                ToolbarItem(placement: .topBarTrailing) {
                    EditButton()
                }
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showingAddSheet = true
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .sheet(isPresented: $showingAddSheet) {
            AddPodcastsSheet(playlistId: playlist.id, existingPodcastIds: Set(podcasts.map(\.id))) {
                await loadPodcasts()
            }
        }
        .sheet(isPresented: $showingSettings) {
            PlaylistFormSheet(playlist: playlist) { saved in
                playlist = saved
                withAnimation { statusMessage = "Playlist updated" }
                // New defaults change every inherited rule shown here.
                await loadPodcasts()
                await onChanged?(nil)
            } onDeleted: { message in
                await onChanged?(message)
                dismiss()
            }
        }
        .sheet(item: $editingPodcast) { podcast in
            AssignmentRuleSheet(playlist: playlist, podcast: podcast) {
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

    private var contentView: some View {
        // Settings stay visible with no podcasts: a new playlist starts empty
        // and its settings are still editable from here.
        List {
            settingsSection
            if podcasts.isEmpty {
                Section("Podcasts") {
                    ContentUnavailableView(
                        "No Podcasts",
                        systemImage: "mic.slash",
                        description: Text("Tap + to add podcasts to this playlist")
                    )
                }
            } else {
                podcastsSection
            }
        }
        .listStyle(.insetGrouped)
    }

    private var settingsSection: some View {
        Section {
            LabeledContent("Arrangement", value: playlist.arrangementLabel)
            LabeledContent("Episodes per podcast", value: playlist.ruleSummary)
            LabeledContent("Status", value: playlist.isEnabled ? "Enabled" : "Disabled")
            if let url = playlist.spotifyURL {
                // Universal link: opens the Spotify app when installed.
                Link(destination: url) {
                    Label("Open in Spotify", systemImage: "arrow.up.right.square")
                }
            } else {
                LabeledContent("Spotify playlist", value: "Created on first run")
            }
            Button {
                showingSettings = true
            } label: {
                Label("Edit Settings", systemImage: "slider.horizontal.3")
            }
        } header: {
            Text("Playlist Settings")
        } footer: {
            // One rule, defined by the backend (issue #239): a disabled
            // playlist is never written to on Spotify — not by the daily
            // rebuild, not by cleanup, and not by a manual run either.
            if !playlist.isEnabled {
                Text(
                    "Disabled playlists are never written to on Spotify: no daily rebuild, "
                        + "no cleanup of played episodes, and Run is unavailable."
                )
            }
        }
    }

    private var podcastsSection: some View {
        Section {
            ForEach(podcasts) { podcast in
                Button {
                    editingPodcast = podcast
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        PodcastRow(podcast: podcast)
                        if let rule = podcast.rule {
                            ruleCaption(rule)
                        }
                    }
                }
                // Keep the row's own colours instead of the button tint,
                // while still getting the row highlight on tap.
                .tint(.primary)
                .accessibilityHint("Edit episodes and play order for this playlist")
                .moveDisabled(isSavingOrder)
            }
            .onDelete { indexSet in
                Task { await removePodcasts(at: indexSet) }
            }
            .onMove(perform: movePodcasts)
        } header: {
            Text("Podcasts (\(podcasts.count))")
        } footer: {
            // Same hint as the web editor: the order is kept either way, but
            // only a by-position playlist plays shows in it.
            let editHint = "Tap a podcast to change how many episodes it adds and where it starts."
            if podcasts.count > 1 {
                Text(
                    editHint + " "
                        + (playlist.arrangement == "by_position"
                            ? "Tap Edit and drag rows to set the order podcasts play in."
                            : "Row order is only used when the arrangement is \"Podcast order\".")
                )
            } else {
                Text(editHint)
            }
        }
    }

    /// One caption line: the resolved rule plus a badge saying why it differs
    /// from the playlist default, if it does.
    private func ruleCaption(_ rule: AssignmentRule) -> some View {
        HStack(spacing: 6) {
            Text(rule.summary)
            if rule.isCustom {
                ruleBadge("Custom", color: Color.accentColor)
            } else if rule.pickFromSource == "sequential" {
                ruleBadge("Sequential", color: .orange)
            }
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .padding(.leading, 68) // align under the text column of PodcastRow (56pt art + 12pt gap)
    }

    private func ruleBadge(_ text: String, color: Color) -> some View {
        Text(text)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private func errorView(_ message: String) -> some View {
        ScrollView {
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                    .padding(.top, 40)
                Text("Error")
                    .font(.headline)
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .textSelection(.enabled)
                    .padding(.horizontal)
                Button("Retry") {
                    Task { await loadPodcasts() }
                }
            }
            .frame(maxWidth: .infinity)
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

    /// Move synchronously so the row stays where it was dropped, then save
    /// the whole order. On failure, reload: the server's order is the truth
    /// (a 400 usually means the playlist changed elsewhere meanwhile).
    private func movePodcasts(from source: IndexSet, to destination: Int) {
        let before = podcasts.map(\.id)
        podcasts.move(fromOffsets: source, toOffset: destination)
        let order = podcasts.map(\.id)
        guard order != before else { return }

        isSavingOrder = true
        Task {
            defer { isSavingOrder = false }
            do {
                _ = try await APIClient.shared.reorderPlaylistPodcasts(playlistId: playlist.id, podcastIds: order)
            } catch {
                withAnimation {
                    statusMessage = "Failed to reorder: \(error.localizedDescription)"
                }
                await loadPodcasts()
            }
        }
    }

    private func removePodcasts(at offsets: IndexSet) async {
        let podcastsToRemove = offsets.map { podcasts[$0] }
        var removedIds: Set<Int> = []
        for podcast in podcastsToRemove {
            do {
                let response = try await APIClient.shared.removePodcastFromPlaylist(
                    playlistId: playlist.id,
                    podcastId: podcast.id
                )
                removedIds.insert(podcast.id)
                withAnimation {
                    statusMessage = response.message
                }
            } catch {
                withAnimation {
                    statusMessage = "Failed to remove: \(error.localizedDescription)"
                }
            }
        }
        if !removedIds.isEmpty {
            withAnimation {
                podcasts.removeAll { removedIds.contains($0.id) }
            }
        }
    }
}
