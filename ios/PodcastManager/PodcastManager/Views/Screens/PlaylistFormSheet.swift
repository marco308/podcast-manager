import SwiftUI

/// Create a playlist, or edit one's settings: name, Spotify link, arrangement,
/// the defaults its podcasts inherit, and enabled. Mirrors the web form's
/// fields and wording; podcasts themselves are managed on the detail screen.
struct PlaylistFormSheet: View {
    /// nil creates a new playlist.
    let playlist: Playlist?
    let onSaved: (Playlist) async -> Void
    /// Called after a delete, once the sheet is closing. Edit only.
    var onDeleted: ((String) async -> Void)? = nil

    @Environment(\.dismiss) private var dismiss

    private enum LimitChoice: Hashable {
        case all, latest, custom
    }

    @State private var draft: PlaylistDraft
    @State private var limitChoice: LimitChoice
    @State private var customLimit: Int
    @State private var isSaving = false
    @State private var error: String?
    @State private var confirmingDelete = false

    @State private var spotifyOptions: SpotifyPlaylistListResponse?
    @State private var spotifyError: String?

    private let original: PlaylistDraft

    init(
        playlist: Playlist?,
        onSaved: @escaping (Playlist) async -> Void,
        onDeleted: ((String) async -> Void)? = nil
    ) {
        self.playlist = playlist
        self.onSaved = onSaved
        self.onDeleted = onDeleted
        let draft = playlist.map(PlaylistDraft.init) ?? .new
        original = draft
        _draft = State(initialValue: draft)
        switch draft.defaultEpisodeLimit {
        case 0: _limitChoice = State(initialValue: .all)
        case 1: _limitChoice = State(initialValue: .latest)
        default: _limitChoice = State(initialValue: .custom)
        }
        _customLimit = State(initialValue: max(2, draft.defaultEpisodeLimit))
    }

    var body: some View {
        NavigationStack {
            Form {
                nameSection
                kindSection
                spotifySection
                arrangementSection
                episodesSection
                takeFromSection
                enabledSection
                if playlist != nil {
                    deleteSection
                }
            }
            .navigationTitle(playlist == nil ? "New Playlist" : "Playlist Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView()
                    } else {
                        Button(playlist == nil ? "Create" : "Save") {
                            Task { await save() }
                        }
                        .disabled(!canSave)
                    }
                }
            }
            .interactiveDismissDisabled(isSaving || hasChanges)
            .task {
                await loadSpotifyPlaylists()
            }
            .alert("Couldn't Save", isPresented: .init(
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
    }

    // MARK: - Sections

    private var nameSection: some View {
        Section {
            TextField("e.g. Morning Podcasts", text: $draft.name)
                .textInputAutocapitalization(.words)
        } header: {
            Text("Name")
        } footer: {
            if playlist?.spotifyURL != nil {
                Text("Renaming here also renames the playlist on Spotify.")
            }
        }
    }

    private var kindSection: some View {
        Section {
            Picker("Kind", selection: Binding(get: { draft.kind }, set: { setKind($0) })) {
                Text("Standard").tag(PlaylistKind.standard)
                Label("Sleep", systemImage: "moon.fill").tag(PlaylistKind.sleep)
            }
            .pickerStyle(.segmented)
        } header: {
            Text("Kind")
        } footer: {
            Text(draft.isSleep
                ? "Sleep plays only episodes you've already finished \u{2014} for falling asleep to."
                : "Standard plays episodes you haven't heard yet.")
        }
    }

    private var spotifySection: some View {
        Section {
            NavigationLink {
                SpotifyPlaylistPicker(
                    selection: $draft.spotifyPlaylistId,
                    currentPlaylistId: playlist?.id,
                    options: spotifyOptions,
                    error: spotifyError,
                    retry: { await loadSpotifyPlaylists() }
                )
            } label: {
                LabeledContent("Spotify playlist", value: spotifyLabel)
            }
            if draft.spotifyPlaylistId != nil, let url = linkedURL {
                Link(destination: url) {
                    Label("Open in Spotify", systemImage: "arrow.up.right.square")
                }
            }
        } footer: {
            if draft.spotifyPlaylistId != nil {
                Text("This Spotify playlist will be fully overwritten on every rebuild. Anything you add to it in Spotify will be removed.")
                    .foregroundStyle(.orange)
            } else if original.spotifyPlaylistId != nil {
                Text("Unlinking leaves the old playlist alone on Spotify; a new one is created on the next run.")
            } else {
                Text("Leave it as New and a Spotify playlist is created on the first run, or pick one of your own playlists to take it over.")
            }
        }
    }

    private var arrangementSection: some View {
        Section {
            Picker("Arrangement", selection: $draft.arrangement) {
                Text("In podcast order").tag("by_position")
                Text("By release date").tag("by_date")
                Text("Shuffled").tag("shuffle")
            }
            if draft.arrangement == "by_date" {
                Picker("Direction", selection: $draft.dateDirection) {
                    Text("Newest first").tag("newest_first")
                    Text("Oldest first").tag("oldest_first")
                }
            }
        } footer: {
            Text("Group each podcast's episodes in the order you set, merge every episode by release date, or shuffle podcasts together (each podcast's own episodes stay in order).")
        }
    }

    private var episodesSection: some View {
        Section {
            Picker("Episodes per podcast", selection: $limitChoice) {
                Text(episodeLimitLabel(0, sleep: draft.isSleep)).tag(LimitChoice.all)
                Text(episodeLimitLabel(1, sleep: draft.isSleep)).tag(LimitChoice.latest)
                Text("Up to…").tag(LimitChoice.custom)
            }
            if limitChoice == .custom {
                Stepper(
                    "Up to \(customLimit) episodes",
                    value: $customLimit,
                    in: 2...AssignmentOverride.episodeLimitMax
                )
            }
        } footer: {
            Text("The default for every podcast in this playlist; tap a podcast in the playlist to override it.")
        }
    }

    private var takeFromSection: some View {
        Section {
            Picker("Take from", selection: $draft.defaultPickFrom) {
                Text("Newest").tag("newest")
                Text("Oldest").tag("oldest")
                // Only a sleep playlist accepts a random pick (the server 422s it elsewhere).
                if draft.isSleep {
                    Text("Random").tag("random")
                }
            }
        } footer: {
            Text(draft.isSleep
                ? "Random draws a fresh set of played episodes on every rebuild."
                : "Sequential podcasts always take from the oldest unfinished episode unless overridden on the podcast.")
        }
    }

    private var enabledSection: some View {
        Section {
            Toggle("Enabled", isOn: $draft.isEnabled)
        } footer: {
            Text("Disabled playlists are never written to on Spotify: no daily rebuild, no cleanup of played episodes, and Run is unavailable. The Spotify playlist keeps whatever it had.")
        }
    }

    private var deleteSection: some View {
        Section {
            Button("Delete Playlist", role: .destructive) {
                confirmingDelete = true
            }
            .disabled(isSaving)
            .confirmationDialog(
                "Delete \u{201C}\(playlist?.name ?? "")\u{201D}?",
                isPresented: $confirmingDelete,
                titleVisibility: .visible
            ) {
                if playlist?.spotifyURL != nil {
                    Button("Delete Here and on Spotify", role: .destructive) {
                        Task { await delete(removeFromSpotify: true) }
                    }
                    Button("Delete Here Only", role: .destructive) {
                        Task { await delete(removeFromSpotify: false) }
                    }
                } else {
                    Button("Delete Playlist", role: .destructive) {
                        Task { await delete(removeFromSpotify: false) }
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                if playlist?.spotifyURL != nil {
                    Text("Deleting here only leaves the Spotify playlist in place, no longer updated.")
                } else {
                    Text("Its podcasts stay in your library.")
                }
            }
        }
    }

    // MARK: - State

    /// Kind changes carry presets (see `PlaylistDraft.setKind`); the episode
    /// limit lives in `limitChoice` / `customLimit` here, so mirror it.
    private func setKind(_ kind: String) {
        draft.setKind(kind)
        if draft.isSleep {
            limitChoice = .custom
            customLimit = draft.defaultEpisodeLimit
        }
    }

    private var trimmedName: String {
        draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var finalDraft: PlaylistDraft {
        var result = draft
        result.name = trimmedName
        result.defaultEpisodeLimit = switch limitChoice {
        case .all: 0
        case .latest: 1
        case .custom: customLimit
        }
        return result
    }

    private var hasChanges: Bool {
        finalDraft != original
    }

    private var canSave: Bool {
        !trimmedName.isEmpty && trimmedName.count <= 255 && (playlist == nil || hasChanges)
    }

    private var spotifyLabel: String {
        guard let id = draft.spotifyPlaylistId else { return "New" }
        if let option = spotifyOptions?.items.first(where: { $0.id == id }) {
            return option.name.isEmpty ? id : option.name
        }
        return "Linked"
    }

    private var linkedURL: URL? {
        draft.spotifyPlaylistId.flatMap { URL(string: "https://open.spotify.com/playlist/\($0)") }
    }

    // MARK: - Actions

    private func loadSpotifyPlaylists() async {
        spotifyError = nil
        do {
            spotifyOptions = try await APIClient.shared.fetchSpotifyPlaylists()
        } catch {
            spotifyError = error.localizedDescription
        }
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        do {
            let saved = if let playlist {
                try await APIClient.shared.updatePlaylist(id: playlist.id, draft: finalDraft)
            } else {
                try await APIClient.shared.createPlaylist(finalDraft)
            }
            // Close first: the caller's reload shouldn't hold the sheet open.
            dismiss()
            await onSaved(saved)
        } catch {
            // The server says what it refused: a rename Spotify rejected
            // (nothing saved), a link that isn't yours, or one already in use.
            self.error = error.localizedDescription
        }
    }

    private func delete(removeFromSpotify: Bool) async {
        guard let playlist else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            let response = try await APIClient.shared.deletePlaylist(
                id: playlist.id,
                removeFromSpotify: removeFromSpotify
            )
            dismiss()
            await onDeleted?(response.message)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Pick one of the user's own Spotify playlists to link, or none. Playlists
/// already linked to another managed playlist are listed but can't be picked:
/// two playlists would overwrite each other on every rebuild.
private struct SpotifyPlaylistPicker: View {
    @Binding var selection: String?
    let currentPlaylistId: Int?
    let options: SpotifyPlaylistListResponse?
    let error: String?
    let retry: () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    private var filtered: [SpotifyPlaylistOption] {
        let items = options?.items ?? []
        if searchText.isEmpty { return items }
        return items.filter { $0.name.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        List {
            Section {
                row(title: "New playlist", subtitle: "Created on the next run", isSelected: selection == nil) {
                    selection = nil
                    dismiss()
                }
            }

            Section {
                if let error, options == nil {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Couldn't load your Spotify playlists")
                            .font(.headline)
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Button("Retry") {
                            Task { await retry() }
                        }
                    }
                } else if options == nil {
                    HStack {
                        ProgressView()
                        Text("Loading your Spotify playlists…")
                            .foregroundStyle(.secondary)
                    }
                } else if filtered.isEmpty {
                    Text(searchText.isEmpty ? "You don't own any Spotify playlists." : "No matches")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(filtered) { option in
                        let linkedElsewhere = option.linkedPlaylistId != nil
                            && option.linkedPlaylistId != currentPlaylistId
                        row(
                            title: option.name.isEmpty ? option.id : option.name,
                            subtitle: linkedElsewhere
                                ? "Already linked to another playlist"
                                : "\(option.itemCount) item\(option.itemCount == 1 ? "" : "s")",
                            isSelected: selection == option.id
                        ) {
                            selection = option.id
                            dismiss()
                        }
                        .disabled(linkedElsewhere)
                    }
                }
            } header: {
                Text("Your Spotify Playlists")
            } footer: {
                if options?.truncated == true {
                    Text("Only your first 1,000 playlists are listed.")
                }
            }
        }
        .searchable(text: $searchText)
        .navigationTitle("Spotify Playlist")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func row(title: String, subtitle: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark")
                        .foregroundStyle(Color.accentColor)
                }
            }
        }
        .tint(.primary)
    }
}
