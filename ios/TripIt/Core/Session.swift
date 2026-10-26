import Foundation
import Observation

/// Who's signed in. The session token lives in the shared Keychain, so the Share Extension can use it too.
@MainActor
@Observable
final class Session {
    enum Phase { case checking, signedOut, signedIn }

    /// Signed in from the last launch: the app opens straight away and checks with the server in the background.
    var phase: Phase = SessionStore.token == nil ? .signedOut : (Session.cachedMe == nil ? .checking : .signedIn)
    var me: Me? = Session.cachedMe

    private static let meKey = "session.me"
    static var cachedMe: Me? {
        get { UserDefaults.standard.data(forKey: meKey).flatMap { try? JSONDecoder().decode(Me.self, from: $0) } }
        set { UserDefaults.standard.set(newValue.flatMap { try? JSONEncoder().encode($0) }, forKey: meKey) }
    }

    func restore() async {
        guard SessionStore.token != nil else { phase = .signedOut; return }
        do {
            me = try await API.shared.get("/v1/me", as: Me?.self)
            Session.cachedMe = me
            Monitoring.setUser(me?.id)
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

    func signInWithApple(token: String, code: String?, nonce: String, name: String) async throws {
        let out: SessionOut = try await API.shared.post("/v1/auth/apple",
                                                        ["identity_token": token, "authorization_code": code, "nonce": nonce, "name": name])
        start(out)
    }

    func setName(_ name: String) async throws {
        me = try await API.shared.patch("/v1/me", ["name": name.trimmingCharacters(in: .whitespaces)], as: Me.self)
        Session.cachedMe = me
    }

    private func start(_ out: SessionOut) {
        SessionStore.save(out.token)
        me = out.user
        Session.cachedMe = out.user
        Monitoring.setUser(out.user.id)
        phase = .signedIn
    }

    func signOut() async {
        await Push.shared.unregister()
        try? await API.shared.call("POST", "/v1/auth/logout")
        signOutLocally()
    }

    func signOutLocally() {
        SessionStore.clear()
        Monitoring.setUser(nil)
        me = nil
        Session.cachedMe = nil
        phase = .signedOut
    }
}
