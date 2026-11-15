import XCTest
@testable import PodcastManager

/// Issue #307: the login sends an S256 challenge and the exchange sends the
/// verifier, so the server can bind the exchange code to this app.
final class PKCETests: XCTestCase {
    /// The worked example from RFC 7636, appendix B.
    func testChallengeMatchesRFC7636Vector() {
        let pkce = PKCE(verifier: "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        XCTAssertEqual(pkce.challenge, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    }

    /// The backend accepts a 43-character base64url challenge and a verifier
    /// of 43 to 128 unreserved characters; anything else is a 400 or a 401.
    func testGeneratedPairHasTheShapeTheServerAccepts() {
        let pkce = PKCE()
        let urlSafe = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        XCTAssertEqual(pkce.verifier.count, 43)
        XCTAssertEqual(pkce.challenge.count, 43)
        XCTAssertTrue(pkce.verifier.unicodeScalars.allSatisfy(urlSafe.contains))
        XCTAssertTrue(pkce.challenge.unicodeScalars.allSatisfy(urlSafe.contains))
    }

    func testEachLoginGetsAFreshVerifier() {
        XCTAssertNotEqual(PKCE().verifier, PKCE().verifier)
    }
}
