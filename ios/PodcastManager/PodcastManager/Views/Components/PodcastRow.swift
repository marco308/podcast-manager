import SwiftUI

struct PodcastRow: View {
    let podcast: Podcast

    var body: some View {
        HStack(spacing: 12) {
            AsyncImage(url: podcast.imageUrl.flatMap(URL.init)) { image in
                image
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } placeholder: {
                Image(systemName: "mic.fill")
                    .font(.title2)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(.systemGray5))
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 4) {
                Text(podcast.name)
                    .font(.headline)
                    .lineLimit(1)

                if let publisher = podcast.publisher {
                    Text(publisher)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                HStack(spacing: 8) {
                    if let unplayed = podcast.unplayedEpisodes {
                        Label("\(unplayed)", systemImage: "play.circle")
                            .font(.caption2)
                            .foregroundStyle(Color.accentColor)
                    }

                    if podcast.isSequential {
                        Label("Sequential", systemImage: "arrow.right")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }
                }
            }

            Spacer()
        }
        .padding(.vertical, 2)
    }
}
