import AuthenticationServices
import CryptoKit
import SwiftUI

/// Sign in or create an account: with Apple in one tap, or with an email and password.
struct SignInView: View {
    @Environment(Session.self) private var session
    @Environment(\.colorScheme) private var colorScheme
    @State private var joining = false
    @State private var email = ""
    @State private var password = ""
    @State private var name = ""
    @State private var busy = false
    @State private var error: String?
    @State private var nonce = ""
    @FocusState private var focus: Field?

    enum Field { case email, password, name }

    var body: some View {
        ScrollView {
            VStack(spacing: 22) {
                VStack(spacing: 14) {
                    Image("Wordmark").resizable().scaledToFit().frame(width: 190)
                        .accessibilityLabel("The Travel Edit")
                    Text("Every place you save from TikTok and Instagram, ready for your next trip.")
                        .font(.subheadline).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                }
                .padding(.top, 40)

                SignInWithAppleButton(joining ? .signUp : .signIn) { request in
                    nonce = Self.randomNonce()
                    request.requestedScopes = [.fullName, .email]
                    request.nonce = Self.sha256(nonce)
                } onCompletion: { result in
                    Task { await apple(result) }
                }
                .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
                .frame(height: 50)
                .clipShape(Capsule())
                .disabled(busy)

                HStack(spacing: 10) {
                    Rectangle().fill(Theme.border).frame(height: 1)
                    Text("or with email").font(.caption).foregroundStyle(Theme.tertiary).fixedSize()
                    Rectangle().fill(Theme.border).frame(height: 1)
                }

                Picker("", selection: $joining) {
                    Text("Sign in").tag(false)
                    Text("Create account").tag(true)
                }
                .pickerStyle(.segmented)

                Card {
                    if joining {
                        field("Your first name", text: $name, field: .name)
                            .textContentType(.givenName)
                        Divider().padding(.leading, 16)
                    }
                    field("Email", text: $email, field: .email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                    Divider().padding(.leading, 16)
                    SecureField(joining ? "Password (at least 8 characters)" : "Password", text: $password)
                        .textContentType(joining ? .newPassword : .password)
                        .focused($focus, equals: .password)
                        .submitLabel(.go)
                        .onSubmit(submit)
                        .padding(16)
                }
                .autocorrectionDisabled()

                if let error {
                    Text(error).font(.subheadline).foregroundStyle(Theme.danger).multilineTextAlignment(.center)
                }

                Button(action: submit) {
                    if busy { ProgressView().tint(Theme.accentInk) } else { Text(joining ? "Create account" : "Sign in") }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(busy)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
            .frame(maxWidth: 480)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Theme.background.ignoresSafeArea())
        .onChange(of: joining) { _, _ in error = nil }
    }

    private func field(_ title: String, text: Binding<String>, field: Field) -> some View {
        TextField(title, text: text)
            .focused($focus, equals: field)
            .submitLabel(.next)
            .padding(16)
    }

    private func submit() {
        guard !busy else { return }
        let email = email.trimmingCharacters(in: .whitespaces)
        guard !email.isEmpty, !password.isEmpty else { error = "Enter your email and password."; return }
        busy = true
        error = nil
        Task {
            do {
                if joining {
                    try await session.signUp(email: email, password: password, name: name, invite: "")
                } else {
                    try await session.signIn(email: email, password: password)
                }
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }

    private func apple(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .failure(let failure):
            if (failure as? ASAuthorizationError)?.code != .canceled { error = "Sign in with Apple didn't work. Try again." }
        case .success(let auth):
            guard let credential = auth.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken, let token = String(data: tokenData, encoding: .utf8) else {
                error = "Sign in with Apple didn't work. Try again."
                return
            }
            let code = credential.authorizationCode.flatMap { String(data: $0, encoding: .utf8) }
            let name = [credential.fullName?.givenName, credential.fullName?.familyName].compactMap { $0 }.joined(separator: " ")
            busy = true
            error = nil
            do {
                try await session.signInWithApple(token: token, code: code, nonce: nonce, name: name)
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }

    /// A random string the app keeps; Apple puts its SHA-256 in the token so the server knows it's this sign-in.
    static func randomNonce(length: Int = 32) -> String {
        let chars = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
        var generator = SystemRandomNumberGenerator()
        return String((0..<length).map { _ in chars.randomElement(using: &generator)! })
    }

    static func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
