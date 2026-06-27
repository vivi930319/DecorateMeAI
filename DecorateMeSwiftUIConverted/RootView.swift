import SwiftUI

struct RootView: View {
    @EnvironmentObject private var state: AppState
    @State private var introDone = false

    var body: some View {
        ZStack {
            if state.isLoggedIn {
                MainShellView()
            } else {
                LoginView()
            }

            if !introDone {
                BrandIntroView()
                    .transition(.opacity)
                    .onTapGesture { withAnimation(.easeInOut(duration: 0.45)) { introDone = true } }
                    .task {
                        try? await Task.sleep(nanoseconds: 2_500_000_000)
                        withAnimation(.easeInOut(duration: 0.75)) { introDone = true }
                    }
            }
        }
    }
}

struct BrandIntroView: View {
    @State private var reveal = false
    @State private var glint = false

    var body: some View {
        ZStack {
            DMColor.ink.ignoresSafeArea()
            RadialGradient(colors: [DMColor.gold.opacity(0.28), .clear], center: .center, startRadius: 20, endRadius: 280)
                .ignoresSafeArea()
                .opacity(reveal ? 1 : 0)
            VStack(spacing: 20) {
                ZStack(alignment: .leading) {
                    Text("裝識你的美")
                        .font(.system(size: 44, weight: .medium, design: .serif))
                        .tracking(8)
                        .foregroundStyle(DMColor.goldGradient)
                        .opacity(reveal ? 1 : 0.35)
                    Rectangle()
                        .fill(DMColor.ink)
                        .frame(width: reveal ? 0 : 280, height: 64)
                        .offset(x: reveal ? 310 : 0)
                    Rectangle()
                        .fill(.white.opacity(0.85))
                        .frame(width: 3, height: 78)
                        .blur(radius: 1)
                        .shadow(color: DMColor.gold.opacity(0.7), radius: 18)
                        .offset(x: glint ? 300 : -20)
                        .opacity(glint ? 0 : 1)
                }
                Rectangle()
                    .fill(DMColor.gold.opacity(0.45))
                    .frame(width: reveal ? 220 : 0, height: 1)
                Text("Decorate Me · Beauty Atelier")
                    .font(.system(size: 11, weight: .regular, design: .rounded))
                    .tracking(5)
                    .foregroundStyle(DMColor.goldSoft)
                    .opacity(reveal ? 1 : 0)
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.2).delay(0.25)) { reveal = true }
            withAnimation(.easeInOut(duration: 1.15).delay(0.2)) { glint = true }
        }
    }
}
