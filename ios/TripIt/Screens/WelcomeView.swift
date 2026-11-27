import SwiftUI

/// The first screen when signed out, as in the design: scenic places fading into one another behind the wordmark,
/// one line on what the app is, then Log In and Sign Up (both open the sign-in sheet). The scenes are stills with a
/// slow zoom and hold still for Reduce Motion. `WelcomeScenery` is shared with Home's header.
struct WelcomeView: View {
    @State private var signIn: SignInMode?
    @State private var jump: Int?

    enum SignInMode: String, Identifiable {
        case logIn, signUp
        var id: String { rawValue }
    }

    var body: some View {
        // Still while the sign-in sheet covers it, so it isn't redrawing every frame unseen.
        WelcomeScenery(paused: signIn != nil, swipeable: true, jump: $jump, world: WelcomeSceneryStyle.scenes) { current, textOpacity in
            content(current: current, textOpacity: textOpacity)
        }
        .background(Color.black)
        .sheet(item: $signIn) { mode in
            SignInView(joining: mode == .signUp)
                .presentationDragIndicator(.visible)
                .tint(Theme.accent)
        }
    }

    private func content(current: Int, textOpacity: Double) -> some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text(WelcomeSceneryStyle.scenes[current].place)
                    .font(Theme.text(.footnote)).kerning(0.8)
                    .foregroundStyle(.white.opacity(0.88))
                if let photo = WelcomeSceneryStyle.scenes[current].photo {
                    Text(photo.credit).font(Theme.text(.caption2)).foregroundStyle(.white.opacity(0.6))
                }
            }
            .opacity(textOpacity)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .accessibilityHidden(true)

            Spacer(minLength: 0)

            VStack(spacing: 12) {
                Text("THE")
                    .font(Theme.serif(13)).kerning(6.5)
                Text("TRAVEL EDIT")
                    .font(Theme.serif(31, weight: .light)).kerning(9.3)
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
                Text("Your saved places")
                    .font(Theme.text(.body)).kerning(0.7)
                    .foregroundStyle(.white.opacity(0.9))
                Text("From a Reel you loved\nto a trip you\u{2019}ll take.")
                    .font(Theme.serif(26))
                    .lineSpacing(4)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                ForEach(0..<WelcomeSceneryStyle.scenes.count, id: \.self) { i in
                    Button { jump = i } label: {
                        Capsule()
                            .fill(i == current ? Color.white : Color.white.opacity(0.45))
                            .frame(width: i == current ? 24 : 7, height: 7)
                            .frame(minWidth: 18, minHeight: 44)  // easier to tap than the dot itself
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Place \(i + 1) of \(WelcomeSceneryStyle.scenes.count)")
                }
            }
            .animation(.easeInOut(duration: 0.4), value: current)
            .padding(.top, 8)

            VStack(spacing: 12) {
                Button("Log In") { signIn = .logIn }
                    .buttonStyle(WelcomeButtonStyle(filled: true))
                Button("Sign Up") { signIn = .signUp }
                    .buttonStyle(WelcomeButtonStyle(filled: false))
            }
            .padding(.top, 30)
            .padding(.bottom, 12)
        }
        .padding(.horizontal, 20)
        .frame(maxWidth: 480)
    }
}

/// Scenic places crossfading with a slow zoom under a dark gradient, for the welcome screen and Home's header box.
/// The content is given the scene on screen and how visible its words should be (they fade between scenes).
struct WelcomeScenery<Content: View>: View {
    var paused = false
    var fullBleed = true  // the welcome screen runs under the status bar; Home's box doesn't
    var gradient: Gradient = WelcomeSceneryStyle.welcome
    var swipeable = false  // the welcome screen: swipe between places
    var jump: Binding<Int?>? = nil  // set to a scene's number to show it now (the welcome screen's dots)
    let world: [WorldScene]  // the drawn places to show, in order
    @ViewBuilder var content: (_ current: Int, _ textOpacity: Double) -> Content
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var start = Date()

    private let period = 9.0  // seconds on each scene
    private let fade = 1.4  // crossfade between scenes

    var body: some View {
        TimelineView(.animation(paused: paused || reduceMotion)) { context in
            let elapsed = reduceMotion ? 0 : max(0, context.date.timeIntervalSince(start))
            let count = max(1, world.count)
            let current = Int(elapsed / period) % count
            let previous = (current + count - 1) % count
            let local = elapsed.truncatingRemainder(dividingBy: period)
            // Each scene's words fade in after the crossfade and out just before the next one.
            let textOpacity: Double = reduceMotion ? 1 : min(1, max(0, (local - 0.3) / 0.7), max(0, (period - local) / 0.5))

            ZStack {
                GeometryReader { geo in
                    ZStack {
                        // The outgoing scene stays in place underneath, so the crossfade never inserts a view mid-fade.
                        scene(previous, age: local + period, size: geo.size, moving: elapsed >= period && local < fade)
                            .opacity(elapsed >= period && local < fade ? 1 : 0)
                        scene(current, age: local, size: geo.size, moving: true)
                            .opacity(elapsed >= period ? min(1, local / fade) : 1)
                        LinearGradient(gradient: gradient, startPoint: .top, endPoint: .bottom)
                    }
                }
                .ignoresSafeArea(edges: fullBleed ? .all : [])
                .accessibilityHidden(true)
                content(current, textOpacity)
            }
            .contentShape(Rectangle())
            .simultaneousGesture(DragGesture(minimumDistance: 24).onEnded { drag in
                let dx = drag.translation.width
                guard abs(dx) > 40, abs(dx) > abs(drag.translation.height) else { return }
                go(to: current + (dx < 0 ? 1 : -1), now: context.date)
            }, including: swipeable ? .all : .subviews)
        }
        .task(id: world.map(\.id)) { await SceneCache.prepare(world) }
        .onChange(of: jump?.wrappedValue) { _, index in
            guard let index, let jump else { return }
            go(to: index, now: Date())
            jump.wrappedValue = nil
        }
    }

    /// Shows this scene now, for a full turn, then carries on from it.
    private func go(to index: Int, now: Date) {
        let count = max(1, world.count)
        let loops = Int(max(0, now.timeIntervalSince(start)) / period) / count
        let target = loops * count + ((index % count) + count) % count
        withAnimation(.easeInOut(duration: 0.3)) {
            start = now.addingTimeInterval(-(Double(target) * period + fade))  // past the crossfade: a clean cut
        }
    }

    /// One scene, zooming in slowly (a little over 1.1× across its time on screen).
    @ViewBuilder private func scene(_ index: Int, age: Double, size: CGSize, moving: Bool) -> some View {
        let zoom = 1.03 + 0.08 * min(1, age / (period + fade))
        Group {
            if world.indices.contains(index) {
                WorldSceneImage(scene: world[index], moving: moving, paused: paused)
            } else {
                Color.black
            }
        }
        .frame(width: size.width, height: size.height)
        .scaleEffect(reduceMotion ? 1.03 : zoom)
        .clipped()
    }
}

/// The scenes, and the darkening laid over them so white words stay readable.
enum WelcomeSceneryStyle {
    /// The welcome screen's places, drawn like Home's header.
    static let scenes: [WorldScene] = [WorldScenes.alps, WorldScenes.jaipur, WorldScenes.amalfi, WorldScenes.paris,
                                       WorldScenes.kyoto, WorldScenes.santorini]

    static let welcome = Gradient(stops: [
        .init(color: .black.opacity(0.38), location: 0),
        .init(color: .black.opacity(0), location: 0.22),
        .init(color: .black.opacity(0), location: 0.46),
        .init(color: .black.opacity(0.55), location: 0.72),
        .init(color: .black.opacity(0.88), location: 1),
    ])

    /// Home's header box: a little shade at the top for the date, more at the bottom for the greeting.
    static let header = Gradient(stops: [
        .init(color: .black.opacity(0.35), location: 0),
        .init(color: .black.opacity(0.05), location: 0.3),
        .init(color: .black.opacity(0.1), location: 0.5),
        .init(color: .black.opacity(0.7), location: 1),
    ])
}

/// The welcome screen's pills: white with ink text, or outlined in white.
private struct WelcomeButtonStyle: ButtonStyle {
    let filled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.text(.headline, weight: .medium)).kerning(0.7)
            .frame(maxWidth: .infinity, minHeight: 58)
            .foregroundStyle(filled ? Color(red: 0.098, green: 0.067, blue: 0.043) : .white)
            .background(filled ? Color.white : Color.clear, in: Capsule())
            .overlay(Capsule().strokeBorder(.white.opacity(filled ? 0 : 0.7), lineWidth: 1))
            .opacity(configuration.isPressed ? 0.8 : 1)
            .contentShape(Capsule())
    }
}
