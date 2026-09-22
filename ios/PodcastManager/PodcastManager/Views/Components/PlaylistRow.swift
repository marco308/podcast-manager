import SwiftUI

struct PlaylistRow: View {
    let playlist: Playlist
    let onRun: () async -> Void

    @State private var isRunning = false

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(playlist.name)
                        .font(.headline)

                    if !playlist.isEnabled {
                        Text("Disabled")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color(.systemGray5))
                            .clipShape(Capsule())
                    }
                }

                HStack(spacing: 12) {
                    Label("\(playlist.podcastCount) podcasts", systemImage: "mic.fill")
                    Label(playlist.ruleSummary, systemImage: "play.circle")
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                if playlist.isWeekendOnly {
                    Label("Weekend only", systemImage: "calendar")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
            }

            Spacer()

            Button {
                Task {
                    isRunning = true
                    await onRun()
                    isRunning = false
                }
            } label: {
                if isRunning {
                    ProgressView()
                        .frame(width: 24, height: 24)
                } else {
                    Image(systemName: "play.circle.fill")
                        .font(.title2)
                        .foregroundStyle(Color.accentColor)
                }
            }
            .buttonStyle(.plain)
            // A disabled playlist is never written to on Spotify, manual runs
            // included (issue #239) — the backend refuses them with a 409.
            .disabled(isRunning || !playlist.isEnabled)
            .accessibilityLabel(playlist.isEnabled ? "Run playlist" : "Run playlist, disabled")
        }
        .padding(.vertical, 4)
    }
}
