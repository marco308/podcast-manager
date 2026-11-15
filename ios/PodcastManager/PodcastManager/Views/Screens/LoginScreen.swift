import SwiftUI

struct LoginScreen: View {
    @Environment(AuthService.self) private var authService
    @State private var serverURLText = ServerConfig.baseURL?.absoluteString ?? ""
    @State private var serverError: String?

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image("Logo")
                .resizable()
                .frame(width: 96, height: 96)
                .accessibilityHidden(true)

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

                // Without this the field is a dead end for anyone who
                // installed the app without a server of their own.
                Text("Podcast Manager runs on your own server. [How to set one up](https://marco308.github.io/podcast-manager/)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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

            // For anyone without a server yet, including App Review
            // (issue #264): the whole app against sample data. A full-width
            // button with a line saying what it does, not a text link: App
            // Review stopped at this screen with the link in plain view
            // (issue #267, Guideline 2.1(a)).
            VStack(spacing: 8) {
                Button {
                    Task { await authService.startDemo() }
                } label: {
                    Text("Try the demo")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .foregroundStyle(.green)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(.green, lineWidth: 2)
                        )
                }
                .accessibilityHint("Opens the app with sample data. No server or account needed.")

                Text("No server or account needed. Explore every screen with sample shows.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 32)
            .disabled(authService.isLoading)

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
