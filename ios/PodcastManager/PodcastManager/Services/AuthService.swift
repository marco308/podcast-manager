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

                // Mobile OAuth now returns a single-use exchange code in the
                // callback URL instead of the raw session credentials. Pull
                // the code out of the URL and trade it for real credentials
                // via POST /api/auth/mobile-exchange — credentials then arrive
                // in the JSON body, never in a URL or device log.
                guard let callbackURL,
                      let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false),
                      let code = components.queryItems?.first(where: { $0.name == "code" })?.value
                else {
                    self.error = "Failed to get exchange code from login"
                    return
                }

                do {
                    let creds = try await APIClient.shared.exchangeMobileAuthCode(code)
                    KeychainService.save(creds.sessionId, for: .sessionId)
                    KeychainService.save(creds.csrfToken, for: .csrfToken)
                    self.isAuthenticated = true
                    await self.fetchUser()
                } catch {
                    self.error = "Failed to complete login: \(error.localizedDescription)"
                }
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
