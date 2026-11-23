import SwiftUI

/// The first screen when signed out: scenic places fading into one another behind the wordmark, a line on what the
/// app does for each scene, then Log In and Sign Up (both open the sign-in sheet).
/// The scenes are stills with a slow zoom; real footage can replace them later without changing the layout.
struct WelcomeView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var start = Date()
    @State private var pausedAt: Date?
    @State private var signIn: SignInMode?

    enum SignInMode: String, Identifiable {
        case logIn, signUp
        var id: String { rawValue }
    }

    struct Slide {
        let image: String
        let place: String
        let title: String
        let line: String
    }

    static let scenes: [Slide] = [
        Slide(image: "SceneLake", place: "Lake Lucerne, Switzerland",
              title: "Save it from a post", line: "Share any Reel or TikTok. We find every place in it."),
        Slide(image: "SceneDesert", place: "Thar Desert, Rajasthan",
              title: "Everything finds its city", line: "Your saves sort themselves, from Lisbon to the spots near home."),
        Slide(image: "SceneCoast", place: "Amalfi Coast, Italy",
              title: "Days that actually work", line: "Turn your saves into a plan with real times and short walks."),
        Slide(image: "SceneCity", place: "Paris, France",
              title: "Plan it together", line: "Invite friends, share the plan and keep bookings in one place."),
    ]

    private let period = 6.0  // seconds on each scene
    private let fade = 1.4  // crossfade between scenes

    // Also still while the sign-in sheet covers it, so it isn't redrawing every frame unseen.
    private var paused: Bool { pausedAt != nil || reduceMotion || signIn != nil }

    var body: some View {
        TimelineView(.animation(paused: paused)) { context in
            let now = pausedAt ?? context.date
            let elapsed = reduceMotion ? 0 : max(0, now.timeIntervalSince(start))
            let count = Self.scenes.count
            let current = Int(elapsed / period) % count
            let previous = (current + count - 1) % count
            let local = elapsed.truncatingRemainder(dividingBy: period)

            ZStack {
                backdrop(current: current, previous: previous, local: local, showPrevious: elapsed >= period)
                content(current: current, local: local)
            }
        }
        .background(Color.black)
        .sheet(item: $signIn) { mode in
            SignInView(joining: mode == .signUp)
                .presentationDragIndicator(.visible)
                .tint(Theme.accent)
        }
    }

    // MARK: Scenery

    private func backdrop(current: Int, previous: Int, local: Double, showPrevious: Bool) -> some View {
        GeometryReader { geo in
            ZStack {
                if showPrevious && local < fade {
                    scene(previous, age: local + period, size: geo.size)
                }
                scene(current, age: local, size: geo.size)
                    .opacity(showPrevious ? min(1, local / fade) : 1)
                LinearGradient(stops: [
                    .init(color: .black.opacity(0.38), location: 0),
                    .init(color: .black.opacity(0), location: 0.22),
                    .init(color: .black.opacity(0), location: 0.46),
                    .init(color: .black.opacity(0.55), location: 0.72),
                    .init(color: .black.opacity(0.88), location: 1),
                ], startPoint: .top, endPoint: .bottom)
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }

    /// One scene, zooming in slowly (a little over 1.1× across its time on screen).
    private func scene(_ index: Int, age: Double, size: CGSize) -> some View {
        let zoom = 1.03 + 0.08 * min(1, age / (period + fade))
        return Image(Self.scenes[index].image)
            .resizable()
            .scaledToFill()
            .frame(width: size.width, height: size.height)
            .scaleEffect(reduceMotion ? 1.03 : zoom)
            .clipped()
    }

    // MARK: Words and buttons

    private func content(current: Int, local: Double) -> some View {
        let scene = Self.scenes[current]
        // Each scene's words fade in after the crossfade and out just before the next one.
        let textOpacity: Double = reduceMotion ? 1 : min(1, max(0, (local - 0.3) / 0.7), max(0, (period - local) / 0.5))

        return VStack(spacing: 0) {
            HStack(alignment: .center) {
                Text(scene.place)
                    .font(Theme.text(.footnote)).kerning(0.8)
                    .foregroundStyle(.white.opacity(0.9))
                    .opacity(textOpacity)
                    .accessibilityHidden(true)
                Spacer()
                if !reduceMotion {
                    Button {
                        if let pausedAt {
                            start = start.addingTimeInterval(Date().timeIntervalSince(pausedAt))
                            self.pausedAt = nil
                        } else {
                            pausedAt = Date()
                        }
                    } label: {
                        Image(systemName: pausedAt == nil ? "pause.fill" : "play.fill")
                            .font(.system(size: 13))
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(.black.opacity(0.35), in: Circle())
                            .overlay(Circle().strokeBorder(.white.opacity(0.3)))
                    }
                    .accessibilityLabel(pausedAt == nil ? "Pause background" : "Play background")
                }
            }
            .padding(.top, 8)

            Spacer(minLength: 0)

            VStack(spacing: 12) {
                Text("THE")
                    .font(.custom(Theme.fontName, size: 13)).kerning(6)
                Text("TRAVEL EDIT")
                    .font(.custom(Theme.fontName, size: 30)).kerning(8)
                    .lineLimit(1).minimumScaleFactor(0.7)
                Rectangle().fill(.white.opacity(0.7)).frame(width: 36, height: 1).padding(.top, 4)
            }
            .foregroundStyle(.white)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("The Travel Edit")
            .accessibilityAddTraits(.isHeader)

            Spacer(minLength: 0)
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text(scene.title)
                    .font(Theme.text(.callout)).kerning(0.5)
                    .foregroundStyle(.white.opacity(0.9))
                Text(scene.line)
                    .font(Theme.serif(25))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minHeight: 66, alignment: .top)
            }
            .opacity(textOpacity)
            .padding(.horizontal, 8)

            HStack(spacing: 8) {
                ForEach(Self.scenes.indices, id: \.self) { i in
                    Capsule()
                        .fill(i == current ? Color.white : Color.white.opacity(0.45))
                        .frame(width: i == current ? 24 : 7, height: 7)
                }
            }
            .animation(.easeInOut(duration: 0.4), value: current)
            .padding(.top, 22)
            .accessibilityHidden(true)

            VStack(spacing: 12) {
                Button("Log In") { signIn = .logIn }
                    .buttonStyle(WelcomeButtonStyle(filled: true))
                Button("Sign Up") { signIn = .signUp }
                    .buttonStyle(WelcomeButtonStyle(filled: false))
            }
            .padding(.top, 28)
            .padding(.bottom, 12)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: 480)
    }
}

/// The welcome screen's pills: white with ink text, or outlined in white.
private struct WelcomeButtonStyle: ButtonStyle {
    let filled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.custom(Theme.fontName, size: 17, relativeTo: .body)).kerning(0.6)
            .frame(maxWidth: .infinity, minHeight: 56)
            .foregroundStyle(filled ? Color(red: 0.098, green: 0.067, blue: 0.043) : .white)
            .background(filled ? Color.white : Color.clear, in: Capsule())
            .overlay(Capsule().strokeBorder(.white.opacity(filled ? 0 : 0.7), lineWidth: 1))
            .opacity(configuration.isPressed ? 0.8 : 1)
            .contentShape(Capsule())
    }
}
