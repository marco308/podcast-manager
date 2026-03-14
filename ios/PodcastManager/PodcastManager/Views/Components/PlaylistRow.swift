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
                    Label(episodeModeLabel, systemImage: "play.circle")
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
            .disabled(isRunning || !playlist.isEnabled)
        }
        .padding(.vertical, 4)
    }

    private var episodeModeLabel: String {
        switch playlist.episodeMode {
        case "latest_only": return "Latest only"
        default: return "All unplayed"
        }
    }
}
