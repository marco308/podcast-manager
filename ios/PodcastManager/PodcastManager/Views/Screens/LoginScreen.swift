import SwiftUI

struct LoginScreen: View {
    @Environment(AuthService.self) private var authService

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "mic.fill")
                .font(.system(size: 64))
                .foregroundStyle(Color.accentColor)

            VStack(spacing: 8) {
                Text("Podcast Manager")
                    .font(.largeTitle.bold())

                Text("Manage your podcasts and playlists")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button {
                authService.login()
            } label: {
                HStack {
                    Image(systemName: "music.note")
                    Text("Sign in with Spotify")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding()
                .background(.green)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .padding(.horizontal, 32)

            if let error = authService.error {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }

            Spacer()
                .frame(height: 48)
        }
    }
}
