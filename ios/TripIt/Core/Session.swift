import Foundation
import Observation

/// Who's signed in. The session token lives in the shared Keychain, so the Share Extension can use it too.
@MainActor
@Observable
final class Session {
    enum Phase { case checking, signedOut, signedIn }

    var phase: Phase = SessionStore.token == nil ? .signedOut : .checking
    var me: Me?

    func restore() async {
        guard SessionStore.token != nil else { phase = .signedOut; return }
        do {
            me = try await API.shared.get("/v1/me", as: Me?.self)
            phase = .signedIn
        } catch let error as APIError where error.isSignedOut {
            signOutLocally()
        } catch {
            phase = .signedIn  // offline: carry on with what the app has
        }
    }

    func signIn(email: String, password: String) async throws {
        let out: SessionOut = try await API.shared.post("/v1/auth/login", ["email": email, "password": password])
        start(out)
    }

    func signUp(email: String, password: String, name: String, invite: String) async throws {
        let out: SessionOut = try await API.shared.post("/v1/auth/signup",
                                                        ["email": email, "password": password, "name": name, "invite": invite])
        start(out)
    }

    private func start(_ out: SessionOut) {
        SessionStore.save(out.token)
        me = out.user
        phase = .signedIn
    }

    func signOut() async {
        await Push.shared.unregister()
        try? await API.shared.call("POST", "/v1/auth/logout")
        signOutLocally()
    }

    func signOutLocally() {
        SessionStore.clear()
        WebSession.clearCookies()
        me = nil
        phase = .signedOut
    }
}
