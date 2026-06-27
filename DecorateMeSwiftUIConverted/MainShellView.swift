import SwiftUI

enum DMColor {
    static let ink = Color(red: 0.17, green: 0.13, blue: 0.14)
    static let ink2 = Color(red: 0.22, green: 0.16, blue: 0.18)
    static let ink3 = Color(red: 0.28, green: 0.20, blue: 0.22)
    static let ivory = Color(red: 0.92, green: 0.84, blue: 0.82)
    static let ivory2 = Color(red: 0.87, green: 0.77, blue: 0.75)
    static let paper = Color(red: 0.96, green: 0.90, blue: 0.88)
    static let white = Color(red: 0.965, green: 0.92, blue: 0.905)
    static let blush = Color(red: 0.85, green: 0.55, blue: 0.51)
    static let blushSoft = Color(red: 0.95, green: 0.81, blue: 0.78)
    static let gold = Color(red: 0.75, green: 0.54, blue: 0.48)
    static let goldSoft = Color(red: 0.91, green: 0.77, blue: 0.70)
    static let goldDeep = Color(red: 0.64, green: 0.40, blue: 0.35)
    static let muted = Color(red: 0.58, green: 0.43, blue: 0.40)
    static let line = Color(red: 0.39, green: 0.25, blue: 0.24).opacity(0.14)

    static var goldGradient: LinearGradient {
        LinearGradient(
            colors: [goldDeep, goldSoft, Color.white.opacity(0.92), goldSoft, goldDeep],
            startPoint: .leading,
            endPoint: .trailing
        )
    }

    static var roseButtonGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.95, green: 0.78, blue: 0.82),
                Color(red: 0.93, green: 0.82, blue: 0.78),
                Color(red: 0.90, green: 0.76, blue: 0.58)
            ],
            startPoint: .leading,
            endPoint: .trailing
        )
    }
}

struct MainShellView: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        ZStack {
            background.ignoresSafeArea()

            VStack(spacing: 0) {
                topbar

                ScrollView(showsIndicators: false) {
                    pageView
                        .padding(.horizontal, 18)
                        .padding(.top, 22)
                        .padding(.bottom, 70)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                        .animation(.easeInOut(duration: 0.30), value: state.currentPage)
                }
            }
        }
    }

    private var background: some View {
        ZStack {
            DMColor.ivory
            RadialGradient(
                colors: [DMColor.blushSoft.opacity(0.48), .clear],
                center: .topLeading,
                startRadius: 20,
                endRadius: 380
            )
            RadialGradient(
                colors: [DMColor.goldSoft.opacity(0.30), .clear],
                center: .bottomTrailing,
                startRadius: 20,
                endRadius: 420
            )
        }
    }

    private var topbar: some View {
        VStack(spacing: 0) {
            Text("裝識你的美・DECORATE ME")
                .font(.system(size: 17, weight: .bold, design: .default))
                .foregroundStyle(Color.black)
                .frame(maxWidth: .infinity)
                .padding(.top, 18)
                .padding(.bottom, 14)
                .background(Color.white)

            Rectangle()
                .fill(Color.black.opacity(0.08))
                .frame(height: 1)
        }
        .background(Color.white)
    }

    @ViewBuilder private var pageView: some View {
        switch state.currentPage {
        case .dashboard: DashboardView()
        case .analysis: AnalysisView()
        case .style: StyleView()
        case .products: ProductsView()
        case .favorites: FavoritesView()
        case .history: HistoryView()
        case .compare: CompareView()
        case .suggestion: SuggestionView()
        case .profile: ProfileView()
        }
    }
}

extension Text {
    func dmPrimaryButton() -> some View {
        self.font(.system(size: 13, weight: .medium, design: .rounded))
            .tracking(2.3)
            .foregroundStyle(Color(red: 0.36, green: 0.23, blue: 0.22))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 15)
            .background(DMColor.roseButtonGradient, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.60), lineWidth: 1))
            .shadow(color: DMColor.goldDeep.opacity(0.22), radius: 16, y: 8)
    }

    func dmOutlineButton() -> some View {
        self.font(.system(size: 12, weight: .medium, design: .rounded))
            .tracking(2.1)
            .foregroundStyle(DMColor.goldDeep)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13)
            .background(.white.opacity(0.42), in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            .shadow(color: DMColor.goldDeep.opacity(0.09), radius: 10, y: 5)
    }
}

struct PageHeader: View {
    let eyebrow: String
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(eyebrow)
                .font(.system(size: 10.5, weight: .regular, design: .rounded))
                .tracking(4.2)
                .textCase(.uppercase)
                .foregroundStyle(DMColor.goldDeep)

            Text(title)
                .font(.system(size: 36, weight: .medium, design: .serif))
                .tracking(2.2)
                .foregroundStyle(DMColor.ink)

            Rectangle()
                .fill(DMColor.gold)
                .frame(width: 46, height: 1)

            if !subtitle.isEmpty {
                Text(subtitle)
                    .font(.system(size: 14, weight: .light, design: .serif))
                    .foregroundStyle(DMColor.muted)
                    .lineSpacing(3)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 6)
    }
}
