import AuthenticationServices
import Foundation
import SwiftUI

@Observable
@MainActor
class AuthService {
    var isAuthenticated = false
    var currentUser: User?
    var isLoading = false
    var error: String?

    // Must retain these or the auth session gets deallocated
    private var authSession: ASWebAuthenticationSession?
    private var contextProvider: PresentationContextProvider?

    init() {
        isAuthenticated = KeychainService.get(.sessionId) != nil
    }

    func login() {
        error = nil
        let loginURL = URL(string: "https://api-podcastmanager.marcuslab.uk/api/auth/login?redirect_scheme=podcastmanager")!

        let session = ASWebAuthenticationSession(
            url: loginURL,
            callback: .customScheme("podcastmanager")
        ) { [weak self] callbackURL, error in
            Task { @MainActor in
                guard let self else { return }
                self.authSession = nil
                self.contextProvider = nil

                if let error {
                    if (error as NSError).code == ASWebAuthenticationSessionError.canceledLogin.rawValue {
                        return
                    }
                    self.error = error.localizedDescription
                    return
                }

                guard let callbackURL,
                      let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false),
                      let sessionId = components.queryItems?.first(where: { $0.name == "session_id" })?.value,
                      let csrfToken = components.queryItems?.first(where: { $0.name == "csrf_token" })?.value
                else {
                    self.error = "Failed to get session from login"
                    return
                }

                KeychainService.save(sessionId, for: .sessionId)
                KeychainService.save(csrfToken, for: .csrfToken)
                self.isAuthenticated = true

                await self.fetchUser()
            }
        }

        session.prefersEphemeralWebBrowserSession = true

        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = windowScene.windows.first(where: { $0.isKeyWindow }) ?? windowScene.windows.first
        else {
            self.error = "Unable to find app window"
            return
        }

        let provider = PresentationContextProvider(window: window)
        self.contextProvider = provider
        self.authSession = session

        session.presentationContextProvider = provider
        session.start()
    }

    func fetchUser() async {
        do {
            currentUser = try await APIClient.shared.fetchCurrentUser()
        } catch let apiError as APIError where apiError.isUnauthorized {
            logout()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func logout() {
        KeychainService.clearAll()
        isAuthenticated = false
        currentUser = nil
    }
}

private class PresentationContextProvider: NSObject, ASWebAuthenticationPresentationContextProviding {
    let window: UIWindow

    init(window: UIWindow) {
        self.window = window
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        window
    }
}
