import SwiftUI

/// Marks a sleep playlist (docs/design/sleep-playlists.md) wherever one is
/// shown, so it is never mistaken for one that serves new episodes.
struct SleepBadge: View {
    var body: some View {
        Label("Sleep", systemImage: "moon.fill")
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.indigo.opacity(0.15))
            .foregroundStyle(.indigo)
            .clipShape(Capsule())
            .accessibilityLabel("Sleep playlist: only episodes you've already finished")
    }
}
