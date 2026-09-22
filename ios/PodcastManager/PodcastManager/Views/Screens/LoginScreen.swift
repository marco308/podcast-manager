import SwiftUI

struct LoginScreen: View {
    @Environment(AuthService.self) private var authService
    @State private var serverURLText = ServerConfig.baseURL?.absoluteString ?? ""
    @State private var serverError: String?

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

            VStack(alignment: .leading, spacing: 8) {
                Text("Server URL")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)

                TextField("https://your-server.example.com", text: $serverURLText)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(.URL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()

                if let serverError {
                    Text(serverError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .padding(.horizontal, 32)

            Button {
                signIn()
            } label: {
                HStack {
                    if authService.isLoading {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "music.note")
                    }
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
            .disabled(
                serverURLText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || authService.isLoading
            )

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

    private func signIn() {
        guard let url = ServerConfig.normalize(serverURLText) else {
            serverError = "Enter a valid server URL, e.g. https://api.example.com"
            return
        }
        serverError = nil
        ServerConfig.save(url)
        authService.login()
    }
}
