import SwiftUI

/// Edit what one podcast contributes to one playlist: how many episodes and
/// which end they come from (the per-assignment overrides, issue #249), plus
/// the podcast-wide sequential flag that feeds the inherited direction.
/// Mirrors the Episodes / Take from columns of the web playlist editor.
struct AssignmentRuleSheet: View {
    let playlist: Playlist
    let podcast: Podcast
    /// Called after anything was saved, so the list can reload the resolved rules.
    let onSaved: () async -> Void

    @Environment(\.dismiss) private var dismiss

    /// Episode-limit override as the picker sees it; `custom` keeps a number
    /// >= 2 in `customLimit` (same split as the web editor).
    private enum LimitChoice: Hashable {
        case inherit, all, latest, custom
    }

    private enum PickChoice: Hashable {
        case inherit, newest, oldest
    }

    @State private var limitChoice: LimitChoice
    @State private var customLimit: Int
    @State private var pickChoice: PickChoice
    @State private var isSequential: Bool
    @State private var isSaving = false
    @State private var error: String?

    private let originalOverride: AssignmentOverride

    init(playlist: Playlist, podcast: Podcast, onSaved: @escaping () async -> Void) {
        self.playlist = playlist
        self.podcast = podcast
        self.onSaved = onSaved

        // Rows always carry `override` from current backends; fall back to the
        // rule's sources so an older one still opens on the right choices.
        let override = podcast.override ?? AssignmentOverride(
            episodeLimit: podcast.rule?.episodeLimitSource == "override" ? podcast.rule?.episodeLimit : nil,
            pickFrom: podcast.rule?.pickFromSource == "override" ? podcast.rule?.pickFrom : nil
        )
        originalOverride = override

        switch override.episodeLimit {
        case nil: _limitChoice = State(initialValue: .inherit)
        case 0: _limitChoice = State(initialValue: .all)
        case 1: _limitChoice = State(initialValue: .latest)
        default: _limitChoice = State(initialValue: .custom)
        }
        _customLimit = State(initialValue: max(2, override.episodeLimit ?? 2))
        switch override.pickFrom {
        case "newest": _pickChoice = State(initialValue: .newest)
        case "oldest": _pickChoice = State(initialValue: .oldest)
        default: _pickChoice = State(initialValue: .inherit)
        }
        _isSequential = State(initialValue: podcast.isSequential)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    PodcastRow(podcast: podcast)
                    LabeledContent("Next rebuild", value: episodeRuleSummary(
                        limit: resolvedLimit,
                        pickFrom: resolvedPickFrom
                    ))
                }

                episodesSection
                takeFromSection
                sequentialSection

                if newOverride != AssignmentOverride() {
                    Section {
                        Button("Use Playlist Defaults") {
                            limitChoice = .inherit
                            pickChoice = .inherit
                        }
                    }
                }
            }
            .navigationTitle(playlist.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView()
                    } else {
                        Button("Save") {
                            Task { await save() }
                        }
                        .disabled(!hasChanges)
                    }
                }
            }
            .interactiveDismissDisabled(isSaving)
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

    private var episodesSection: some View {
        Section {
            Picker("Episodes", selection: $limitChoice) {
                Text("Playlist default (\(episodeLimitLabel(playlist.defaultEpisodeLimit)))").tag(LimitChoice.inherit)
                Text("All unplayed").tag(LimitChoice.all)
                Text("Latest only").tag(LimitChoice.latest)
                Text("Up to…").tag(LimitChoice.custom)
            }
            .pickerStyle(.inline)
            .labelsHidden()

            if limitChoice == .custom {
                Stepper(
                    "Up to \(customLimit) episodes",
                    value: $customLimit,
                    in: 2...AssignmentOverride.episodeLimitMax
                )
            }
        } header: {
            Text("Episodes")
        } footer: {
            Text("How many unplayed episodes this podcast adds on each rebuild.")
        }
    }

    private var takeFromSection: some View {
        Section {
            Picker("Take from", selection: $pickChoice) {
                Text("Default (\(inheritedPickFrom)\(isSequential ? ", sequential" : ""))").tag(PickChoice.inherit)
                Text("Newest").tag(PickChoice.newest)
                Text("Oldest").tag(PickChoice.oldest)
            }
            .pickerStyle(.inline)
            .labelsHidden()
        } header: {
            Text("Take From")
        } footer: {
            Text("Newest takes the latest unplayed episodes. Oldest starts from the earliest unplayed one, so a series plays in order.")
        }
    }

    private var sequentialSection: some View {
        Section {
            Toggle("Sequential", isOn: $isSequential)
        } footer: {
            Text("Applies to this podcast in every playlist: it takes from the oldest unplayed episode unless Take From is set above.")
        }
    }

    // MARK: - State

    private var newOverride: AssignmentOverride {
        let limit: Int? = switch limitChoice {
        case .inherit: nil
        case .all: 0
        case .latest: 1
        case .custom: customLimit
        }
        let pick: String? = switch pickChoice {
        case .inherit: nil
        case .newest: "newest"
        case .oldest: "oldest"
        }
        return AssignmentOverride(episodeLimit: limit, pickFrom: pick)
    }

    private var hasChanges: Bool {
        newOverride != originalOverride || isSequential != podcast.isSequential
    }

    /// The direction an un-overridden row gets, as `resolve_rule` decides it.
    private var inheritedPickFrom: String {
        isSequential ? "oldest" : playlist.defaultPickFrom
    }

    private var resolvedLimit: Int {
        newOverride.episodeLimit ?? playlist.defaultEpisodeLimit
    }

    private var resolvedPickFrom: String {
        newOverride.pickFrom ?? inheritedPickFrom
    }

    private func episodeLimitLabel(_ limit: Int) -> String {
        switch limit {
        case 0: return "All unplayed"
        case 1: return "Latest only"
        default: return "Up to \(limit)"
        }
    }

    // MARK: - Save

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        var savedSomething = false
        do {
            if isSequential != podcast.isSequential {
                _ = try await APIClient.shared.updatePodcast(id: podcast.id, isSequential: isSequential)
                savedSomething = true
            }
            if newOverride != originalOverride {
                _ = try await APIClient.shared.updateAssignmentOverride(
                    playlistId: playlist.id,
                    podcastId: podcast.id,
                    override: newOverride
                )
                savedSomething = true
            }
            await onSaved()
            dismiss()
        } catch {
            // The sequential flag may already be saved; reload so the list
            // doesn't keep showing the old rule behind the sheet.
            if savedSomething {
                await onSaved()
            }
            self.error = error.localizedDescription
        }
    }
}
