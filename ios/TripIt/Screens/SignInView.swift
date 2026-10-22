import SwiftUI

/// Sign in, or join with an invite code (TripIt is invite-only while it's being tested).
struct SignInView: View {
    @Environment(Session.self) private var session
    @State private var joining = false
    @State private var email = ""
    @State private var password = ""
    @State private var name = ""
    @State private var invite = ""
    @State private var busy = false
    @State private var error: String?
    @FocusState private var focus: Field?

    enum Field { case email, password, name, invite }

    var body: some View {
        ScrollView {
            VStack(spacing: 22) {
                VStack(spacing: 8) {
                    Image(systemName: "bookmark.fill")
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(Theme.accentInk)
                        .frame(width: 64, height: 64)
                        .background(Theme.accent, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    Text("TripIt").font(Theme.serif(40))
                    Text(joining ? "Create your account with the invite code you were sent."
                                 : "Every place you save from TikTok and Instagram, ready for your next trip.")
                        .font(.subheadline).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                }
                .padding(.top, 48)

                Picker("", selection: $joining) {
                    Text("Sign in").tag(false)
                    Text("I have an invite").tag(true)
                }
                .pickerStyle(.segmented)

                Card {
                    if joining {
                        field("Invite code", text: $invite, field: .invite)
                            .textInputAutocapitalization(.characters)
                        Divider().padding(.leading, 16)
                        field("Your name (optional)", text: $name, field: .name)
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

                if !joining {
                    Text("Forgot your password? Ask the person who invited you to reset it.")
                        .font(.footnote).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                }
            }
            .padding(.horizontal, 24)
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
        if joining, invite.trimmingCharacters(in: .whitespaces).isEmpty { error = "Enter your invite code."; return }
        busy = true
        error = nil
        Task {
            do {
                if joining {
                    try await session.signUp(email: email, password: password, name: name, invite: invite)
                } else {
                    try await session.signIn(email: email, password: password)
                }
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}
